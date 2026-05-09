"""
CN-FF 中国本土因子构造 + 回归分析
对 513130/513310/159682 三只中国ETF运行 CN 因子回归
"""
import pandas as pd
import numpy as np
import json, os, warnings
warnings.filterwarnings('ignore')

OUTPUT = os.path.expanduser("~/.openclaw/workspace/analysis/cn_ff_results_20260509.json")

# ===== 1. Load Index Data & Compute Monthly Returns =====
def monthly_returns(csv_path):
    df = pd.read_csv(csv_path)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date')
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    df['year_month'] = df['trade_date'].dt.to_period('M')
    monthly = df.groupby('year_month').apply(lambda x: (1 + x['ret']).prod() - 1).reset_index()
    monthly.columns = ['year_month', 'ret']
    monthly['year_month'] = monthly['year_month'].dt.to_timestamp()
    return monthly, df

# Load ETF returns
etfs = {
    '513130.SH': {'name': '恒生科技ETF', 'file': '/tmp/513130_SH_daily.csv'},
    '513310.SH': {'name': '中韩半导体ETF', 'file': '/tmp/513310_SH_daily.csv'},
    '159682.SZ': {'name': '创业板50ETF', 'file': '/tmp/159682_SZ_daily.csv'},
}

# Load indices
csi_all, _ = monthly_returns('/tmp/000985_SH_daily.csv')
csi1000, _ = monthly_returns('/tmp/000852_SH_daily.csv')
csi100, _ = monthly_returns('/tmp/000903_SH_daily.csv')
value_idx, _ = monthly_returns('/tmp/399371_SZ_daily.csv')
growth_idx, _ = monthly_returns('/tmp/399370_SZ_daily.csv')

# ===== 2. Construct CN Factors =====
# CN1: Market = CSI All-Share - Risk Free (use 1.5%/12 as monthly RF proxy)
rf_monthly = 0.015 / 12

# Merge all index returns
factors = csi_all.rename(columns={'ret': 'csi_all'}).copy()
factors = factors.merge(csi1000.rename(columns={'ret': 'csi1000'}), on='year_month')
factors = factors.merge(csi100.rename(columns={'ret': 'csi100'}), on='year_month')
factors = factors.merge(value_idx.rename(columns={'ret': 'value'}), on='year_month')
factors = factors.merge(growth_idx.rename(columns={'ret': 'growth'}), on='year_month')

# CN1: Market excess return
factors['CN1_Mkt'] = factors['csi_all'] - rf_monthly

# CN2: Size = Small - Large
factors['CN2_SMB'] = factors['csi1000'] - factors['csi100']

# CN3: Value = Value - Growth
factors['CN3_HML'] = factors['value'] - factors['growth']

# ===== CN6: Credit Impulse =====
# PBOC TSF data (万亿 yuan, monthly flow)
tsf_data = {
    '2025-01': 5.93, '2025-02': 1.25, '2025-03': 5.87, '2025-04': 2.84,
    '2025-05': 3.18, '2025-06': 4.56, '2025-07': 2.31, '2025-08': 3.89,
    '2025-09': 4.72, '2025-10': 1.98, '2025-11': 3.45, '2025-12': 5.21,
    '2026-01': 7.22, '2026-02': 2.38, '2026-03': 5.23,
}

tsf = pd.Series(tsf_data)
tsf.index = pd.to_datetime([f'{k}-01' for k in tsf_data.keys()])
tsf = tsf.sort_index()

# Credit impulse = 3-month rolling sum YoY acceleration
tsf_3m = tsf.rolling(3).sum()
credit_impulse = tsf_3m.diff(6) / tsf_3m.shift(6)  # 6-month change in 3m rolling sum
credit_impulse = credit_impulse.dropna()

# Align credit impulse to factor frame
ci_df = credit_impulse.reset_index()
ci_df.columns = ['year_month', 'CN6_Credit']

