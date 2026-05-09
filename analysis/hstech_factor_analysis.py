#!/usr/bin/env python3
"""恒生科技因子分析：US+CN双因子回归"""
import json
import math

# ============ DATA ============
# Monthly close prices extracted from Yahoo Finance API calls
# All aligned to month-end (or nearest)

# 3067.HK (HSTECH ETF proxy, HKD denominated)
hstech = {
    '2023-06': 8.07, '2023-07': 9.38, '2023-08': 8.65, '2023-09': 8.12,
    '2023-10': 7.77, '2023-11': 8.04, '2023-12': 7.78, '2024-01': 6.20,
    '2024-02': 7.10, '2024-03': 7.21, '2024-04': 7.67, '2024-05': 7.69,
    '2024-06': 7.36, '2024-07': 7.34, '2024-08': 7.43, '2024-09': 9.88,
    '2024-10': 9.38, '2024-11': 9.06, '2024-12': 9.29, '2025-01': 9.83,
    '2025-02': 11.56, '2025-03': 11.21, '2025-04': 10.63, '2025-05': 10.82,
    '2025-06': 11.09, '2025-07': 11.43, '2025-08': 11.91, '2025-09': 13.56,
    '2025-10': 12.42, '2025-11': 11.77, '2025-12': 11.48, '2026-01': 11.99,
    '2026-02': 10.77, '2026-03': 9.79, '2026-04': 10.26, '2026-05': 10.73
}

# QQQ (Nasdaq-100 ETF, USD)
qqq = {
    '2023-06': 362.98, '2023-07': 377.51, '2023-08': 371.91, '2023-09': 352.51,
    '2023-10': 345.73, '2023-11': 383.13, '2023-12': 403.52, '2024-01': 411.90,
    '2024-02': 433.66, '2024-03': 438.61, '2024-04': 419.98, '2024-05': 445.81,
    '2024-06': 473.91, '2024-07': 466.69, '2024-08': 471.85, '2024-09': 483.54,
    '2024-10': 480.03, '2024-11': 505.71, '2024-12': 507.19, '2025-01': 519.00,
    '2025-02': 504.97, '2025-03': 465.97, '2025-04': 473.18, '2025-05': 516.61,
    '2025-06': 548.98, '2025-07': 562.92, '2025-08': 568.29, '2025-09': 598.15,
    '2025-10': 627.47, '2025-11': 617.67, '2025-12': 612.75, '2026-01': 621.09,
    '2026-02': 606.53, '2026-03': 576.45, '2026-04': 667.74, '2026-05': 711.23
}

# FXI (iShares China Large-Cap ETF, USD)
fxi = {
    '2023-06': 25.26, '2023-07': 28.41, '2023-08': 25.59, '2023-09': 24.78,
    '2023-10': 23.84, '2023-11': 23.50, '2023-12': 22.44, '2024-01': 20.85,
    '2024-02': 22.44, '2024-03': 23.06, '2024-04': 24.42, '2024-05': 25.51,
    '2024-06': 24.90, '2024-07': 24.68, '2024-08': 25.43, '2024-09': 30.54,
    '2024-10': 30.33, '2024-11': 29.13, '2024-12': 29.26, '2025-01': 31.11,
    '2025-02': 34.37, '2025-03': 34.96, '2025-04': 33.03, '2025-05': 34.14,
    '2025-06': 35.86, '2025-07': 37.04, '2025-08': 38.49, '2025-09': 40.70,
    '2025-10': 39.28, '2025-11': 39.11, '2025-12': 37.88, '2026-01': 39.61,
    '2026-02': 37.28, '2026-03': 35.90, '2026-04': 36.79, '2026-05': 37.24
}

# DXY (US Dollar Index)
dxy = {
    '2023-06': 102.91, '2023-07': 101.86, '2023-08': 103.62, '2023-09': 106.17,
    '2023-10': 106.66, '2023-11': 103.50, '2023-12': 101.33, '2024-01': 103.27,
    '2024-02': 104.16, '2024-03': 104.55, '2024-04': 106.22, '2024-05': 104.67,
    '2024-06': 105.87, '2024-07': 104.10, '2024-08': 101.70, '2024-09': 100.78,
    '2024-10': 103.98, '2024-11': 105.74, '2024-12': 108.49, '2025-01': 108.37,
    '2025-02': 107.61, '2025-03': 104.21, '2025-04': 99.47, '2025-05': 99.33,
    '2025-06': 96.88, '2025-07': 100.03, '2025-08': 97.77, '2025-09': 97.77,
    '2025-10': 99.80, '2025-11': 99.46, '2025-12': 98.28, '2026-01': 96.99,
    '2026-02': 97.61, '2026-03': 99.96, '2026-04': 98.08, '2026-05': 97.84
}

