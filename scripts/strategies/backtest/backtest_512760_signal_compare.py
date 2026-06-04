"""
512760 芯片ETF国泰 — 回测5种买入信号（2021-06-04 → 2026-06-04）

核心逻辑: 每次信号触发，将剩余现金按『等权预期触发次数』分批买入。
但更直观点：把每次信号视为一个『独立买点』，买固定金额。
这样比较的是各信号在历史上的平均择时质量。
"""
import pandas as pd
import numpy as np
from easy_tdx import MacClient, Market, Period, Adjust

# ── 拉取数据 ──────────────────────────────────────────────
with MacClient.from_best_host() as c:
    raw = c.get_stock_kline(Market.SH, '512760', Period.DAILY, count=1300, adjust=Adjust.QFQ)
df = raw.copy()
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').reset_index(drop=True)
df = df[(df['datetime'] >= '2021-06-04') & (df['datetime'] <= '2026-06-04')].copy()
df = df.reset_index(drop=True)
close = df['close'].values
n = len(df)

print(f"数据: {len(df)}个交易日, {df['datetime'].iloc[0].date()} → {df['datetime'].iloc[-1].date()}")
print(f"价格区间: ¥{close.min():.3f} ~ ¥{close.max():.3f}")

# ── 技术指标 ──────────────────────────────────────────────
ma20 = pd.Series(close).rolling(20).mean().values

delta = pd.Series(close).diff()
gain = delta.where(delta > 0, 0).rolling(14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
rsi_vals = (100 - (100 / (1 + gain / loss))).values

ema12 = pd.Series(close).ewm(span=12).mean()
ema26 = pd.Series(close).ewm(span=26).mean()
macd_line = (ema12 - ema26).values
signal_line = pd.Series(macd_line).ewm(span=9).mean().values

# ── 信号生成 ──────────────────────────────────────────────
def find_signals():
    signals = {}
    
    # A: 回踩MA20 — 收盘从上方跌破MA20
    sig_a = []
    for i in range(21, n):
        if close[i] <= ma20[i] and close[i-1] > ma20[i-1]:
            sig_a.append(i)
    signals['A:回踩MA20'] = sig_a
    
    # B: RSI回落至40 — RSI从上方跌破40
    sig_b = []
    for i in range(15, n):
        if rsi_vals[i] <= 40 and rsi_vals[i-1] > 40:
            sig_b.append(i)
    signals['B:RSI<40'] = sig_b
    
    # C: 60日创新高 — 收盘站上60日最高
    sig_c = []
    for i in range(61, n):
        if close[i] >= pd.Series(close).iloc[i-60:i].max():
            sig_c.append(i)
    signals['C:60日新高'] = sig_c
    
    # D: MACD金叉 — MACD线上穿信号线
    sig_d = []
    for i in range(27, n):
        if macd_line[i] > signal_line[i] and macd_line[i-1] <= signal_line[i-1]:
            sig_d.append(i)
    signals['D:MACD金叉'] = sig_d
    
    return signals

signals = find_signals()

for name, idx_list in signals.items():
    print(f"  {name}: {len(idx_list)}次触发")
    # 打印前3次和后1次
    preview = idx_list[:3]
    if len(idx_list) > 3:
        preview.append(idx_list[-1])
    for idx in preview:
        d = df['datetime'].iloc[idx].date()
        p = close[idx]
        print(f"     {d} @ ¥{p:.3f}")
    if len(idx_list) > 4:
        print(f"     ...共{len(idx_list)}次")

# ── 回测方法: 每次信号买固定金额，比较平均收益率 ─────────
def backtest_fixed_lot(label, idx_list, lot=5000):
    """每次信号触发买入¥lot，持有到终局。统计所有买入的平均表现。"""
    results_list = []
    for idx in idx_list:
        buy_price = close[idx]
        shares = lot / buy_price
        end_value = shares * close[-1]
        ret = (end_value / lot - 1) * 100
        results_list.append({
            'date': df['datetime'].iloc[idx].date(),
            'buy_price': round(buy_price, 3),
            'end_value': round(end_value, 2),
            'return_pct': round(ret, 2)
        })
    return results_list

print(f"\n{'='*60}")
print(f"  各信号买点质量对比 (每笔买入¥5000,持有到终局¥{close[-1]:.3f})")
print(f"{'='*60}")

benchmark_buy = close[0]
benchmark_shares = 5000 / benchmark_buy
benchmark_end = benchmark_shares * close[-1]
benchmark_ret = (benchmark_end / 5000 - 1) * 100

all_results = {}
for name, idx_list in signals.items():
    all_results[name] = backtest_fixed_lot(name, idx_list)
    
    rets = [r['return_pct'] for r in all_results[name]]
    avg_ret = np.mean(rets) if rets else 0
    med_ret = np.median(rets) if rets else 0
    min_ret = min(rets) if rets else 0
    max_ret = max(rets) if rets else 0
    
    # 胜率: 收益>0的比例
    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else 0
    
    # 最佳单笔表现
    best_idx = np.argmax(rets)
    best = all_results[name][best_idx]
    worst_idx = np.argmin(rets)
    worst = all_results[name][worst_idx]
    
    print(f"\n  {name} ({len(idx_list)}次触发)")
    print(f"   平均收益率: {avg_ret:+.2f}% | 中位数: {med_ret:+.2f}%")
    print(f"   最优: {best['date']} @ ¥{best['buy_price']:.3f} → {best['return_pct']:+.2f}%")
    print(f"   最差: {worst['date']} @ ¥{worst['buy_price']:.3f} → {worst['return_pct']:+.2f}%")
    print(f"   胜率(正收益): {win_rate:.1f}%")
    print(f"   平均买入价: ¥{np.mean([r['buy_price'] for r in all_results[name]]):.3f}")
    print(f"   最高买入价: ¥{max(r['buy_price'] for r in all_results[name]):.3f}")
    print(f"   最低买入价: ¥{min(r['buy_price'] for r in all_results[name]):.3f}")

print(f"\n{'─'*60}")
print(f"  基准: 期初一次性买入 ¥{benchmark_buy:.3f} → {benchmark_ret:+.2f}%")
print(f"{'─'*60}")

# ── 汇总排名: 按平均收益率 ────────────────────────────────
print(f"\n{'='*60}")
print(f"  策略排名 (按平均收益率)")
print(f"{'='*60}")
sorted_by_avg = sorted(all_results.items(), key=lambda x: np.mean([r['return_pct'] for r in x[1]]), reverse=True)
for i, (name, data) in enumerate(sorted_by_avg, 1):
    rets = [r['return_pct'] for r in data]
    avg_ret = np.mean(rets)
    med_ret = np.median(rets)
    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100
    print(f"  #{i} {name}: 均收益 {avg_ret:+.2f}% | 中位数 {med_ret:+.2f}% | 胜率{win_rate:.0f}% ({len(data)}笔)")

print(f"  基准(期初): {benchmark_ret:+.2f}%")

# ── 买入价格分布的统计特征 ────────────────────────────────
print(f"\n{'='*60}")
print(f"  各信号买入价格分布 vs 全区间价格分布")
print(f"{'='*60}")
all_prices = close
print(f"  全区间价格: 均值¥{np.mean(all_prices):.3f} 中位¥{np.median(all_prices):.3f}")
for name, idx_list in signals.items():
    buy_prices = [close[i] for i in idx_list]
    print(f"  {name}:   均值¥{np.mean(buy_prices):.3f} 中位¥{np.median(buy_prices):.3f}  "
          f"vs全区间均值: {(np.mean(all_prices)/np.mean(buy_prices)-1)*100:+.1f}%")