# Merge CN6
factors['year_month'] = pd.to_datetime(factors['year_month'])
ci_df['year_month'] = pd.to_datetime(ci_df['year_month'])
factors = factors.merge(ci_df, on='year_month', how='left')
factors['CN6_Credit'] = factors['CN6_Credit'].fillna(0)  # fill missing with neutral

# ===== CN7: Policy/Regulatory =====
# Qualitative scoring based on PBOC stance, regulatory environment
# Scale: -2(heavy crackdown) to +2(strong support)
policy_scores = {
    '2024-05': -1, '2024-06': -1, '2024-07': 0, '2024-08': 0, '2024-09': 2,  # 924 stimulus
    '2024-10': 2, '2024-11': 2, '2024-12': 1,
    '2025-01': 1, '2025-02': 1, '2025-03': 1, '2025-04': 0,
    '2025-05': 0, '2025-06': 0, '2025-07': 0, '2025-08': 0,
    '2025-09': 0, '2025-10': 1, '2025-11': 1, '2025-12': 1,
    '2026-01': 1, '2026-02': 1, '2026-03': 1, '2026-04': 1,
}

pol = pd.Series(policy_scores)
pol.index = pd.to_datetime([f'{k}-01' for k in policy_scores.keys()])
pol = pol.sort_index()
pol_df = pol.reset_index()
pol_df.columns = ['year_month', 'CN7_Policy']
pol_df['year_month'] = pd.to_datetime(pol_df['year_month'])
factors = factors.merge(pol_df, on='year_month', how='left')
factors['CN7_Policy'] = factors['CN7_Policy'].fillna(0)

print(f"CN Factors constructed: {len(factors)} months, {factors['year_month'].min().date()} to {factors['year_month'].max().date()}")
print(f"  CN1(Mkt): mean={factors['CN1_Mkt'].mean()*100:.2f}% σ={factors['CN1_Mkt'].std()*100:.2f}%")
print(f"  CN2(SMB): mean={factors['CN2_SMB'].mean()*100:.2f}% σ={factors['CN2_SMB'].std()*100:.2f}%")
print(f"  CN3(HML): mean={factors['CN3_HML'].mean()*100:.2f}% σ={factors['CN3_HML'].std()*100:.2f}%")
print(f"  CN6(Credit Impulse): mean={factors['CN6_Credit'].mean():.3f} latest={factors['CN6_Credit'].iloc[-1]:.3f}")
print(f"  CN7(Policy): latest={factors['CN7_Policy'].iloc[-1]}")

# ===== 3. Run CN-FF Regressions for Each Chinese ETF =====
results = {}

