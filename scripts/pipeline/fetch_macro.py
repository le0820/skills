#!/usr/bin/env python3
"""fetch_macro.py — 拉取 CN 宏观数据（PMI/CPI/PPI/M2/TSF/零售/LPR）

Usage:
    cd repo_skills/scripts/pipeline
    uv run python fetch_macro.py [--date YYYYMMDD]
"""

import json, sys, os
from datetime import datetime
from typing import Optional, Dict, Any

import pandas as pd
import akshare as ak

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output", "data")
os.makedirs(DATA_DIR, exist_ok=True)

def _latest_by_date(df: pd.DataFrame, col: str, date_col: str) -> Optional[float]:
    """Extract value from row with most recent date. Sorts by date desc, returns first non-NaN."""
    # Normalize date column: extract year-month from Chinese format
    dates = df[date_col].astype(str)
    # Try formats: "2026年04月份" → 202604, "202604" → 202604, "2026-04-20" → 202604
    parsed = dates.str.extract(r"(\d{4})\D*(\d{1,2})").dropna()
    if parsed.empty:
        # Fallback: use last row
        s = df[col].dropna()
        return float(s.iloc[-1]) if len(s) > 0 else None
    # Create sort key: year*100 + month
    sort_key = parsed[0].astype(int) * 100 + parsed[1].astype(int)
    df = df.assign(_sort=sort_key)
    df = df.sort_values("_sort", ascending=False)
    s = df[col].dropna()
    val = float(s.iloc[0]) if len(s) > 0 else None
    return val

def _latest(df: pd.DataFrame, col: str) -> Optional[float]:
    """Simple last-value extractor for numeric-only indices."""
    s = df[col].dropna()
    return float(s.iloc[-1]) if len(s) > 0 else None

def fetch_all(date_str: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"timestamp": datetime.utcnow().isoformat() + "Z", "data_date": date_str}
    errors = []

    # ── PMI ──
    try:
        df = ak.macro_china_pmi()
        result["pmi_mfg"] = _latest_by_date(df, "制造业-指数", "月份")
        result["pmi_non_mfg"] = _latest_by_date(df, "非制造业-指数", "月份")
        print(f"  PMI 制造业={result['pmi_mfg']}, 非制造={result['pmi_non_mfg']}")
    except Exception as e:
        errors.append(f"PMI: {e}")

    # ── CPI ──
    try:
        df = ak.macro_china_cpi()
        result["cpi_yoy"] = _latest_by_date(df, "全国-同比增长", "月份")
        print(f"  CPI YoY={result['cpi_yoy']}%")
    except Exception as e:
        errors.append(f"CPI: {e}")

    # ── PPI ──
    try:
        df = ak.macro_china_ppi()
        result["ppi_yoy"] = _latest_by_date(df, "当月同比增长", "月份")
        print(f"  PPI YoY={result['ppi_yoy']}%")
    except Exception as e:
        errors.append(f"PPI: {e}")

    # ── M2 / M1 ──
    try:
        df = ak.macro_china_money_supply()
        result["m2_yoy"] = _latest_by_date(df, "货币和准货币(M2)-同比增长", "月份")
        result["m1_yoy"] = _latest_by_date(df, "货币(M1)-同比增长", "月份")
        print(f"  M2={result['m2_yoy']}%, M1={result['m1_yoy']}%")
    except Exception as e:
        errors.append(f"M2: {e}")

    # ── TSF (社融) ──
    try:
        df = ak.macro_china_shrzgm()
        result["tsf_monthly"] = _latest_by_date(df, "社会融资规模增量", "月份")
        print(f"  TSF增量={result['tsf_monthly']}")
    except Exception as e:
        errors.append(f"TSF: {e}")

    # ── 零售 ──
    try:
        df = ak.macro_china_consumer_goods_retail()
        result["retail_sales_yoy"] = _latest_by_date(df, "同比增长", "月份")
        print(f"  零售YoY={result['retail_sales_yoy']}%")
    except Exception as e:
        errors.append(f"零售: {e}")

    # ── LPR ──
    try:
        df = ak.macro_china_lpr()
        df = df.dropna(subset=["LPR1Y", "LPR5Y"])
        result["lpr_1y"] = _latest_by_date(df, "LPR1Y", "TRADE_DATE")
        result["lpr_5y"] = _latest_by_date(df, "LPR5Y", "TRADE_DATE")
        print(f"  LPR 1Y={result['lpr_1y']}%, 5Y={result['lpr_5y']}%")
    except Exception as e:
        errors.append(f"LPR: {e}")

    # ── 工业增加值（akshare 函数可能因版本不同而不可用）──
    result["industrial_output_yoy"] = None  # 需 web_search 或 cn_financial_pro 补充

    result["_errors"] = errors
    return result

def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    print(f"[fetch_macro] 拉取 CN 宏观数据 (data_date={date_str})...")

    data = fetch_all(date_str)

    out_file = os.path.join(DATA_DIR, f"raw_macro_{date_str}.json")
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    n_ok = sum(1 for k, v in data.items() if v is not None and not k.startswith("_"))
    n_err = len(data["_errors"])
    print(f"\n[fetch_macro] 完成: {n_ok} 项, {n_err} 失败 → {out_file}")
    if n_err:
        for e in data["_errors"]:
            print(f"  ⚠️ {e}")

if __name__ == "__main__":
    main()
