"""
P1 升级实施：FF5 因子回归 + VaR/CVaR 量化风险
对 4 只 ETF 运行因子暴露分析和尾部风险量化
"""
import pandas as pd
import numpy as np
from scipy import stats
import json, os, warnings
warnings.filterwarnings('ignore')

OUTPUT = os.path.expanduser("~/.openclaw/workspace/analysis/p1_upgrade_results_20260509.json")

# ===== 1. Load FF5 Data =====
ff5_raw = pd.read_csv('/tmp/ff5_data/F-F_Research_Data_5_Factors_2x3.csv', skiprows=3)
ff5_raw.columns = ['date', 'MktRF', 'SMB', 'HML', 'RMW', 'CMA', 'RF']
ff5 = ff5_raw[ff5_raw['date'].astype(str).str.match(r'^\d{6}$')].copy()
ff5['date'] = pd.to_datetime(ff5['date'].astype(str), format='%Y%m')
ff5['MktRF'] = ff5['MktRF'].astype(float) / 100
ff5['SMB'] = ff5['SMB'].astype(float) / 100
ff5['HML'] = ff5['HML'].astype(float) / 100
ff5['RMW'] = ff5['RMW'].astype(float) / 100
ff5['CMA'] = ff5['CMA'].astype(float) / 100
ff5['RF'] = ff5['RF'].astype(float) / 100
ff5 = ff5.sort_values('date').reset_index(drop=True)
print(f"FF5 data: {len(ff5)} months, {ff5['date'].min().date()} to {ff5['date'].max().date()}")

# ===== 2. Load ETF Data and Compute Monthly Returns =====
etfs = {
    '513130.SH': {'name': '恒生科技ETF', 'file': '/tmp/513130_SH_daily.csv'},
    '513310.SH': {'name': '中韩半导体ETF', 'file': '/tmp/513310_SH_daily.csv'},
    '159682.SZ': {'name': '创业板50ETF', 'file': '/tmp/159682_SZ_daily.csv'},
    'QQQ.US': {'name': '纳斯达克100ETF', 'file': '/tmp/QQQ_US_daily.csv'},
}

all_results = {}

