#!/usr/bin/env python3
"""三菱UFJ銀行の入出金明細CSVを、用途別に集計する。

    python3 bank_mufg.py <csv_path> [<csv_path> ...] [--month YYYY-MM]

複数ファイルを渡せる（期間が重なっていても重複は自動で除去する）。

【重要】カード引落はカード明細と二重計上しない。
銀行側の「カード引落」はカード会社への支払総額で、カード明細はその内訳。
両方を支出に数えると2倍になる。生活費の総額は銀行側で押さえ、
カテゴリの内訳はカード明細側で見る、という使い分けにする。
"""
import argparse
import collections
import csv
import json
import re
import sys

ENCODINGS = ["cp932", "utf-8-sig", "utf-8"]

# 摘要内容に含まれる文字列 → 用途。上から順に最初に当たったものを採用する。
CATEGORIES = [
    ("給与",            ["給料"],                  "収入"),
    ("賞与",            ["賞与"],                  "収入"),
    ("家賃収入",        ["カ）シ－ラ", "カ)シーラ"], "不動産"),
    ("税還付",          ["ゼイムシヨ", "税務署"],   "収入"),
    ("児童手当",        ["コドモセイサク", "ジドウテアテ"], "収入"),
    ("証券からの入金",  ["シヨウケン"],            "資産移動"),
    ("不動産ローン",    ["オリツクス", "オリックス"], "不動産"),
    ("管理費等",        ["カンリヒトウ"],          "不動産"),
    ("火災保険",        ["カイジヨウ", "ソンポ"],   "不動産"),
    ("カード引落",      ["カ－ド", "カード", "ミツイスミトモＣ", "メルペイ"], "カード"),
    ("生命保険",        ["セイメイ"],              "生活"),
    ("奨学金",          ["ガクセイシエン"],        "生活"),
    ("水道",            ["スイドウ"],              "生活"),
    ("教育",            ["ワ－ルドフアミリ", "スポ－ツ"], "生活"),
    ("食材宅配",        ["セイカツクラブ"],        "生活"),
    ("会社の精算",      ["コクナイリヨヒ", "トヨタアオバ"], "その他"),
    ("口座間移動・出金", ["サトウ", "シラカワ", "ギンコウＡＴＭ", "リヨウキヨク"], "資産移動"),
]


def read_rows(paths):
    rows, seen = [], set()
    for path in paths:
        for enc in ENCODINGS:
            try:
                with open(path, encoding=enc, newline="") as f:
                    parsed = list(csv.DictReader(f))
                break
            except UnicodeDecodeError:
                continue
        else:
            raise SystemExit(f"文字コードを判定できませんでした: {path}")
        for row in parsed:
            # 同じ取引が複数ファイルに入っていることがある（期間の重なり）
            key = (row.get("日付"), row.get("摘要"), row.get("摘要内容"),
                   row.get("支払い金額"), row.get("預かり金額"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def amount(row):
    def num(v):
        v = re.sub(r"[,\s]", "", v or "")
        return int(v) if v else 0
    return num(row.get("預かり金額")) - num(row.get("支払い金額"))


def month_of(value):
    m = re.match(r"\s*(\d{4})/(\d{1,2})", str(value or ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else None


def classify(row):
    text = (row.get("摘要内容") or "").strip()
    label = (row.get("摘要") or "").strip()
    for name, keys, group in CATEGORIES:
        if any(k in text for k in keys):
            return name, group
    if label in ("カ－ド", "カードＣ１", "ゆうちょ"):
        return "口座間移動・出金", "資産移動"
    if label in ("給料", "賞与", "利息"):
        return label, "収入"
    return f"未分類：{text or label}", "未分類"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv_paths", nargs="+")
    p.add_argument("--month", help="YYYY-MM。省略すると全期間を月別に出す")
    args = p.parse_args()

    rows = read_rows(args.csv_paths)
    by_month = collections.defaultdict(lambda: collections.defaultdict(int))
    groups = collections.defaultdict(lambda: collections.defaultdict(int))
    unknown = collections.defaultdict(int)

    for row in rows:
        m = month_of(row.get("日付"))
        if not m or (args.month and m != args.month):
            continue
        name, group = classify(row)
        value = amount(row)
        by_month[m][name] += value
        groups[m][group] += value
        if group == "未分類":
            unknown[name] += value

    months = sorted(by_month)
    # 端の月は期間が欠けているので平均から外す
    full = months[1:-1] if len(months) > 2 else months

    out = {
        "件数": len(rows),
        "月別": {m: dict(sorted(by_month[m].items(), key=lambda kv: kv[1])) for m in months},
        "完全な月": full,
        "月平均": {},
        "warnings": [],
    }
    if full:
        keys = {k for m in full for k in by_month[m]}
        out["月平均"] = {k: sum(by_month[m][k] for m in full) // len(full) for k in keys}
        out["月平均"] = dict(sorted(out["月平均"].items(), key=lambda kv: kv[1]))

    for name, total in sorted(unknown.items(), key=lambda kv: abs(kv[1]), reverse=True):
        out["warnings"].append(f"{name}（計 {total:,}円）を分類できませんでした。CATEGORIES に追記してください。")
    out["warnings"].append(
        "カード引落はカード明細と二重計上しないこと。総額は銀行側、内訳はカード明細側で見る。")

    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