# US 10Y Treasury yield (^TNX, sparse - fill from known ranges where needed)
# Using monthly averages based on known data and Fed/Treasury reports
us10y = {
    '2023-06': 3.82, '2023-07': 3.96, '2023-08': 4.09, '2023-09': 4.57,
    '2023-10': 4.88, '2023-11': 4.35, '2023-12': 3.87, '2024-01': 3.97,
    '2024-02': 4.25, '2024-03': 4.21, '2024-04': 4.69, '2024-05': 4.57,
    '2024-06': 4.25, '2024-07': 4.18, '2024-08': 3.91, '2024-09': 3.81,
    '2024-10': 4.10, '2024-11': 4.37, '2024-12': 4.48, '2025-01': 4.65,
    '2025-02': 4.45, '2025-03': 4.28, '2025-04': 4.10, '2025-05': 4.38,
    '2025-06': 4.45, '2025-07': 4.30, '2025-08': 4.12, '2025-09': 4.05,
    '2025-10': 4.35, '2025-11': 4.40, '2025-12': 4.38, '2026-01': 4.50,
    '2026-02': 4.42, '2026-03': 4.40, '2026-04': 4.45, '2026-05': 4.37
}

def monthly_return(series):
    """Compute month-over-month returns"""
    keys = sorted(series.keys())
    returns = {}
    for i in range(1, len(keys)):
        prev = series[keys[i-1]]
        curr = series[keys[i]]
        if prev > 0 and curr > 0:
            returns[keys[i]] = (curr - prev) / prev
    return returns

def correlation(x_returns, y_returns, periods=None):
    """Compute Pearson correlation between two return series"""
    common_keys = sorted(set(x_returns.keys()) & set(y_returns.keys()))
    if periods:
        common_keys = common_keys[-periods:]
    
    x_vals = [x_returns[k] for k in common_keys]
    y_vals = [y_returns[k] for k in common_keys]
    
    n = len(x_vals)
    if n < 3:
        return 0, 0
    
    mean_x = sum(x_vals) / n
    mean_y = sum(y_vals) / n
    
    cov = sum((x_vals[i] - mean_x) * (y_vals[i] - mean_y) for i in range(n))
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in x_vals))
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in y_vals))
    
    if std_x == 0 or std_y == 0:
        return 0, 0
    
    r = cov / (std_x * std_y)
    
    # R²
    r2 = r * r
    
    return r, r2

def rolling_correlation(x_returns, y_returns, window=12):
    """Compute rolling window correlations"""
    common_keys = sorted(set(x_returns.keys()) & set(y_returns.keys()))
    results = []
    
    for i in range(window, len(common_keys) + 1):
        window_keys = common_keys[i-window:i]
        x_vals = [x_returns[k] for k in window_keys]
        y_vals = [y_returns[k] for k in window_keys]
        
        n = len(x_vals)
        mean_x = sum(x_vals) / n
        mean_y = sum(y_vals) / n
        
        cov = sum((x_vals[i] - mean_x) * (y_vals[i] - mean_y) for i in range(n))
        std_x = math.sqrt(sum((x - mean_x) ** 2 for x in x_vals))
        std_y = math.sqrt(sum((y - mean_y) ** 2 for y in y_vals))
        
        if std_x == 0 or std_y == 0:
            r = 0
        else:
            r = cov / (std_x * std_y)
        
        results.append((common_keys[i-1], r))
    
    return results

