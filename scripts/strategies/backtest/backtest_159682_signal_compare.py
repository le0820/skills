"""
159682 创业板50ETF — 回测6种买入信号（2023-01-03 → 2026-06-04）

信号清单：
A. 回踩MA20买入
B. RSI<40买入
C. 60日新高买入
D. MACD金叉买入
E. 突破BOLL上轨买入 (新增)
F. 回踩BOLL中轨买入 (新增)

方法：每次信号触发，买入¥5,000份额，持有到终局，统计平均收益率。
"""
import pandas as pd
import numpy as np
from easy_tdx import MacClient, Market, Period, Adjust

# ── 拉取数据 ──────────────────────────────────────────────
with MacClient.from_best_host() as c:
    raw = c.get_stock_kline(Market.SZ, '159682', Period.DAILY, count=900, adjust=Adjust.QFQ)

df = raw.copy()
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').reset_index(drop=True)
# 使用全量数据（最早从2023-01-03开始）
df = df[df['datetime'] >= '2023-01-03'].copy()
df = df.reset_index(drop=True)

close = df['close'].values
n = len(df)

print(f"159682 数据: {len(df)}个交易日, {df['datetime'].iloc[0].date()} → {df['datetime'].iloc[-1].date()}")
print(f"价格区间: ¥{min(close):.3f} ~ ¥{max(close):.3f}")
print()

# ── 技术指标 ──────────────────────────────────────────────

# MA20
ma20 = pd.Series(close).rolling(20).mean().values

