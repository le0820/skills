#!/usr/bin/env python3
"""run_scoring.py — Phase 2 scoring: generate L1/L2/L3/composite JSON from raw data + compiled rules.

Output: output/data/scores_*.json, update system_state.json
"""

import os, sys, json, math
from datetime import datetime, timezone

BASE = os.path.dirname(__file__)
REPO = os.path.join(BASE, "..", "..")
OUT_DATA = os.path.join(REPO, "output", "data")
OUT_STATE = os.path.join(REPO, "output", "state", "system_state.json")

DATE = datetime.now(timezone.utc).strftime("%Y%m%d")

# ── RSI(14) calculation ───────────────────────────────────
def calc_rsi_14(csv_path):
    """从easy-tdx导出的CSV计算RSI(14)"""
    try:
        import pandas as pd
        import numpy as np
        df = pd.read_csv(csv_path)
        if 'close' not in df.columns or len(df) < 15:
            return None
        close = df['close'].values
        delta = np.diff(close)
        gains = np.where(delta > 0, delta, 0)
        losses = np.where(delta < 0, -delta, 0)
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(float(rsi), 1)
    except Exception as e:
        return None

RSI_SYMBOLS = {
    "513130.SH": "/tmp/513130_SH_daily.csv",
    "513310.SH": "/tmp/513310_SH_daily.csv",
    "159682.SZ": "/tmp/159682_SZ_daily.csv",
    "QQQ.US":    "/tmp/QQQ_US_daily.csv",
    "159632.SZ": "/tmp/159632_SZ_daily.csv",
    "512760.SH": "/tmp/512760_SH_daily.csv",
}
rsi_values = {}
for sym, path in RSI_SYMBOLS.items():
    r = calc_rsi_14(path)
    if r is not None:
        rsi_values[sym] = r

# ── Load data ──────────────────────────────────────────────
with open(os.path.join(OUT_DATA, f"raw_macro_{DATE}.json")) as f:
    macro = json.load(f)

with open(os.path.expanduser(f"~/.openclaw/workspace/analysis/p1_upgrade_results_{DATE}.json")) as f:
    p1 = json.load(f)

# ── Web search results (injected manually) ─────────────────
VALUE_MAP = {
    "vix": 16.29,           # FRED 2026-05-27 close
    "spx": 7563.62,          # SPX ~ATH
    "ust_30y": 4.98,         # 30Y UST ~4.98%
    "aaii_bull": 35.6,       # May 27 AAII
    "aaii_bear": 41.9,
    "aaii_spread": -6.3,     # 35.6 - 41.9
    "cpi_us_yoy": 3.5,       # PCE headline March 2026 (FOMC)
    "core_pce_yoy": 3.2,     # PCE core March 2026
    "fed_rate": 5.00,        # Current Fed funds rate
    "nfp_actual_apr": 178,   # April NFP actual (thousands)
    "nfp_consensus_apr": 65, # April NFP consensus
    "unemployment": 4.3,     # April unemployment rate
    "brent": 102,            # Brent crude ~$102
    "dxy": 100.5,            # DXY ~100.5 (estimated from USDJPY 159 context)
    "put_call_ratio": 0.7,   # Default
    "credit_spread": "stable",
    "jp_jgb_10y": 2.79,      # From MEMORY
    "usdjpy": 159,           # From MEMORY
}

# ── L1 Scoring ─────────────────────────────────────────────

# US factors
us_employment = 4  # NFP 178K vs 65K (2.74x). Score 4: near-5 but recent trend weak (Mar ~48K)
us_inflation = 3   # Core PCE 3.2%, headline 3.5%, Brent $102. Base 3 + oil>90→qual: not oil-driven inflation per FOMC
us_monetary = 2    # Rates unchanged but FOMC shows ~30% hike risk, cuts pushed to H2 2026
us_financial = 4   # VIX 16.2 (calm), SPX at ATH, 30Y ~4.98% (back below 5%)
us_geopolitical = 4  # US-Iran fragile ceasefire, no major escalation

us_composite = round(
    us_employment*0.20 + us_inflation*0.20 + us_monetary*0.20 +
    us_financial*0.20 + us_geopolitical*0.20, 2
)

