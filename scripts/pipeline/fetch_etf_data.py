#!/usr/bin/env python3
"""fetch_etf_data.py — 拉取 ETF 日线数据到 /tmp/ (easy-tdx 统一接口)

通过 easy-tdx SDK 统一获取所有评分所需标的的历史日K线：
  - A股ETF/指数 → MacClient
  - 美股/港美股 → MacExClient
为 p1_upgrade.py / cn_ff_regression.py 准备输入 CSV。

统一列名: datetime → trade_date (兼容旧下游脚本)

Usage:
    cd repo_skills/scripts/pipeline
    uv run python fetch_etf_data.py [--days 500]
"""

import os, sys, json
from datetime import datetime
from typing import Dict, Tuple

# ‒‒ A股: MacClient ‒‒
from easy_tdx import MacClient, Market, Period, Adjust

# ‒‒ 港股/美股: MacExClient ‒‒
from easy_tdx import MacExClient, ExMarket
import pandas as pd

# ── Configurable ticker lists ──────────────────────────────
# 格式: (market, code_in_tdx)
# Market 是 A股市场枚举, ExMarket 是扩展市场枚举
ETF_SCORING: Dict[str, Tuple] = {
    "513130.SH": (Market.SH, "513130", "恒生科技ETF"),
    "513310.SH": (Market.SH, "513310", "中韩半导体ETF"),
    "159682.SZ": (Market.SZ, "159682", "创业板50ETF"),
    "QQQ.US":    (ExMarket.US_STOCK, "QQQ", "纳斯达克100ETF"),
    "159632.SZ": (Market.SZ, "159632", "纳斯达克ETF(华安)"),
    "512760.SH": (Market.SH, "512760", "芯片ETF国泰"),
}

IDX_CN_FF: Dict[str, Tuple] = {
    "000985.SH": (Market.SZ, "000985", "中证全指"),  # TDX 中 000985 归在 SZ 市场
    "000852.SH": (Market.SH, "000852", "中证1000"),
    "000903.SH": (Market.SH, "000903", "中证100"),
    "399371.SZ": (Market.SZ, "399371", "国证价值"),
    "399370.SZ": (Market.SZ, "399370", "国证成长"),
}

OUTPUT_DIR = "/tmp"
_CUR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_MANIFEST = os.path.join(_CUR, "..", "..", "output", "data", "etf_manifest.json")


def _is_ashare(sym: str) -> bool:
    """判断是否为 A 股标的 (Market.SH/SZ)"""
    return sym.endswith(".SH") or sym.endswith(".SZ")


def _to_safe_name(sym: str) -> str:
    return sym.replace(".", "_")


def _rename_columns(df):
    """统一列名: datetime → trade_date"""
    if "datetime" in df.columns:
        df = df.rename(columns={"datetime": "trade_date"})
    return df


def _fetch_ashare(client, market, code, count, adjust=Adjust.QFQ):
    df = client.get_stock_kline(market, code, Period.DAILY, count=count, adjust=adjust)
    df = _rename_columns(df)
    # 确保 trade_date 是 datetime
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def _fetch_ex(client, ex_market, code, count):
    df = client.goods_kline(ex_market, code, Period.DAILY, count=count, adjust=Adjust.NONE)
    df = _rename_columns(df)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def fetch_and_save(symbols_dict: dict, count: int, label: str) -> dict:
    """Fetch klines for all symbols and save to /tmp/. Returns manifest."""
    manifest = {}
    a_client = None
    ex_client = None

    for sym in symbols_dict:
        info = symbols_dict[sym]
        safe_name = _to_safe_name(sym)
        path = os.path.join(OUTPUT_DIR, f"{safe_name}_daily.csv")
        name = info[2]

        try:
            if _is_ashare(sym):
                if a_client is None:
                    a_client = MacClient.from_best_host().__enter__()
                market, code = info[0], info[1]
                df = _fetch_ashare(a_client, market, code, count)
            else:
                # US/HK stocks via MacExClient
                if ex_client is None:
                    ex_client = MacExClient.from_best_host().__enter__()
                ex_market, code = info[0], info[1]
                df = _fetch_ex(ex_client, ex_market, code, count)

            df.to_csv(path, index=False)
            date_range = f"{df['trade_date'].min()} ~ {df['trade_date'].max()}"
            print(f"  [{label}] {sym} ({name}): {len(df)} rows, {date_range} → {path}")
            manifest[sym] = {"name": name, "path": path, "rows": len(df), "date_range": date_range}
        except Exception as e:
            print(f"  [{label}] {sym} ({name}): FAILED — {e}")
            manifest[sym] = {"name": name, "path": None, "error": str(e)}

    # Clean up
    if a_client:
        a_client.close()
    if ex_client:
        ex_client.close()

    return manifest


def main():
    days = int(sys.argv[1].replace("--days=", "")) if len(sys.argv) > 1 and sys.argv[1].startswith("--days") else 500
    print(f"[fetch_etf] 拉取 {len(ETF_SCORING) + len(IDX_CN_FF)} 只标的日线 (count={days})...")
    print("[fetch_etf] 数据源: easy-tdx MacClient(A股) + MacExClient(美股)\n")

    manifest: dict = {"timestamp": datetime.utcnow().isoformat() + "Z", "days": days, "data_source": "easy-tdx", "etfs": {}, "indexes": {}}

    # ETFs
    manifest["etfs"] = fetch_and_save(ETF_SCORING, days, "ETF")
    # CN-FF indexes
    manifest["indexes"] = fetch_and_save(IDX_CN_FF, days, "IDX")

    # Summary
    n_ok = sum(1 for m in [manifest["etfs"], manifest["indexes"]] for v in m.values() if v.get("path"))
    n_total = len(ETF_SCORING) + len(IDX_CN_FF)
    print(f"\n[fetch_etf] 完成: {n_ok}/{n_total} 只 → /tmp/")

    # Save manifest
    os.makedirs(os.path.dirname(OUTPUT_MANIFEST), exist_ok=True)
    with open(OUTPUT_MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
    print(f"[fetch_etf] manifest → {OUTPUT_MANIFEST}")

    if n_ok < n_total:
        sys.exit(1)


if __name__ == "__main__":
    main()