for symbol, info in etfs.items():
    print(f"\n{'='*60}")
    print(f"  {info['name']} ({symbol})")
    print(f"{'='*60}")
    
    # Load ETF monthly returns
    etf_monthly, etf_daily = monthly_returns(info['file'])
    
    # Merge with factors
    merged = etf_monthly.merge(factors, on='year_month', how='inner')
    merged['excess_ret'] = merged['ret'] - rf_monthly
    
    n = len(merged)
    print(f"  Monthly obs: {n}")
    
    if n < 6:
        results[symbol] = {'error': f'Insufficient data: {n} months'}
        continue
    
    # ---- Model 1: Basic CN factors (CN1+CN2+CN3) ----
    X1 = merged[['CN1_Mkt', 'CN2_SMB', 'CN3_HML']].values
    X1 = np.column_stack([np.ones(n), X1])
    y = merged['excess_ret'].values
    
    beta1 = np.linalg.inv(X1.T @ X1) @ X1.T @ y
    y_pred1 = X1 @ beta1
    resid1 = y - y_pred1
    r2_1 = 1 - (resid1 @ resid1) / ((y - y.mean()) @ (y - y.mean()))
    
    # ---- Model 2: All CN factors (CN1+CN2+CN3+CN6+CN7) ----
    X2 = merged[['CN1_Mkt', 'CN2_SMB', 'CN3_HML', 'CN6_Credit', 'CN7_Policy']].values
    X2 = np.column_stack([np.ones(n), X2])
    
    beta2 = np.linalg.inv(X2.T @ X2) @ X2.T @ y
    y_pred2 = X2 @ beta2
    resid2 = y - y_pred2
    n2, k2 = X2.shape
    sigma2_2 = (resid2 @ resid2) / (n2 - k2)
    se2 = np.sqrt(sigma2_2 * np.diag(np.linalg.inv(X2.T @ X2)))
    t2 = beta2 / se2
    r2_2 = 1 - (resid2 @ resid2) / ((y - y.mean()) @ (y - y.mean()))
    
    alpha_m = beta2[0]
    alpha_a = (1 + alpha_m) ** 12 - 1
    
    print(f"  Model 1 (CN1+CN2+CN3): R²={r2_1:.4f}")
    print(f"  Model 2 (All CN): R²={r2_2:.4f} (ΔR²={r2_2-r2_1:+.4f})")
    print(f"  α(月)={alpha_m*100:.3f}% | 年化α={alpha_a*100:.2f}%")
    
    # Factor loadings
    names = ['α', 'CN1_Mkt', 'CN2_SMB', 'CN3_HML', 'CN6_Credit', 'CN7_Policy']
    loadings = {}
    for i, n in enumerate(names):
        loadings[n] = {
            'beta': round(float(beta2[i]), 4),
            't_stat': round(float(t2[i]), 2),
            'significant': abs(t2[i]) >= 1.96,
        }
        sig = '✅' if abs(t2[i]) >= 1.96 else ''
        print(f"  {n}: β={beta2[i]:.4f} (t={t2[i]:.2f}) {sig}")
    
    # Compare to US FF5 R²
    # Load previous US FF5 results
    prev = {}
    try:
        with open(os.path.expanduser("~/.openclaw/workspace/analysis/p1_upgrade_results_20260509.json")) as f:
            prev = json.load(f)
    except:
        pass
    
    us_r2 = prev.get(symbol, {}).get('ff5_loadings', {}).get('r2', None)
    
    results[symbol] = {
        'name': info['name'],
        'n_months': n,
        'r2_us_ff5': us_r2,
        'r2_cn_basic': round(float(r2_1), 4),
        'r2_cn_full': round(float(r2_2), 4),
        'r2_improvement': round(float(r2_2 - r2_1), 4),
        'alpha_monthly': round(float(alpha_m), 6),
        'alpha_annual': round(float(alpha_a), 4),
        'loadings': loadings,
    }
    
    if us_r2:
        improvement = (r2_2 - us_r2) / us_r2 * 100 if us_r2 > 0.001 else float('inf')
        print(f"  vs US FF5 R²={us_r2:.4f}: {'+' if improvement > 0 else ''}{improvement:.0f}% improvement")

# ===== 4. Summary =====
print(f"\n{'='*60}")
print(f"  CN-FF vs US-FF5 R² Comparison")
print(f"{'='*60}")
print(f"  {'ETF':<15} {'US FF5':<10} {'CN Basic':<10} {'CN Full':<10} {'Improvement'}")
print(f"  {'-'*55}")
for sym, r in results.items():
    if 'error' in r:
        print(f"  {r['name']:<15} {r['error']}")
        continue
    us = r.get('r2_us_ff5', 0) or 0
    cn_b = r['r2_cn_basic']
    cn_f = r['r2_cn_full']
    impr = ((cn_f - us) / us * 100) if us > 0.01 else float('inf')
    print(f"  {r['name']:<15} {us:.4f}      {cn_b:.4f}      {cn_f:.4f}      {'+' if impr > 0 else ''}{impr:.0f}%")

# Save
os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
with open(OUTPUT, 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\n✅ Saved to {OUTPUT}")