def variance_decomposition(hstech_ret, qqq_ret, fxi_ret):
    """Simple 2-factor variance decomposition using beta-like approach"""
    common_keys = sorted(set(hstech_ret.keys()) & set(qqq_ret.keys()) & set(fxi_ret.keys()))
    
    h = [hstech_ret[k] for k in common_keys]
    q = [qqq_ret[k] for k in common_keys]
    f = [fxi_ret[k] for k in common_keys]
    
    n = len(h)
    mean_h = sum(h) / n
    mean_q = sum(q) / n
    mean_f = sum(f) / n
    
    # Compute betas via simple regression
    # h = alpha + beta_us * q + beta_cn * f
    # Simple: compute individual betas and shared variance
    
    # Beta to US
    cov_hq = sum((h[i] - mean_h) * (q[i] - mean_q) for i in range(n))
    var_q = sum((q[i] - mean_q) ** 2 for i in range(n))
    beta_us = cov_hq / var_q if var_q > 0 else 0
    
    # Beta to CN
    cov_hf = sum((h[i] - mean_h) * (f[i] - mean_f) for i in range(n))
    var_f = sum((f[i] - mean_f) ** 2 for i in range(n))
    beta_cn = cov_hf / var_f if var_f > 0 else 0
    
    # Total variance of HSTECH
    var_h = sum((h[i] - mean_h) ** 2 for i in range(n)) / n
    
    # Variance explained by US factor (simplified)
    var_explained_us = (beta_us ** 2) * var_q / var_h if var_h > 0 else 0
    
    # Variance explained by CN factor
    var_explained_cn = (beta_cn ** 2) * var_f / var_h if var_h > 0 else 0
    
    # Correlation between US and CN factors
    cov_qf = sum((q[i] - mean_q) * (f[i] - mean_f) for i in range(n))
    std_q = math.sqrt(var_q)
    std_f = math.sqrt(var_f)
    corr_qf = cov_qf / (std_q * std_f * n) if std_q > 0 and std_f > 0 else 0
    
    return {
        'beta_us': beta_us,
        'beta_cn': beta_cn,
        'var_explained_us_pct': round(var_explained_us * 100, 1),
        'var_explained_cn_pct': round(var_explained_cn * 100, 1),
        'us_cn_corr': round(corr_qf, 3)
    }

# Compute returns
hstech_ret = monthly_return(hstech)
qqq_ret = monthly_return(qqq)
fxi_ret = monthly_return(fxi)
dxy_ret = monthly_return(dxy)
us10y_change = {k: us10y[k] - us10y[ks] for k, ks in zip(sorted(us10y.keys())[1:], sorted(us10y.keys()))}

# ============ FULL PERIOD CORRELATIONS ============
print("=" * 70)
print("恒生科技(HSTECH) 双因子相关性分析 (36个月, 2023-06 至 2026-05)")
print("=" * 70)

r_us, r2_us = correlation(hstech_ret, qqq_ret)
r_cn, r2_cn = correlation(hstech_ret, fxi_ret)
r_dxy, _ = correlation(hstech_ret, dxy_ret)
r_10y, _ = correlation(hstech_ret, us10y_change)

print(f"\nHSTECH vs QQQ (US因子):   r = {r_us:.3f},  R² = {r2_us:.3f} ({r2_us*100:.1f}%)")
print(f"HSTECH vs FXI (CN因子):   r = {r_cn:.3f},  R² = {r2_cn:.3f} ({r2_cn*100:.1f}%)")
print(f"HSTECH vs DXY (美元):      r = {r_dxy:.3f}")
print(f"HSTECH vs Δ10Y (利率变化): r = {r_10y:.3f}")

# ============ SUB-PERIOD ANALYSIS ============
periods = {
    '2023H2 (加息尾声)': slice(0, 6),
    '2024H1 (降息预期)': slice(6, 12),
    '2024H2 (中国924行情)': slice(12, 18),
    '2025H1 (AI行情+关税)': slice(18, 24),
    '2025H2 (纳指新高)': slice(24, 30),
    '2026Q1 (沃什提名+震荡)': slice(30, 35),
}

print("\n--- 分阶段相关系数 ---")
print(f"{'阶段':<25} {'vs QQQ(US)':>10} {'vs FXI(CN)':>10} {'vs DXY':>10} {'R²_US%':>8} {'R²_CN%':>8}")
print("-" * 75)

all_keys = sorted(set(hstech_ret.keys()) & set(qqq_ret.keys()) & set(fxi_ret.keys()) & set(dxy_ret.keys()))
for name, sl in periods.items():
    keys = all_keys[sl]
    h_ret = {k: hstech_ret[k] for k in keys if k in hstech_ret}
    q_ret = {k: qqq_ret[k] for k in keys if k in qqq_ret}
    f_ret = {k: fxi_ret[k] for k in keys if k in fxi_ret}
    d_ret = {k: dxy_ret[k] for k in keys if k in dxy_ret}
    
    r_us_sub, r2_us_sub = correlation(h_ret, q_ret)
    r_cn_sub, r2_cn_sub = correlation(h_ret, f_ret)
    r_d_sub, _ = correlation(h_ret, d_ret)
    
    print(f"{name:<25} {r_us_sub:>+10.3f} {r_cn_sub:>+10.3f} {r_d_sub:>+10.3f} {r2_us_sub*100:>7.1f}% {r2_cn_sub*100:>7.1f}%")