# CN factors
cn_manufacturing = 3   # PMI 50.3 (barely expansion), non-mfg 49.4 (contraction)
cn_consumption = 2     # Retail 0.2% (near-zero), non-mfg 49.4
cn_credit = 3          # M2 8.6%, M1 5.0%, TSF 22075亿, LPR unchanged
cn_real_estate = 3     # No new data, neutral default
cn_policy = 3          # LPR unchanged, policy on hold

cn_composite = round(
    cn_manufacturing*0.25 + cn_consumption*0.20 + cn_credit*0.20 +
    cn_real_estate*0.15 + cn_policy*0.20, 2
)

l1_composite = round(us_composite*0.60 + cn_composite*0.40, 2)

# ── Cross-validation ───────────────────────────────────────
# Brent $102 (< 105), no forced re-eval
# Check triple-rise: oil↑ + 10Y↓ + gold? 10Y 4.98% (↓from 5.07%), not applicable

# ── L2 Scoring ─────────────────────────────────────────────

# Momentum (12-1月): from p1 upgrade
momentum_scores = {
    "513130.SH": p1["individual"]["513130.SH"]["momentum"]["momentum_12_1"],
    "513310.SH": p1["individual"]["513310.SH"]["momentum"]["momentum_12_1"],
    "159682.SZ": p1["individual"]["159682.SZ"]["momentum"]["momentum_12_1"],
    "QQQ.US":    p1["individual"]["QQQ.US"]["momentum"]["momentum_12_1"],
    "512760.SH": p1["individual"]["512760.SH"]["momentum"]["momentum_12_1"],
}

def score_momentum(val):
    if val > 50: return 5
    if val > 20: return 4
    if val > 0: return 3
    if val > -20: return 2
    return 1

momentum_avg = round(sum(score_momentum(v) for v in momentum_scores.values()) / 5, 2)

# Value (HML): use CN3_HML for CN-based, US FF5 HML for QQQ
# From cn_ff_results: CN3_HML β
def score_value_hml(us_beta, us_t, cn_beta, cn_t, us_pct=0.0, cn_pct=0.0):
    """Score value factor. Negative HML = growth (low score). Use significant betas."""
    cn_score = 3
    if abs(cn_t) >= 1.96 and cn_beta is not None:
        if cn_beta > 0.8: cn_score = 5
        elif cn_beta > 0.4: cn_score = 4
        elif cn_beta > -0.4: cn_score = 3
        elif cn_beta > -0.8: cn_score = 2
        else: cn_score = 1

    us_score = 3
    if abs(us_t) >= 1.96 and us_beta is not None:
        if us_beta > 0.8: us_score = 5
        elif us_beta > 0.4: us_score = 4
        elif us_beta > -0.4: us_score = 3
        elif us_beta > -0.8: us_score = 2
        else: us_score = 1

    # Apply mixed model
    if us_pct + cn_pct > 0:
        return round(us_score*us_pct + cn_score*cn_pct)
    return cn_score if cn_pct > 0 else us_score

# 513130: CN_FF (80% CN, 20% US)
cnff = json.load(open(os.path.expanduser(f"~/.openclaw/workspace/analysis/cn_ff_results_{DATE}.json")))
v130 = score_value_hml(
    p1["individual"]["513130.SH"]["ff5_loadings"]["beta_hml"],
    p1["individual"]["513130.SH"]["ff5_loadings"]["t_hml"],
    cnff["513130.SH"]["loadings"]["CN3_HML"]["beta"],
    cnff["513130.SH"]["loadings"]["CN3_HML"]["t_stat"],
    us_pct=0.20, cn_pct=0.80
)

v310 = score_value_hml(
    p1["individual"]["513310.SH"]["ff5_loadings"]["beta_hml"],
    p1["individual"]["513310.SH"]["ff5_loadings"]["t_hml"],
    cnff["513310.SH"]["loadings"]["CN3_HML"]["beta"],
    cnff["513310.SH"]["loadings"]["CN3_HML"]["t_stat"],
    us_pct=0.60, cn_pct=0.40
)