for symbol, info in etfs.items():
    print(f"\n{'='*60}")
    print(f"  {info['name']} ({symbol})")
    print(f"{'='*60}")
    
    df = pd.read_csv(info['file'])
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date').reset_index(drop=True)
    
    # Daily log returns
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    
    # ---- VaR/CVaR Analysis ----
    rets = df['ret'].dropna()
    n_days = len(rets)
    
    # Rolling 60-day VaR and CVaR
    window = 60
    var_95 = np.full(n_days, np.nan)
    var_99 = np.full(n_days, np.nan)
    cvar_95 = np.full(n_days, np.nan)
    
    for i in range(window, n_days + 1):
        w = rets.iloc[i-window:i]
        var_95[i-1] = np.percentile(w, 5)
        var_99[i-1] = np.percentile(w, 1)
        cvar_95[i-1] = w[w <= var_95[i-1]].mean()
    
    # Latest values
    latest_var_95 = var_95[-1]
    latest_var_99 = var_99[-1]
    latest_cvar_95 = cvar_95[-1]
    
    # VaR trend (20-day avg vs 40-day avg of VaR series)
    var_series = pd.Series(var_95).dropna()
    var_20d = var_series.tail(20).mean()
    var_40d = var_series.tail(40).head(20).mean()
    var_trend_change = (var_20d - var_40d) / abs(var_40d) * 100 if abs(var_40d) > 0.0001 else 0
    
    # Full-period VaR
    full_var_95 = np.percentile(rets, 5)
    full_var_99 = np.percentile(rets, 1)
    full_cvar_95 = rets[rets <= full_var_95].mean()
    
    # ---- Maximum Drawdown ----
    cum = (1 + rets).cumprod()
    running_max = cum.expanding().max()
    drawdown = (cum - running_max) / running_max
    
    max_dd = drawdown.min()
    max_dd_idx = drawdown.idxmin()
    
    # Recovery time from max drawdown
    if max_dd_idx < len(cum) - 1:
        recovery_mask = cum.iloc[max_dd_idx:] >= running_max.iloc[max_dd_idx]
        if recovery_mask.any():
            recovery_days = recovery_mask.idxmax() - max_dd_idx
        else:
            recovery_days = len(cum) - max_dd_idx  # still in drawdown
    else:
        recovery_days = 0
    
    # 60-day max drawdown
    dd_60 = drawdown.tail(60).min()
    
    # ---- Annualized Volatility ----
    ann_vol = rets.std() * np.sqrt(252)
    
    # ---- Sharpe Ratio ----
    sharpe = (rets.mean() * 252) / ann_vol if ann_vol > 0 else 0
    
    # ---- Monthly Returns for FF5 Regression ----
    df['year_month'] = df['trade_date'].dt.to_period('M')
    monthly = df.groupby('year_month').apply(
        lambda x: (1 + x['ret']).prod() - 1
    ).reset_index()
    monthly.columns = ['year_month', 'ret']
    monthly['year_month'] = monthly['year_month'].dt.to_timestamp()
    
    # Merge with FF5
    merged = monthly.merge(ff5, left_on='year_month', right_on='date', how='inner')
    merged['excess_ret'] = merged['ret'] - merged['RF']
    
    print(f"  Monthly obs for regression: {len(merged)}")
    
    # ---- FF5 Regression ----
    if len(merged) >= 12:
        X = merged[['MktRF', 'SMB', 'HML', 'RMW', 'CMA']]
        X = np.column_stack([np.ones(len(X)), X])  # add intercept
        y = merged['excess_ret'].values
        
        # OLS
        beta_hat = np.linalg.inv(X.T @ X) @ X.T @ y
        y_pred = X @ beta_hat
        residuals = y - y_pred
        n, k = X.shape
        sigma2 = (residuals @ residuals) / (n - k)
        se = np.sqrt(sigma2 * np.diag(np.linalg.inv(X.T @ X)))
        t_stats = beta_hat / se
        r2 = 1 - (residuals @ residuals) / ((y - y.mean()) @ (y - y.mean()))
        
        # Annualized alpha
        alpha_monthly = beta_hat[0]
        alpha_annual = (1 + alpha_monthly) ** 12 - 1
        
        # Factor loadings
        loadings = {
            'alpha_monthly': round(float(alpha_monthly), 6),
            'alpha_annual': round(float(alpha_annual), 6),
            'beta_mkt': round(float(beta_hat[1]), 4),
            'beta_smb': round(float(beta_hat[2]), 4),
            'beta_hml': round(float(beta_hat[3]), 4),
            'beta_rmw': round(float(beta_hat[4]), 4),
            'beta_cma': round(float(beta_hat[5]), 4),
            't_alpha': round(float(t_stats[0]), 2),
            't_mkt': round(float(t_stats[1]), 2),
            't_smb': round(float(t_stats[2]), 2),
            't_hml': round(float(t_stats[3]), 2),
            't_rmw': round(float(t_stats[4]), 2),
            't_cma': round(float(t_stats[5]), 2),
            'r2': round(float(r2), 4),
            'n_months': len(merged),
        }
        
        # Interpret loadings
        interp = []
        if abs(t_stats[1]) >= 1.96:
            interp.append(f"市场β={beta_hat[1]:.2f}({'进攻型' if beta_hat[1] > 1 else '防御型'})")
        if abs(t_stats[2]) >= 1.96:
            interp.append(f"{'小盘' if beta_hat[2] > 0 else '大盘'}偏好(SMB={beta_hat[2]:.2f})")
        if abs(t_stats[3]) >= 1.96:
            interp.append(f"{'价值' if beta_hat[3] > 0 else '成长'}偏好(HML={beta_hat[3]:.2f})")
        if abs(t_stats[4]) >= 1.96:
            interp.append(f"{'高盈利' if beta_hat[4] > 0 else '低盈利'}偏好(RMW={beta_hat[4]:.2f})")
        if abs(t_stats[5]) >= 1.96:
            interp.append(f"{'保守投资' if beta_hat[5] > 0 else '激进投资'}偏好(CMA={beta_hat[5]:.2f})")
        
        loadings['interpretation'] = interp
        
        print(f"  α(月): {alpha_monthly*100:.3f}% | 年化α: {alpha_annual*100:.2f}%")
        print(f"  R²: {r2:.3f}")
        for ip in interp:
            print(f"  → {ip}")
    else:
        loadings = {'error': f'Insufficient data: {len(merged)} months'}
        print(f"  ⚠️ Insufficient data for regression")
    
    # ---- Momentum Factor (Carhart UMD: 12-1 month return) ----
    # Use daily data to approximate: skip most recent month, use prior 11 months
    if len(df) >= 252:
        df_sorted = df.sort_values('trade_date')
        cum_ret = (1 + df_sorted['ret']).cumprod()
        
        # Find index of ~1 month ago and ~12 months ago
        n = len(df_sorted)
        idx_1m_ago = max(0, n - 22)  # ~22 trading days = 1 month
        idx_12m_ago = max(0, n - 252)  # ~252 trading days = 12 months
        
        ret_12m = cum_ret.iloc[-1] / cum_ret.iloc[idx_12m_ago] - 1 if idx_12m_ago > 0 else None
        ret_1m = cum_ret.iloc[-1] / cum_ret.iloc[idx_1m_ago] - 1
        momentum_12_1 = (ret_12m - ret_1m) if ret_12m is not None else None
        
        # 3-month, 6-month momentum for reference
        idx_3m = max(0, n - 66)
        idx_6m = max(0, n - 126)
        ret_3m = cum_ret.iloc[-1] / cum_ret.iloc[idx_3m] - 1
        ret_6m = cum_ret.iloc[-1] / cum_ret.iloc[idx_6m] - 1
        
        momentum = {
            'ret_1m': round(float(ret_1m) * 100, 2),
            'ret_3m': round(float(ret_3m) * 100, 2),
            'ret_6m': round(float(ret_6m) * 100, 2),
            'ret_12m': round(float(ret_12m) * 100, 2) if ret_12m is not None else None,
            'momentum_12_1': round(float(momentum_12_1) * 100, 2) if momentum_12_1 is not None else None,
        }
        print(f"  动量(12-1月): {momentum.get('momentum_12_1', 'N/A')}% | 3月: {momentum['ret_3m']}% | 6月: {momentum['ret_6m']}%")
    else:
        momentum = {'error': 'Insufficient history'}
    
    # ---- Compile Results ----
    all_results[symbol] = {
        'name': info['name'],
        'n_days': n_days,
        'ann_volatility': round(float(ann_vol) * 100, 2),
        'sharpe_ratio': round(float(sharpe), 2),
        'var': {
            'daily_95pct': round(float(latest_var_95) * 100, 2),
            'daily_99pct': round(float(latest_var_99) * 100, 2),
            'cvar_95pct': round(float(latest_cvar_95) * 100, 2),
            'full_period_var_95': round(float(full_var_95) * 100, 2),
            'full_period_var_99': round(float(full_var_99) * 100, 2),
            'full_period_cvar_95': round(float(full_cvar_95) * 100, 2),
            'trend_20d_vs_40d_pct': round(float(var_trend_change), 1),
            'trend_direction': '扩大⚠️' if var_trend_change > 5 else ('缩小✅' if var_trend_change < -5 else '持平'),
        },
        'drawdown': {
            'max_dd_pct': round(float(max_dd) * 100, 2),
            'dd_60d_pct': round(float(dd_60) * 100, 2),
            'recovery_days': int(recovery_days),
            'in_drawdown_now': bool(drawdown.iloc[-1] < -0.01),
        },
        'momentum': momentum,
        'ff5_loadings': loadings,
    }

