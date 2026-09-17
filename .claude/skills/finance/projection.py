#!/usr/bin/env python3
"""不労所得が生活費を上回る（＝経済的自立）までの年数を試算する。

  python3 projection.py --annual-expense 2400000 --financial-assets 8000000 \
      --annual-savings 1800000 --annual-rent-income 1140000

前提を明示するために、すべての仮定はコマンドライン引数で見えるようにしてある。
デフォルト値は目安であって、本人の状況に合わせて変えるためのもの。
"""
import argparse
import json
import sys


def years_to_target(assets, annual_savings, target, rate):
    """毎年末に積立を加え、年利 rate で複利運用した場合に target に届く年数。"""
    if assets >= target:
        return 0.0
    if annual_savings <= 0 and rate <= 0:
        return None
    balance, years = assets, 0
    while years < 100:
        balance = balance * (1 + rate) + annual_savings
        years += 1
        if balance >= target:
            # 年の途中で到達する分を線形に補間する
            previous = (balance - annual_savings) / (1 + rate)
            gain = balance - previous
            return round(years - 1 + (target - previous) / gain, 1) if gain > 0 else float(years)
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--annual-expense", type=float, required=True, help="年間支出（円）")
    p.add_argument("--financial-assets", type=float, required=True, help="現在の金融資産＝現金預金＋証券＋年金資産（円）")
    p.add_argument("--annual-savings", type=float, required=True, help="年間の貯蓄額＝収支の年間合計（円）")
    p.add_argument("--annual-rent-income", type=float, default=0, help="年間の家賃収入（円）。資産を取り崩さずに得られる分")
    p.add_argument("--debt", type=float, default=0, help="金融資産から差し引く負債（カード未払・住宅以外のローン）")
    p.add_argument("--return-rate", type=float, default=0.05, help="想定運用利回り（名目）。既定 5%%")
    p.add_argument("--withdrawal-rate", type=float, default=0.04, help="安全な取り崩し率。既定 4%%")
    p.add_argument("--current-year", type=int, default=None)
    args = p.parse_args()

    if args.current_year is None:
        from datetime import date
        args.current_year = date.today().year

    # 家賃収入は資産を取り崩さずに得られるので、その分だけ必要な金融資産が減る
    expense_to_cover = max(args.annual_expense - args.annual_rent_income, 0)
    target = expense_to_cover / args.withdrawal_rate if args.withdrawal_rate > 0 else None
    assets = args.financial_assets - args.debt

    years = years_to_target(assets, args.annual_savings, target, args.return_rate) if target else None

    out = {
        "前提": {
            "年間支出": args.annual_expense,
            "年間家賃収入": args.annual_rent_income,
            "取り崩し率": args.withdrawal_rate,
            "想定運用利回り": args.return_rate,
        },
        "必要金融資産": round(target) if target else None,
        "現在の金融資産（負債控除後）": round(assets),
        "年間貯蓄額": args.annual_savings,
        "到達までの年数": years,
        "到達予測年": args.current_year + int(years) if years is not None else None,
        "注意": [
            "取り崩し率4%は米国株の過去データに基づく経験則で、日本の税制・為替・年金を織り込んでいない。",
            "運用益や配当にかかる税金（約20%）を控除していないため、結果は楽観側に出る。",
            "年間支出が将来変わる前提（子の独立、医療費の増加など）は含めていない。",
            "この数字は精度を競うものではなく、今のペースが目標に対して速いか遅いかを見るためのもの。",
        ],
    }
    if years is None:
        out["到達までの年数"] = "100年以内に到達しない試算。貯蓄額か利回りの前提を見直すこと。"

    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