v682 = score_value_hml(
    None, 0,
    cnff["159682.SZ"]["loadings"]["CN3_HML"]["beta"],
    cnff["159682.SZ"]["loadings"]["CN3_HML"]["t_stat"],
    cn_pct=1.0
)

# QQQ: US FF5 only
vqqq = score_value_hml(
    p1["individual"]["QQQ.US"]["ff5_loadings"]["beta_hml"],
    p1["individual"]["QQQ.US"]["ff5_loadings"]["t_hml"],
    None, 0, us_pct=1.0
)

# 512760: Pure A-share chip ETF, CN_FF model
v760 = score_value_hml(
    None, 0,
    cnff["512760.SH"]["loadings"]["CN3_HML"]["beta"],
    cnff["512760.SH"]["loadings"]["CN3_HML"]["t_stat"],
    cn_pct=1.0
)

value_avg = round((v130 + v310 + v682 + vqqq + v760) / 5, 2)

# Growth (RMW + CMA/2): default 3 for all since most not significant
# QQQ has significant RMW (-0.349, t=-2.24) but β in [-0.4,0.4] → score 3
growth_avg = 3.0

# Profitability (RMW): all non-significant → default 3
profit_avg = 3.0

# Size (SMB): all non-significant → default 3
size_avg = 3.0

l2_composite = round((momentum_avg + value_avg + growth_avg + profit_avg + size_avg) / 5, 2)

# ── L3 Scoring ─────────────────────────────────────────────

# Sentiment factors
vix_val = VALUE_MAP["vix"]
if vix_val < 12: vix_score = 1
elif vix_val < 17: vix_score = 2
elif vix_val < 22: vix_score = 3
elif vix_val < 28: vix_score = 4
else: vix_score = 5

put_call = VALUE_MAP["put_call_ratio"]
if put_call > 1.0: pc_score = 1
elif put_call >= 0.5: pc_score = 2
else: pc_score = 3

aaii_spread = VALUE_MAP["aaii_spread"]
if aaii_spread < -20: aaii_score = 1
elif aaii_spread < -10: aaii_score = 2
elif aaii_spread < 10: aaii_score = 3
elif aaii_spread < 20: aaii_score = 4
else: aaii_score = 5

# DXY ~100.5 (moderate strong)
dxy_score = 3  # moderate strong, neutral

# Credit spread
cs_score = 3  # stable

sentiment_composite = round((vix_score + pc_score + aaii_score + dxy_score + cs_score) / 5, 2)

# Risk from p1_upgrade l3_risk_scores
l3_risk = p1["l3_risk_scores"]
risk_scores = [l3_risk[t]["avg_risk_score"] for t in ["513130.SH", "513310.SH", "159682.SZ", "QQQ.US", "512760.SH"]]
risk_composite = round(sum(risk_scores) / len(risk_scores), 2)

l3_composite = round(sentiment_composite*0.50 + risk_composite*0.50, 2)

# ── Composite ──────────────────────────────────────────────
composite = round(l1_composite*0.40 + l2_composite*0.30 + l3_composite*0.30, 2)

# ── Position map lookup ────────────────────────────────────
if composite < 1.5: band = "极端防御"; central = 10; pmin, pmax = 0, 10
elif composite < 2.0: band = "防御"; central = 20; pmin, pmax = 10, 20
elif composite < 2.5: band = "偏防御"; central = 35; pmin, pmax = 20, 35
elif composite < 3.0: band = "中性偏保守"; central = 45; pmin, pmax = 35, 50
elif composite < 3.5: band = "中性偏进攻"; central = 55; pmin, pmax = 50, 60
elif composite < 4.0: band = "进攻"; central = 70; pmin, pmax = 60, 70
else: band = "积极进攻"; central = 85; pmin, pmax = 70, 85

# ── Check trigger: 30Y > 5.0% ──────────────────────────────
trigger_1_active = False
if VALUE_MAP["ust_30y"] >= 5.0:
    trigger_1_active = True

# ── Output ─────────────────────────────────────────────────

def write_json(filename, data):
    path = os.path.join(OUT_DATA, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"  ✅ {path}")

