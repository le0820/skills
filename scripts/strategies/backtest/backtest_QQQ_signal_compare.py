"""QQQ.US 纳斯达克100ETF — 买入信号回测对照组 (2023-08-21→2026-06-04)"""
import pandas as pd
import numpy as np
from easy_tdx import MacExClient, ExMarket, Period

with MacExClient.from_best_host() as c:
    raw = c.goods_kline(ExMarket.US_STOCK, 'QQQ', Period.DAILY, count=1300)

df = raw.copy()
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').reset_index(drop=True)
close = df['close'].values
n = len(df)

print(f"QQQ 数据: {len(df)}个交易日, {df['datetime'].iloc[0].date()} → {df['datetime'].iloc[-1].date()}")
print(f"价格区间: ${min(close):.1f} ~ ${max(close):.1f}")

# 指标
ma20 = pd.Series(close).rolling(20).mean().values
delta = pd.Series(close).diff()
gain = delta.where(delta > 0, 0).rolling(14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
rsi14 = (100 - (100 / (1 + gain / loss))).values

ema12 = pd.Series(close).ewm(span=12).mean()
ema26 = pd.Series(close).ewm(span=26).mean()
macd_line = (ema12 - ema26).values
signal_line = pd.Series(macd_line).ewm(span=9).mean().values

boll_m = pd.Series(close).rolling(20).mean().values
boll_u = boll_m + 2 * pd.Series(close).rolling(20).std().values

# 多周期RSI
def rsi_series(c, p):
    d = pd.Series(c).diff()
    g = d.where(d > 0, 0).rolling(p).mean()
    l = (-d.where(d < 0, 0)).rolling(p).mean()
    return (100 - (100 / (1 + g / l))).values

rsi6 = rsi_series(close, 6)
rsi12 = rsi_series(close, 12)
rsi24 = rsi_series(close, 24)

# 信号
def find_sig(cond, lookback):
    return [i for i in range(lookback, n) if cond(i)]

sig = {}
sig['A:回踩MA20'] = find_sig(lambda i: close[i] <= ma20[i] and close[i-1] > ma20[i-1], 21)
sig['B:RSI14<40'] = find_sig(lambda i: rsi14[i] <= 40 and rsi14[i-1] > 40, 15)
sig['C:60日新高'] = find_sig(lambda i: close[i] >= pd.Series(close).iloc[i-60:i].max(), 61)
sig['D:MACD金叉'] = find_sig(lambda i: macd_line[i] > signal_line[i] and macd_line[i-1] <= signal_line[i-1], 27)
sig['E:突破BOLL上轨'] = find_sig(lambda i: close[i] >= boll_u[i] and close[i-1] < boll_u[i-1], 21)
sig['F:回踩BOLL中轨'] = sig['A:回踩MA20']

for name, idx in sig.items():
    prices = [close[i] for i in idx]
    print(f"  {name}: {len(idx)}次 | 均价${np.mean(prices):.1f}" if prices else f"  {name}: 0次")

# RSI多参数对比
print(f"\n{'='*55}")
print(f"  QQQ RSI参数对比")
print(f"{'='*55}")
print(f"{'周期':>4} {'阈值':>4} {'触发':>5} {'均收益':>9} {'均价':>8} {'偏离%':>7}")
print('-'*40)
FINAL = close[-1]
ALL_AVG = np.mean(close)

for period, arr in [(6,rsi6),(12,rsi12),(14,rsi14),(24,rsi24)]:
    for th in [30, 35, 40]:
        idx = [i for i in range(period+1,n) if arr[i] <= th and arr[i-1] > th]
        if not idx: continue
        rets = [(FINAL/close[i]-1)*100 for i in idx]
        ap = np.mean([close[i] for i in idx])
        dev = (ap/ALL_AVG-1)*100
        print(f"{period:>4d} {th:>4d} {len(idx):>5d} {np.mean(rets):>+8.2f}% ${ap:>6.1f} {dev:>+6.1f}%")

# 全信号回测
print(f"\n{'='*55}")
print(f"  QQQ 六大信号回测 (终局${FINAL:.1f}, 均价${ALL_AVG:.1f})")
print(f"{'='*55}")

results = []
for name, idx in sig.items():
    if not idx: continue
    rets = [(FINAL/close[i]-1)*100 for i in idx]
    prices = [close[i] for i in idx]
    ar, mr = np.mean(rets), np.median(rets)
    wr = sum(1 for r in rets if r > 0)/len(rets)*100
    ap = np.mean(prices)
    dev = (ap/ALL_AVG-1)*100
    bi = np.argmax(rets)
    wi = np.argmin(rets)
    results.append((name, len(idx), ar, mr, wr, ap, dev))
    
    print(f"\n  {name} ({len(idx)}次)")
    print(f"    收益: 均{ar:+.2f}% / 中{mr:+.2f}% / 胜{wr:.0f}%")
    print(f"    价格: ${ap:.1f} vs 市场${ALL_AVG:.1f} ({dev:+.1f}%)")
    print(f"    最优: {df['datetime'].iloc[idx[bi]].date()} ${prices[bi]:.1f} → {rets[bi]:+.2f}%")
    print(f"    最差: {df['datetime'].iloc[idx[wi]].date()} ${prices[wi]:.1f} → {rets[wi]:+.2f}%")

results.sort(key=lambda x: x[2], reverse=True)
print(f"\n{'='*55}")
print(f"  排名 (按平均收益率)")
print(f"{'='*55}")
for i, (n, c, ar, mr, wr, ap, d) in enumerate(results, 1):
    print(f"  #{i} {n}: 均{ar:+.2f}% | 中{mr:+.2f}% | 胜{wr:.0f}% | {c}次 | 偏离{d:+.1f}%")

# RSI(24)<30事件分析
print(f"\n{'='*55}")
print(f"  RSI(24)<30 连续停留分析")
print(f"{'='*55}")
events = []
in_ev = False
for i in range(25, n):
    if rsi24[i] <= 30 and not in_ev:
        in_ev, start = True, i
    elif rsi24[i] > 30 and in_ev:
        in_ev = False
        events.append((start, i-1, i-start))
if in_ev:
    events.append((start, n-1, n-start))
print(f"  事件: {len(events)}次 | 多日: {sum(1 for _,_,d in events if d>1)}/{len(events)} ({sum(1 for _,_,d in events if d>1)/len(events)*100:.0f}%)")
if events:
    ds = [d for _,_,d in events]
    print(f"  最长: {max(ds)}天 | 中位: {np.median(ds):.0f}天")
    print(f"  上次: {df['datetime'].iloc[events[-1][0]].date()}")

# 跨ETF对比
print(f"\n{'='*55}")
print(f"  跨ETF: RSI(14)<40 + RSI(24)<30 对比")
print(f"{'='*55}")
print(f"{'ETF':>8} {'RSI(14)<40偏离':>16} {'RSI(24)<30偏离':>16} {'RSI(14)<40均收益':>16}")
for etf, d14, d24, r14 in [
    ('159682', '-11.1%', '-21.8%', '+130.99%'),
    ('512760', '-5.6%', '-16.9%', '+123.10%'),
    ('QQQ', '',
     f'{(np.mean([close[i] for i in [i for i in range(25,n) if rsi24[i]<=30 and rsi24[i-1]>30]])/ALL_AVG-1)*100:+.1f}%' if any(rsi24[i]<=30 and rsi24[i-1]>30 for i in range(25,n)) else 'N/A',
     ''),
]:
    # QQQ RSI14<40
    q14_idx = [i for i in range(15,n) if rsi14[i]<=40 and rsi14[i-1]>40]
    if q14_idx:
        q14_ret = np.mean([(FINAL/close[i]-1)*100 for i in q14_idx])
        q14_dev = (np.mean([close[i] for i in q14_idx])/ALL_AVG-1)*100
        print(f"  {etf:>8} {q14_dev:>+15.1f}% {d24:>16} {q14_ret:>+15.2f}%")
    else:
        print(f"  {etf:>8} {d14:>16} {d24:>16} {r14:>16}")