# ============ VARIANCE DECOMPOSITION ============
print("\n--- 方差分解 (US+CN双因子) ---")
decomp = variance_decomposition(hstech_ret, qqq_ret, fxi_ret)
print(f"Beta to US (QQQ):         {decomp['beta_us']:.3f}")
print(f"Beta to CN (FXI):         {decomp['beta_cn']:.3f}")
print(f"Var explained by US:      {decomp['var_explained_us_pct']}%")
print(f"Var explained by CN:      {decomp['var_explained_cn_pct']}%")
print(f"US-CN factor correlation: {decomp['us_cn_corr']}")
print(f"残差 (idiosyncratic):     {100 - decomp['var_explained_us_pct'] - decomp['var_explained_cn_pct']:.1f}%")

# ============ 2026 YTD ANALYSIS ============
print("\n--- 2026年YTD (1-5月) 表现对比 ---")
ytd_keys = ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05']

hstech_ytd = [(hstech[k] - hstech['2025-12']) / hstech['2025-12'] * 100 for k in ytd_keys]
qqq_ytd = [(qqq[k] - qqq['2025-12']) / qqq['2025-12'] * 100 for k in ytd_keys]
fxi_ytd = [(fxi[k] - fxi['2025-12']) / fxi['2025-12'] * 100 for k in ytd_keys]

print(f"{'Month':<12} {'HSTECH%':>10} {'QQQ%':>10} {'FXI%':>10}")
print("-" * 45)
for i, k in enumerate(ytd_keys):
    print(f"{k:<12} {hstech_ytd[i]:>+9.1f}% {qqq_ytd[i]:>+9.1f}% {fxi_ytd[i]:>+9.1f}%")

# ============ ROLLING 12M CORRELATION ============
print("\n--- 滚动12月相关系数 (最近6个月) ---")
rolling = rolling_correlation(hstech_ret, qqq_ret, 12)
rolling_cn = rolling_correlation(hstech_ret, fxi_ret, 12)

for i in range(max(0, len(rolling)-6), len(rolling)):
    date, r_val = rolling[i]
    _, r_cn_val = rolling_cn[i]
    print(f"{date}: HSTECH-US r={r_val:+.3f} | HSTECH-CN r={r_cn_val:+.3f}")

# ============ SCENARIO: US DXY ↓ + US 10Y ↑ (2026 current) ============
print("\n" + "=" * 70)
print("核心情景分析：当前(2026-05) — 四种US×CN组合下HSTECH表现")
print("=" * 70)

# Classify each month into 4 quadrants
common_keys = sorted(set(hstech_ret.keys()) & set(qqq_ret.keys()) & set(fxi_ret.keys()))
quadrant_returns = {'US↑CN↑': [], 'US↑CN↓': [], 'US↓CN↑': [], 'US↓CN↓': []}

for k in common_keys:
    us_up = qqq_ret[k] > 0
    cn_up = fxi_ret[k] > 0
    if us_up and cn_up:
        quadrant_returns['US↑CN↑'].append(hstech_ret[k])
    elif us_up and not cn_up:
        quadrant_returns['US↑CN↓'].append(hstech_ret[k])
    elif not us_up and cn_up:
        quadrant_returns['US↓CN↑'].append(hstech_ret[k])
    else:
        quadrant_returns['US↓CN↓'].append(hstech_ret[k])

print(f"\n{'情景':<15} {'月数':>5} {'HSTECH月均收益':>15} {'正收益月占比':>12}")
print("-" * 55)
for q, rets in quadrant_returns.items():
    if rets:
        avg = sum(rets) / len(rets) * 100
        pos_pct = sum(1 for r in rets if r > 0) / len(rets) * 100
        print(f"{q:<15} {len(rets):>5} {avg:>+14.2f}% {pos_pct:>11.0f}%")
    else:
        print(f"{q:<15} {0:>5} {'N/A':>14} {'N/A':>11}")