print(f"\n{'='*60}")
print(f"  ⭐ 每日评分 {DATE}")
print(f"{'='*60}")

# L1
l1_report = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "L1_US_composite": us_composite,
    "L1_CN_composite": cn_composite,
    "L1_composite": l1_composite,
    "us": {
        "employment": {"score": us_employment, "value": {"nfp_178K_vs_consensus_65K": "2.74x beat"}, "rationale": "NFP April 178K (2.7x consensus 65K), but Mar trend weak (48K) → no full 5"},
        "inflation": {"score": us_inflation, "value": {"core_pce": "3.2%", "headline_pce": "3.5%", "brent": "$102"}, "rationale": "Core PCE 3.2% in 3-4% range, oil>$90 but FOMC notes services-driven inflation → no oil penalty"},
        "monetary": {"score": us_monetary, "value": {"fed_rate": "5.00%", "fomc_hike_prob": "~30% by 2027"}, "rationale": "Rates unchanged but FOMC reveals hike possibility, cuts pushed to H2 2026"},
        "financial": {"score": us_financial, "value": {"vix": "16.29", "spx": "7563.62"}, "rationale": "VIX calm (16.2), SPX at ATH, 30Y~4.98% (below 5%)"},
        "geopolitical": {"score": us_geopolitical, "value": {"iran_ceasefire": "fragile"}, "rationale": "US-Iran ceasefire fragile but holding"}
    },
    "cn": {
        "manufacturing": {"score": cn_manufacturing, "value": {"pmi_mfg": "50.3", "pmi_non_mfg": "49.4"}, "rationale": "PMI barely expansion, non-mfg in contraction"},
        "consumption": {"score": cn_consumption, "value": {"retail_yoy": "0.2%", "pmi_non_mfg": "49.4"}, "rationale": "Retail near-zero, non-mfg in contraction"},
        "credit": {"score": cn_credit, "value": {"m2": "8.6%", "m1": "5.0%", "tsf": "22075亿"}, "rationale": "M2 decent, M1 positive but gap persists, LPR unchanged"},
        "real_estate": {"score": cn_real_estate, "value": {}, "rationale": "No new housing data, neutral default"},
        "policy": {"score": cn_policy, "value": {"lpr_1y": "3.0%", "lpr_5y": "3.5%"}, "rationale": "Policy on hold, no new stimulus"}
    },
    "assessment": f"US {us_composite} | CN {cn_composite} → L1 {l1_composite}. US mixed: employment strong but inflation sticky + monetary hawkish cap score. CN remains weak: retail near-zero drags consumption factor."
}
write_json(f"scores_L1_{DATE}.json", l1_report)

# L2
l2_report = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "L2_composite": l2_composite,
    "momentum": {"score": momentum_avg, "per_etf": {t: score_momentum(momentum_scores[t]) for t in momentum_scores}},
    "value": {"score": value_avg, "per_etf": {"513130": v130, "513310": v310, "159682": v682, "QQQ": vqqq, "512760": v760}},
    "growth": {"score": growth_avg, "note": "All non-significant FF5 RMW/CMA"},
    "profitability": {"score": profit_avg, "note": "All non-significant"},
    "size": {"score": size_avg, "note": "All non-significant"},
    "assessment": f"Momentum {momentum_avg} strong (driven by 513310/159682 strong trends), Value {value_avg} weak (CN-based ETFs show strong growth/HML-negative exposure), rest neutral 3.0"
}
write_json(f"scores_L2_{DATE}.json", l2_report)

# L3
l3_report = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "L3_composite": l3_composite,
    "sentiment": {
        "composite": sentiment_composite,
        "vix": {"score": vix_score, "value": vix_val, "interpretation": "calm"},
        "put_call": {"score": pc_score, "value": put_call, "note": "estimated"},
        "aaii": {"score": aaii_score, "value": aaii_spread, "interpretation": "neutral (bull 35.6/bear 41.9)"},
        "dxy": {"score": dxy_score, "value": VALUE_MAP["dxy"], "note": "moderate strong"},
        "credit_spread": {"score": cs_score, "value": "stable"}
    },
    "rsi_14": rsi_values,
    "risk": {
        "composite": risk_composite,
        "per_etf": l3_risk
    },
    "assessment": f"Sentiment {sentiment_composite} (calm VIX, neutral AAII) | Risk {risk_composite} (elevated by 513310 VaR=1, moderated by 159682/QQQ). RSI(14): {rsi_values}"
}
write_json(f"scores_L3_{DATE}.json", l3_report)