# ===== 3. Portfolio VaR/CVaR =====
print(f"\n{'='*60}")
print(f"  PORTFOLIO-LEVEL RISK")
print(f"{'='*60}")

# Equal-weighted portfolio daily returns (simple average of returns)
all_rets = {}
for symbol in etfs:
    df = pd.read_csv(etfs[symbol]['file'])
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date')
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    all_rets[symbol] = df[['trade_date', 'ret']].set_index('trade_date')

# Align dates
common_idx = None
for sym, rdf in all_rets.items():
    if common_idx is None:
        common_idx = rdf.index
    else:
        common_idx = common_idx.intersection(rdf.index)

port_rets = pd.DataFrame(index=common_idx)
for sym in all_rets:
    port_rets[sym] = all_rets[sym].loc[common_idx, 'ret']

port_rets['port_ret'] = port_rets.mean(axis=1)
port_ret_vals = port_rets['port_ret'].dropna()

# Portfolio VaR
port_var_95 = np.percentile(port_ret_vals.tail(60), 5)
port_var_99 = np.percentile(port_ret_vals.tail(60), 1)
port_cvar_95 = port_ret_vals.tail(60)[port_ret_vals.tail(60) <= port_var_95].mean()

# Portfolio correlation matrix
corr_matrix = port_rets[list(etfs.keys())].corr()

