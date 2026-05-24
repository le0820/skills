#!/usr/bin/env python3
"""fetch_etf_data.py — 拉取 ETF 日线数据到 /tmp/

通过 TickFlow SDK (free tier) 获取所有评分所需 ETF 的历史日K线。
为 p1_upgrade.py / cn_ff_regression.py 准备输入 CSV。

Required env: TICKFLOW_API_KEY (for full tier) or use free tier (日K only).
Must run from skills/tickflow/python/ or configure paths.

Usage:
    cd repo_skills/skills/tickflow/python
    uv run python ../../scripts/pipeline/fetch_etf_data.py [--days 500]
"""

import os, sys, json
from datetime import datetime, timedelta
from typing import Optional

# Allow running from either skills/tickflow/python/ or scripts/pipeline/
_CUR = os.path.dirname(os.path.abspath(__file__))
_TF_DIR = os.path.join(_CUR, "..", "..", "..", "skills", "tickflow", "python")
if os.path.isdir(_TF_DIR):
    sys.path.insert(0, _TF_DIR)

from tickflow import TickFlow

# ── Configurable ticker lists ──────────────────────────────
# ETFs for scoring (L2/L3)
ETF_SCORING = {
    "513130.SH": "恒生科技ETF",
    "513310.SH": "中韩半导体ETF",
    "159682.SZ": "创业板50ETF",
    "QQQ.US":    "纳斯达克100ETF",
    "159632.SZ": "纳斯达克ETF(华安)",
}

# Indexes for CN-FF regression
IDX_CN_FF = {
    "000985.SH": "中证全指",     # CN1_Mkt proxy
    "000852.SH": "中证1000",     # CN2_SMB small-cap
    "000903.SH": "中证100",      # CN2_SMB large-cap
    "399371.SZ": "国证价值",     # CN3_HML value leg
    "399370.SZ": "国证成长",     # CN3_HML growth leg
}

OUTPUT_DIR = "/tmp"
OUTPUT_MANIFEST = os.path.join(_CUR, "..", "..", "output", "data", "etf_manifest.json")


def fetch_and_save(tf, symbols_dict: dict, count: int, label: str) -> dict:
    """Fetch klines for all symbols and save to /tmp/. Returns manifest."""
    manifest = {}
    for sym, name in symbols_dict.items():
        safe_name = sym.replace(".", "_")
        path = os.path.join(OUTPUT_DIR, f"{safe_name}_daily.csv")
        try:
            df = tf.klines.get(sym, period="1d", count=count, as_dataframe=True)
            df.to_csv(path, index=False)
            date_range = f"{df['trade_date'].min()} ~ {df['trade_date'].max()}" if 'trade_date' in df.columns else "N/A"
            print(f"  [{label}] {sym} ({name}): {len(df)} rows, {date_range} → {path}")
            manifest[sym] = {"name": name, "path": path, "rows": len(df), "date_range": date_range}
        except Exception as e:
            print(f"  [{label}] {sym} ({name}): FAILED — {e}")
            manifest[sym] = {"name": name, "path": None, "error": str(e)}
    return manifest


def main():
    days = int(sys.argv[1].replace("--days=", "")) if len(sys.argv) > 1 and sys.argv[1].startswith("--days") else 500
    print(f"[fetch_etf] 拉取 {len(ETF_SCORING) + len(IDX_CN_FF)} 只标的日线 (count={days})...")

    tf = TickFlow.free()  # free tier works for daily klines
    manifest: dict = {"timestamp": datetime.utcnow().isoformat() + "Z", "days": days, "etfs": {}, "indexes": {}}

    # ETFs
    manifest["etfs"] = fetch_and_save(tf, ETF_SCORING, days, "ETF")
    # CN-FF indexes
    manifest["indexes"] = fetch_and_save(tf, IDX_CN_FF, days, "IDX")

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