# Composite
comp_report = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "composite": composite,
    "L1": l1_composite,
    "L2": l2_composite,
    "L3": l3_composite,
    "formula": f"{l1_composite}×0.40 + {l2_composite}×0.30 + {l3_composite}×0.30 = {composite}",
    "position_band": band,
    "position_range": f"{pmin}-{pmax}%",
    "position_central": central,
    "previous_composite": None,
    "change": None
}
write_json(f"scores_composite_{DATE}.json", comp_report)

# ── Update system_state.json ───────────────────────────────
if os.path.exists(OUT_STATE):
    with open(OUT_STATE) as f:
        state = json.load(f)
else:
    state = {"sop_versions": {}}

prev = state.get("scores", {}).get("composite")
change = round(composite - prev, 2) if prev else None

state["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
state["scores"] = {
    "composite": composite,
    "L1": l1_composite,
    "L1_us": us_composite,
    "L1_cn": cn_composite,
    "L2": l2_composite,
    "L3": l3_composite,
    "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
}
state["position"]["band_label"] = band
state["position"]["central_pct"] = central
state["position"]["range"] = f"{pmin}-{pmax}%"
state["position"]["deviation"] = f"{state['position']['current_actual_pct']-central:+}pp ({band})"

# Update alert: check if 30Y trigger should be cleared
if trigger_1_active:
    # Keep red alert
    pass
else:
    # Remove or update trigger 1
    new_active = [a for a in state["alerts"]["active_list"] if a["trigger_id"] != 1]
    if len(new_active) < state["alerts"]["active_count"]:
        state["alerts"]["active_count"] = len(new_active)
        state["alerts"]["resolved_list"] = state["alerts"].get("resolved_list", [])
        state["alerts"]["resolved_list"].append({
            "alert_id": "trigger_1_20260529",
            "trigger_id": 1,
            "resolved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reason": f"30Y UST at {VALUE_MAP['ust_30y']}% fell below 5.0% threshold"
        })
    state["alerts"]["active_list"] = new_active

state["narrative_context"] = f"Score {composite} ({band}), previous {prev}. L1-US {us_composite}/L1-CN {cn_composite} | L2 {l2_composite} | L3 {l3_composite}. 30Y~{VALUE_MAP['ust_30y']}% (below 5%, trigger cleared). CN retail 0.2% remains drag. NVDA FY27Q1 beat (5/20). Next key: 6/5 NFP."

with open(OUT_STATE, "w") as f:
    json.dump(state, f, indent=2, ensure_ascii=False, default=str)
print(f"\n  ✅ system_state.json updated (composite: {prev} → {composite}, Δ={change})")

# ── Alert check ────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  ⚠️  Alert Check")
print(f"{'='*60}")
alerts = []

# Trigger 1: 30Y UST > 5.0%
if VALUE_MAP["ust_30y"] >= 5.0:
    alerts.append({"id": 1, "level": "red", "value": VALUE_MAP["ust_30y"], "threshold": ">5.0%", "action": "FOMC confirmed inflation sticky. Monitor PCE/GDP revision 5/28."})
else:
    print(f"  ✅ Trigger 1 (30Y>5%): {VALUE_MAP['ust_30y']}% ≤ 5.0% → ALERT CLEARED")

# Trigger active count
print(f"  Active alerts: {state['alerts']['active_count']}")
if state['alerts']['active_count'] == 0:
    print(f"  ✅ All alerts clear")

print(f"\n{'='*60}")
print(f"  📊 摘要: L1={l1_composite} L2={l2_composite} L3={l3_composite}")
print(f"  ⭐ COMPOSITE: {composite} → {band} ({pmin}-{pmax}%, central {central}%)")
print(f"  📈 Change from prev: {change}")
print(f"{'='*60}\n")