portfolio_risk = {
    'var_95_1d_pct': round(float(port_var_95) * 100, 2),
    'var_99_1d_pct': round(float(port_var_99) * 100, 2),
    'cvar_95_1d_pct': round(float(port_cvar_95) * 100, 2),
    'correlation_matrix': {s1: {s2: round(float(corr_matrix.loc[s1, s2]), 2) for s2 in etfs} for s1 in etfs},
}

print(f"  组合 VaR(95%,1d): {portfolio_risk['var_95_1d_pct']}%")
print(f"  组合 CVaR(95%,1d): {portfolio_risk['cvar_95_1d_pct']}%")
print(f"  平均相关性: {corr_matrix.values[np.triu_indices(4,1)].mean():.2f}")

# ===== 4. Generate Scoring =====
def score_var(var_pct):
    v = abs(var_pct)
    if v < 1: return 5
    elif v < 2: return 4
    elif v < 3: return 3
    elif v < 4: return 2
    else: return 1

def score_cvar(cvar_pct):
    v = abs(cvar_pct)
    if v < 1.5: return 5
    elif v < 3: return 4
    elif v < 4.5: return 3
    elif v < 6: return 2
    else: return 1

def score_drawdown(dd_pct):
    v = abs(dd_pct)
    if v < 5: return 5
    elif v < 10: return 4
    elif v < 15: return 3
    elif v < 20: return 2
    else: return 1

def score_var_trend(trend_pct):
    if trend_pct < -20: return 5  # rapidly shrinking risk
    elif trend_pct < -5: return 4
    elif trend_pct < 5: return 3
    elif trend_pct < 20: return 2
    else: return 1  # rapidly expanding risk

scoring = {}
for symbol, r in all_results.items():
    v = r['var']
    d = r['drawdown']
    
    scoring[symbol] = {
        'name': r['name'],
        'var_score': score_var(v['daily_95pct']),
        'cvar_score': score_cvar(v['cvar_95pct']),
        'dd_score': score_drawdown(d['dd_60d_pct']),
        'var_trend_score': score_var_trend(v['trend_20d_vs_40d_pct']),
        'avg_risk_score': round((score_var(v['daily_95pct']) + score_cvar(v['cvar_95pct']) + 
                                 score_drawdown(d['dd_60d_pct']) + score_var_trend(v['trend_20d_vs_40d_pct'])) / 4, 1),
    }
    
    print(f"\n  {r['name']}: VaR={v['daily_95pct']}% (→{scoring[symbol]['var_score']}), "
          f"CVaR={v['cvar_95pct']}% (→{scoring[symbol]['cvar_score']}), "
          f"DD={d['dd_60d_pct']}% (→{scoring[symbol]['dd_score']}), "
          f"趋势={v['trend_direction']} (→{scoring[symbol]['var_trend_score']}), "
          f"综合风险评分={scoring[symbol]['avg_risk_score']}")

# Portfolio-level risk scoring
port_risk_score = round((score_var(portfolio_risk['var_95_1d_pct']) + 
                          score_cvar(portfolio_risk['cvar_95_1d_pct'])) / 2, 1)

