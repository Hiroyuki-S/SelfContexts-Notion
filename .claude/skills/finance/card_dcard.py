#!/usr/bin/env python3
"""dカードの「ご利用内訳明細」CSVを支出カテゴリ別に集計する。

    python3 card_dcard.py <csv_path> [--month YYYY-MM]

このCSVには4つの落とし穴があり、素直に合計すると必ず金額を間違える。
  1. 1つのファイルに「ご利用内訳明細」と「キャッシングご返済明細」の2セクションがある
  2. 末尾に名義ごとの小計行と総合計行が混ざっている（そのまま足すと3重計上になる）
  3. ガソリンスタンドの仮売上は「利用金額」に出るが実際には請求されない
     （同額の返品行と対になり、請求額である「支払い金額」は空欄になる）
  4. 締め日が15日のため、対象期間は暦の月とずれる（7/16〜8/15 など）

そこで「利用金額」ではなく請求額である「支払い金額」を使い、小計行を除外する。
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import unicodedata

ENCODINGS = ["utf-8-sig", "cp932", "utf-8"]
SECTION_BREAK = "キャッシングご返済明細"
HEADER_FIRST_COL = "名前"


# 店名にはハイフンに見える文字が何種類も混ざる（セブン‐イレブン の ‐ は U+2010 で、
# NFKC では通常のハイフンにならない）。照合前にまとめて落とす。
DASHES = dict.fromkeys(map(ord, "-‐‑‒–—―ー－_・､，,．"), None)


def norm(text):
    """全角・半角、大文字小文字、区切り記号の揺れを吸収する。ＥＮＥＯＳ と ENEOS を同じ扱いにする。"""
    s = unicodedata.normalize("NFKC", str(text or "")).upper()
    return s.translate(DASHES).replace(" ", "").replace("\u3000", "")


def load_rules(path):
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        rules = [(r["category"], [norm(k) for k in r["keywords"]]) for r in data.get("rules", [])]
        excludes = [norm(k) for k in data.get("exclude_keywords") or []]
        return rules, excludes
    except ImportError:
        pass

    rules, excludes, current, in_exclude = [], [], None, False
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.startswith("exclude_keywords:"):
                in_exclude = True
                continue
            if line.startswith("rules:"):
                in_exclude = False
                continue
            body = line.strip()
            if in_exclude and body.startswith("- "):
                excludes.append(norm(body[2:]))
            elif body.startswith("- category:"):
                current = body.split(":", 1)[1].strip()
            elif body.startswith("keywords:") and current:
                items = body.split(":", 1)[1].strip().strip("[]")
                rules.append((current, [norm(k) for k in items.split(",") if k.strip()]))
                current = None
    return rules, excludes


def parse_amount(value):
    cleaned = re.sub(r"[,\s¥円]", "", str(value or ""))
    if not cleaned or cleaned in {"-", "―"}:
        return None
    try:
        return int(round(float(cleaned)))
    except ValueError:
        return None


def read_detail_rows(path):
    """「ご利用内訳明細」セクションだけを取り出す。キャッシング欄は別物なので混ぜない。"""
    last_err = None
    for enc in ENCODINGS:
        try:
            with open(path, encoding=enc, newline="") as f:
                text = f.read()
            break
        except UnicodeDecodeError as e:
            last_err = e
    else:
        raise SystemExit(f"CSVの文字コードを判定できませんでした: {last_err}")

    all_rows = list(csv.reader(io.StringIO(text)))
    header_index = next(
        (i for i, r in enumerate(all_rows) if r and norm(r[0]) == norm(HEADER_FIRST_COL)), None
    )
    if header_index is None:
        raise SystemExit("ヘッダー行（名前,カード番号,…）が見つかりません。dカードの明細CSVか確認してください。")

    header = [h.strip() for h in all_rows[header_index]]
    rows = []
    for row in all_rows[header_index + 1:]:
        if row and SECTION_BREAK in norm("".join(row)):
            break  # キャッシングご返済明細セクションに入ったので打ち切る
        if len(row) >= len(header):
            rows.append(dict(zip(header, row)))
    return rows, enc


def classify(store, rules):
    key = norm(store)
    for category, keywords in rules:
        if any(k and k in key for k in keywords):
            return category
    return None


def aggregate(rows, rules, excludes, target_month=None):
    totals, per_person, unmatched = {}, {}, {}
    dates, counted, skipped = [], 0, {"小計・合計行": 0, "請求なし（仮売上・返品）": 0, "除外": 0, "月外": 0}

    for row in rows:
        store = (row.get("利用店名") or "").strip()
        date = (row.get("ご利用年月日") or "").strip()
        person = (row.get("名前") or "").strip()

        # 名義ごとの小計行・総合計行。日付が無い、または店名欄が「＜◯◯様」になっている。
        if not date or store.startswith("＜") or store.startswith("<"):
            skipped["小計・合計行"] += 1
            continue

        # 請求額。仮売上と返品の対は両方とも空欄になるので、ここで自然に落ちる。
        billed = parse_amount(row.get("支払い金額"))
        if billed is None or billed == 0:
            skipped["請求なし（仮売上・返品）"] += 1
            continue

        if any(k in norm(store) for k in excludes):
            skipped["除外"] += 1
            continue

        month = None
        m = re.match(r"\s*(\d{4})[/-](\d{1,2})", date)
        if m:
            month = f"{m.group(1)}-{int(m.group(2)):02d}"
        if target_month and month != target_month:
            skipped["月外"] += 1
            continue

        category = classify(store, rules)
        if category is None:
            unmatched[store] = unmatched.get(store, 0) + billed
            category = "その他支出"

        totals[category] = totals.get(category, 0) + billed
        per_person[person] = per_person.get(person, 0) + billed
        dates.append(date)
        counted += 1

    warnings = []
    period = None
    if dates:
        period = {"開始": min(dates), "終了": max(dates)}
        months = sorted({d[:7].replace("/", "-") for d in dates})
        if not target_month and len(months) > 1:
            warnings.append(
                f"この明細は {period['開始']}〜{period['終了']} をまたいでいます（締め日15日のため）。"
                f"暦の月で集計するには --month を指定し、1ヶ月分につき2枚の明細が必要です。"
            )

    for store, amount in sorted(unmatched.items(), key=lambda kv: -kv[1]):
        warnings.append(f"未分類「{store}」{amount:,}円 → その他支出に入れました。rules_store.yaml に追記してください。")

    return {
        "対象期間": period,
        "カテゴリ別": dict(sorted(totals.items(), key=lambda kv: -kv[1])),
        "合計": sum(totals.values()),
        "名義別": dict(sorted(per_person.items(), key=lambda kv: -kv[1])),
        "件数": {"集計対象": counted, **skipped},
        "warnings": warnings,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv_path")
    p.add_argument("--month", help="YYYY-MM。指定すると暦の月で絞り込む")
    p.add_argument("--rules", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules_store.yaml"))
    args = p.parse_args()

    rows, encoding = read_detail_rows(args.csv_path)
    rules, excludes = load_rules(args.rules)
    out = aggregate(rows, rules, excludes, args.month)
    out["読み込み"] = {"明細行数": len(rows), "文字コード": encoding}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