# RSI(14)
delta = pd.Series(close).diff()
gain = delta.where(delta > 0, 0).rolling(14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
rsi_vals = (100 - (100 / (1 + gain / loss))).values

# MACD
ema12 = pd.Series(close).ewm(span=12).mean()
ema26 = pd.Series(close).ewm(span=26).mean()
macd_line = (ema12 - ema26).values
signal_line = pd.Series(macd_line).ewm(span=9).mean().values

# BOLL (20,2)
def calc_boll(c, window=20, k=2):
    middle = pd.Series(c).rolling(window).mean().values
    std = pd.Series(c).rolling(window).std().values
    upper = middle + k * std
    lower = middle - k * std
    return upper, middle, lower

boll_u, boll_m, boll_l = calc_boll(close)

# ── 信号生成 ──────────────────────────────────────────────
def find_signals():
    out = {}

    # A: 回踩MA20 — 收盘从上方跌破MA20
    sig = []
    for i in range(21, n):
        if close[i] <= ma20[i] and close[i-1] > ma20[i-1]:
            sig.append(i)
    out['A:回踩MA20'] = sig

    # B: RSI<40
    sig = []
    for i in range(15, n):
        if rsi_vals[i] <= 40 and rsi_vals[i-1] > 40:
            sig.append(i)
    out['B:RSI<40'] = sig

    # C: 60日新高
    sig = []
    for i in range(61, n):
        if close[i] >= pd.Series(close).iloc[i-60:i].max():
            sig.append(i)
    out['C:60日新高'] = sig

    # D: MACD金叉
    sig = []
    for i in range(27, n):
        if macd_line[i] > signal_line[i] and macd_line[i-1] <= signal_line[i-1]:
            sig.append(i)
    out['D:MACD金叉'] = sig

    # E: 突破BOLL上轨 — 收盘站上BOLL上轨
    sig = []
    for i in range(21, n):
        if close[i] >= boll_u[i] and close[i-1] < boll_u[i-1]:
            sig.append(i)
    out['E:突破BOLL上轨'] = sig

    # F: 回踩BOLL中轨 — 收盘从上方跌破BOLL中轨
    sig = []
    for i in range(21, n):
        if close[i] <= boll_m[i] and close[i-1] > boll_m[i-1]:
            sig.append(i)
    out['F:回踩BOLL中轨'] = sig

    return out

signals = find_signals()

# ── 打印信号概览 ──────────────────────────────────────────
for name, idx_list in signals.items():
    buy_prices = [close[i] for i in idx_list]
    avg_p = np.mean(buy_prices) if buy_prices else 0
    preview = idx_list[:3] + (idx_list[-1:] if len(idx_list) > 3 else [])
    dates_str = ", ".join([f"{df['datetime'].iloc[i].date()}¥{close[i]:.3f}" for i in preview])
    if len(idx_list) > 4:
        dates_str += " ..."
    print(f"  {name}: {len(idx_list)}次触发 | 均价¥{avg_p:.3f} | 例: {dates_str}")

# ── 回测 ──────────────────────────────────────────────────
def backtest_fixed_lot(label, idx_list, lot=5000):
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

benchmark_price = close[0]
benchmark_shares = 5000 / benchmark_price
benchmark_end = benchmark_shares * close[-1]
benchmark_ret = (benchmark_end / 5000 - 1) * 100

all_results = {}
for name, idx_list in signals.items():
    all_results[name] = backtest_fixed_lot(name, idx_list)

# ── 打印详细回测结果 ──────────────────────────────────────
FINAL_PRICE = close[-1]
print(f"\n{'='*65}")
print(f"  各信号买点质量对比 (每笔¥5,000, 终局¥{FINAL_PRICE:.3f})")
print(f"{'='*65}")

for name, data in all_results.items():
    rets = [r['return_pct'] for r in data]
    buy_prices = [r['buy_price'] for r in data]
    avg_ret = np.mean(rets) if rets else 0
    med_ret = np.median(rets) if rets else 0
    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else 0
    
    best_idx = np.argmax(rets)
    best = data[best_idx]
    worst_idx = np.argmin(rets)
    worst = data[worst_idx]
    
    # 买入价相对于市场均价的偏离
    all_avg = np.mean(close)
    price_dev = (np.mean(buy_prices) / all_avg - 1) * 100 if buy_prices else 0
    
    print(f"\n  {name} ({len(data)}次触发)")
    print(f"    平均收益率: {avg_ret:+.2f}% | 中位数: {med_ret:+.2f}%")
    print(f"    最优: {best['date']} @ ¥{best['buy_price']:.3f} → {best['return_pct']:+.2f}%")
    print(f"    最差: {worst['date']} @ ¥{worst['buy_price']:.3f} → {worst['return_pct']:+.2f}%")
    print(f"    胜率: {win_rate:.0f}% | 均价¥{np.mean(buy_prices):.3f} vs 市场均值¥{all_avg:.3f} ({price_dev:+.1f}%)")

print(f"\n  {'─'*60}")
print(f"    基准: 期初买入 ¥{benchmark_price:.3f} → {benchmark_ret:+.2f}%")
print(f"    终局价: ¥{FINAL_PRICE:.3f}")
print(f"    市场均价(全区间): ¥{np.mean(close):.3f}")

# ── 排名 ──────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"  策略排名 (按平均收益率)")
print(f"{'='*65}")

sorted_res = sorted(all_results.items(),
                     key=lambda x: np.mean([r['return_pct'] for r in x[1]]) if x[1] else 0,
                     reverse=True)

for i, (name, data) in enumerate(sorted_res, 1):
    rets = [r['return_pct'] for r in data]
    avg_ret = np.mean(rets) if rets else 0
    med_ret = np.median(rets) if rets else 0
    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else 0
    avg_price = np.mean([r['buy_price'] for r in data]) if data else 0
    all_avg = np.mean(close)
    dev = (avg_price / all_avg - 1) * 100 if avg_price else 0
    print(f"  #{i} {name}")
    print(f"     收益: 均{avg_ret:+.2f}% / 中{med_ret:+.2f}% / 胜率{win_rate:.0f}%")
    print(f"     价格: 均¥{avg_price:.3f} vs 市场¥{all_avg:.3f} ({dev:+.1f}%)")

print(f"  基准(期初): {benchmark_ret:+.2f}%")

# ── BOLL专用分析 ──────────────────────────────────────────
print(f"\n{'='*65}")
print(f"  BOLL带信号专题分析")
print(f"{'='*65}")

e_data = all_results.get('E:突破BOLL上轨', [])
f_data = all_results.get('F:回踩BOLL中轨', [])

if e_data:
    e_rets = [r['return_pct'] for r in e_data]
    print(f"\n  突破BOLL上轨: {len(e_data)}次")
    print(f"    均收益: {np.mean(e_rets):+.2f}% | 中位数: {np.median(e_rets):+.2f}%")
    print(f"    买入后持有到终局: 胜率{sum(1 for r in e_rets if r>0)/len(e_rets)*100:.0f}%")
    # 统计突破后的短期表现（20天）
    short_rets = []
    for r in e_data:
        buy_idx = None
        for i in range(n):
            if df['datetime'].iloc[i].date() == r['date']:
                buy_idx = i
                break
        if buy_idx is not None and buy_idx + 20 < n:
            sr = (close[buy_idx+20] / close[buy_idx] - 1) * 100
            short_rets.append(sr)
    if short_rets:
        print(f"    突破后20日均涨幅: {np.mean(short_rets):+.2f}% | 胜率{sum(1 for s in short_rets if s>0)/len(short_rets)*100:.0f}%")

if f_data:
    f_rets = [r['return_pct'] for r in f_data]
    print(f"\n  回踩BOLL中轨: {len(f_data)}次")
    print(f"    均收益: {np.mean(f_rets):+.2f}% | 中位数: {np.median(f_rets):+.2f}%")
    print(f"    买入后持有到终局: 胜率{sum(1 for r in f_rets if r>0)/len(f_rets)*100:.0f}%")
    # 对比回踩BOLL中轨 vs 回踩MA20
    a_avg = np.mean([r['buy_price'] for r in all_results.get('A:回踩MA20', [])]) if all_results.get('A:回踩MA20') else 0
    f_avg = np.mean([r['buy_price'] for r in f_data]) if f_data else 0
    if a_avg and f_avg:
        print(f"    买入均价¥{f_avg:.3f} vs 回踩MA20均价¥{a_avg:.3f} ({(f_avg/a_avg-1)*100:+.1f}%)")

# ── 当前信号状态 ──────────────────────────────────────────
print(f"\n{'='*65}")
print(f"  当前(2026-06-04)信号状态")
print(f"{'='*65}")
latest = df.iloc[-1]
print(f"  收盘价: ¥{latest['close']:.3f}")
print(f"  MA20: ¥{ma20[-1]:.3f} (价差: {(close[-1]/ma20[-1]-1)*100:+.2f}%)")
print(f"  RSI(14): {rsi_vals[-1]:.1f}")
print(f"  MACD: {'金叉' if macd_line[-1] > signal_line[-1] else '死叉'}")
print(f"  BOLL上/中/下: ¥{boll_u[-1]:.3f} / ¥{boll_m[-1]:.3f} / ¥{boll_l[-1]:.3f}")
print(f"  BOLL位置: {(close[-1]/boll_m[-1]-1)*100:+.2f}% (中轨上方)")

# 检查各信号是否触发
for name, idx_list in signals.items():
    if idx_list and idx_list[-1] == n - 1:
        print(f"  → {name}: ⚠️ 今天触发！")
    elif idx_list:
        days_ago = n - 1 - idx_list[-1]
        last_date = df['datetime'].iloc[idx_list[-1]].date()
        print(f"  → {name}: 上次触发 {last_date} ({days_ago}天前)")
    else:
        print(f"  → {name}: 从未触发")

print()
print("  实战结论: ", end="")
# 哪个信号的综合性价比最高？
best_signal_name = sorted_res[0][0]
best_avg_ret = np.mean([r['return_pct'] for r in sorted_res[0][1]])
print(f"{best_signal_name} 历史最优 (均收益{best_avg_ret:+.1f}%)")
