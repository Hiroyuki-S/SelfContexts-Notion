#!/usr/bin/env python3
"""マネーフォワードMEの家計簿CSVを、Notion「📈 家計サマリー（月次）」の列に集計する。

使い方:
    python3 aggregate.py <csv_path> <YYYY-MM> [--mapping mapping.yaml]

標準出力にJSONを返す。未知の大項目があれば warnings に入れて返す（黙って握りつぶさない）。
"""
import argparse
import csv
import io
import json
import os
import re
import sys

ENCODINGS = ["utf-8-sig", "cp932", "utf-8"]


def load_mapping(path):
    """依存を増やさないため、この用途に必要な範囲だけのYAMLパーサを使う。"""
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        pass

    data, section, out = {}, None, {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            body = line.strip()
            if indent == 0 and body.endswith(":"):
                section = body[:-1]
                data[section] = [] if section == "exclude" else {}
                continue
            if section is None:
                continue
            if body.startswith("- "):
                data[section].append(body[2:].strip())
            elif ":" in body:
                k, v = body.split(":", 1)
                v = v.split("#")[0].strip()
                data[section][k.strip()] = v
    return data


def read_rows(path):
    last_err = None
    for enc in ENCODINGS:
        try:
            with open(path, encoding=enc, newline="") as f:
                text = f.read()
            return list(csv.DictReader(io.StringIO(text))), enc
        except UnicodeDecodeError as e:
            last_err = e
    raise SystemExit(f"CSVの文字コードを判定できませんでした: {last_err}")


def parse_amount(value):
    if value is None:
        return 0
    cleaned = re.sub(r"[,\s¥円]", "", str(value))
    if not cleaned or cleaned in {"-", "―"}:
        return 0
    try:
        return int(round(float(cleaned)))
    except ValueError:
        return 0


def month_of(value):
    """2026/09/17, 2026-09-17, 2026/9/17 のいずれでも YYYY-MM を返す。"""
    m = re.match(r"\s*(\d{4})[/-](\d{1,2})", str(value or ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else None


def aggregate(rows, mapping, target_month):
    cols = mapping["csv_columns"]
    income_map, expense_map = mapping["income"], mapping["expense"]
    excluded = set(mapping.get("exclude") or [])

    totals, warnings = {}, []
    unknown, counted, skipped = {}, 0, {"月外": 0, "計算対象外": 0, "振替": 0, "除外項目": 0}

    for row in rows:
        if month_of(row.get(cols["date"])) != target_month:
            skipped["月外"] += 1
            continue
        if str(row.get(cols["target"], "1")).strip() not in {"1", "True", "true"}:
            skipped["計算対象外"] += 1
            continue
        if str(row.get(cols["transfer"], "0")).strip() in {"1", "True", "true"}:
            skipped["振替"] += 1
            continue

        major = (row.get(cols["major"]) or "").strip()
        if major in excluded:
            skipped["除外項目"] += 1
            continue

        amount = parse_amount(row.get(cols["amount"]))
        if amount == 0:
            continue

        # MFの仕様：プラスが収入、マイナスが支出。大項目より符号を優先する。
        table = income_map if amount > 0 else expense_map
        column = table.get(major)
        if column is None:
            unknown[major] = unknown.get(major, 0) + abs(amount)
            column = "その他収入" if amount > 0 else "その他支出"

        totals[column] = totals.get(column, 0) + abs(amount)
        counted += 1

    income_cols = sorted(set(income_map.values()))
    expense_cols = sorted(set(expense_map.values()))
    income_total = sum(totals.get(c, 0) for c in income_cols)
    expense_total = sum(totals.get(c, 0) for c in expense_cols)
    balance = income_total - expense_total
    passive = totals.get("配当", 0) + totals.get("家賃収入", 0)

    result = {k: v for k, v in sorted(totals.items())}
    result.update({
        "収入合計": income_total,
        "支出合計": expense_total,
        "収支": balance,
        "貯蓄率": round(balance / income_total, 4) if income_total else None,
        "不労所得": passive,
        "不労所得カバー率": round(passive / expense_total, 4) if expense_total else None,
    })

    for major, amount in sorted(unknown.items(), key=lambda kv: -kv[1]):
        warnings.append(
            f"未知の大項目「{major}」（合計 {amount:,}円）を『その他』に入れました。"
            f"mapping.yaml に追記してください。"
        )
    if counted == 0:
        warnings.append(f"{target_month} の対象行が0件でした。CSVの期間と対象月を確認してください。")

    return {
        "対象月": target_month,
        "集計値": result,
        "件数": {"集計対象": counted, **skipped},
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("month", help="YYYY-MM")
    parser.add_argument("--mapping", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "mapping.yaml"))
    args = parser.parse_args()

    if not re.fullmatch(r"\d{4}-\d{2}", args.month):
        raise SystemExit("月は YYYY-MM の形式で指定してください")

    rows, encoding = read_rows(args.csv_path)
    out = aggregate(rows, load_mapping(args.mapping), args.month)
    out["読み込み"] = {"行数": len(rows), "文字コード": encoding}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