# ===== 5. Map Factor Loadings to L2 Scores =====
def score_factor(beta, t_stat, factor_name):
    """Map factor loading to 1-5 score based on magnitude and significance"""
    if abs(t_stat) < 1.96:
        return 3, '不显著'
    
    abs_beta = abs(beta)
    if factor_name == 'mkt':
        if beta > 1.2: return 5, '强进攻'
        elif beta > 1.0: return 4, '偏进攻'
        elif beta > 0.8: return 3, '中性'
        elif beta > 0.6: return 2, '偏防御'
        else: return 1, '防御'
    elif factor_name == 'smb':
        if abs_beta > 0.8: return (5 if beta < 0 else 1), ('大盘' if beta < 0 else '小盘')
        elif abs_beta > 0.4: return (4 if beta < 0 else 2), ('偏大盘' if beta < 0 else '偏小盘')
        else: return 3, '中性'
    elif factor_name == 'hml':
        if abs_beta > 0.8: return (1 if beta < 0 else 5), ('成长' if beta < 0 else '价值')
        elif abs_beta > 0.4: return (2 if beta < 0 else 4), ('偏成长' if beta < 0 else '偏价值')
        else: return 3, '中性'
    elif factor_name == 'rmw':
        if abs_beta > 0.8: return (1 if beta < 0 else 5), ('低盈利' if beta < 0 else '高盈利')
        elif abs_beta > 0.4: return (2 if beta < 0 else 4), ('盈利偏弱' if beta < 0 else '盈利偏强')
        else: return 3, '中性'
    elif factor_name == 'cma':
        if abs_beta > 0.8: return (5 if beta < 0 else 1), ('激进' if beta > 0 else '保守')
        elif abs_beta > 0.4: return (4 if beta < 0 else 2), ('偏激进' if beta > 0 else '偏保守')
        else: return 3, '中性'
    return 3, '未知'

l2_scores = {}
for symbol, r in all_results.items():
    if 'error' not in r['ff5_loadings']:
        l = r['ff5_loadings']
        mkt_score, mkt_label = score_factor(l['beta_mkt'], l['t_mkt'], 'mkt')
        smb_score, smb_label = score_factor(l['beta_smb'], l['t_smb'], 'smb')
        hml_score, hml_label = score_factor(l['beta_hml'], l['t_hml'], 'hml')
        rmw_score, rmw_label = score_factor(l['beta_rmw'], l['t_rmw'], 'rmw')
        cma_score, cma_label = score_factor(l['beta_cma'], l['t_cma'], 'cma')
        
        l2_scores[symbol] = {
            'name': r['name'],
            'mkt': {'score': mkt_score, 'label': mkt_label, 'beta': l['beta_mkt']},
            'smb': {'score': smb_score, 'label': smb_label, 'beta': l['beta_smb']},
            'hml': {'score': hml_score, 'label': hml_label, 'beta': l['beta_hml']},
            'rmw': {'score': rmw_score, 'label': rmw_label, 'beta': l['beta_rmw']},
            'cma': {'score': cma_score, 'label': cma_label, 'beta': l['beta_cma']},
            'avg_style_score': round((mkt_score + smb_score + hml_score + rmw_score + cma_score) / 5, 1),
            'r2': l['r2'],
        }
        
        print(f"\n  {r['name']} FF5: β_mkt={l['beta_mkt']}({mkt_label}) "
              f"β_smb={l['beta_smb']}({smb_label}) "
              f"β_hml={l['beta_hml']}({hml_label}) "
              f"β_rmw={l['beta_rmw']}({rmw_label}) "
              f"β_cma={l['beta_cma']}({cma_label}) "
              f"R²={l['r2']:.3f}")

# ===== 6. Save Results =====
output = {
    'timestamp': '2026-05-09',
    'individual': all_results,
    'portfolio': portfolio_risk,
    'l2_scores': l2_scores,
    'l3_risk_scores': scoring,
    'portfolio_risk_score': port_risk_score,
}

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
with open(OUTPUT, 'w') as f:
    json.dump(output, f, ensure_ascii=False, indent=2, default=str)

print(f"\n✅ Results saved to {OUTPUT}")
