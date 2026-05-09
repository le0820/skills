"""
三只ETF综合分析：恒生科技ETF(513130)、中韩半导体ETF(513310)、创业板50ETF(159682)
分析周期：2026-05-06 至 2026-09-30
"""
import sys
import json
from datetime import datetime
from tickflow import TickFlow

# Use free service since we're doing historical analysis
tf = TickFlow.free()

etfs = {
    "513130.SH": {"name": "恒生科技ETF", "underlying": "恒生科技指数"},
    "513310.SH": {"name": "中韩半导体ETF", "underlying": "中韩半导体指数"},
    "159682.SZ": {"name": "创业板50ETF", "underlying": "创业板50指数"},
}

# Corresponding underlying indices
indices = {
    "HSTECH": {"code": "HSTECH.HK", "name": "恒生科技指数"},
    "399637.SZ": {"name": "中韩半导体(人民币)指数"},
    "399673.SZ": {"name": "创业板50指数"},
}

results = {}

for symbol, info in etfs.items():
    print(f"\n{'='*80}")
    print(f"### {info['name']} ({symbol})")
    print(f"{'='*80}")
    
    # 1. Get ETF info
    try:
        instruments = tf.instruments.batch(symbols=[symbol])
        etf_info = instruments[0] if instruments else {}
        print(f"\n--- 标的信息 ---")
        print(json.dumps(etf_info, ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(f"标的信息获取失败: {e}")
        etf_info = {}
    
    # 2. Get long-term daily K-line (since early 2025 for full context)
    try:
        df = tf.klines.get(symbol, period="1d", count=400, as_dataframe=True)
        if df is not None and len(df) > 0:
            print(f"\n--- K线数据 ({len(df)} 条) ---")
            print(f"数据范围: {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}")
            
            # Basic stats
            latest = df.iloc[-1]
            earliest_in_range = df[df['trade_date'] >= '2026-04-01'].iloc[0] if len(df[df['trade_date'] >= '2026-04-01']) > 0 else df.iloc[0]
            
            print(f"\n最新收盘价 ({latest['trade_date']}): {latest['close']}")
            print(f"最新成交量: {latest['volume']}")
            
            # Calculate returns over different periods
            if len(df) >= 5:
                week_close = df.iloc[-6]['close'] if len(df) >= 6 else df.iloc[0]['close']
                week_ret = (latest['close'] - week_close) / week_close * 100
                print(f"近一周涨跌幅: {week_ret:.2f}%")
            
            if len(df) >= 22:
                month_close = df.iloc[-23]['close'] if len(df) >= 23 else df.iloc[0]['close']
                month_ret = (latest['close'] - month_close) / month_close * 100
                print(f"近一月涨跌幅: {month_ret:.2f}%")
            
            if len(df) >= 66:
                qtr_close = df.iloc[-67]['close'] if len(df) >= 67 else df.iloc[0]['close']
                qtr_ret = (latest['close'] - qtr_close) / qtr_close * 100
                print(f"近三月涨跌幅: {qtr_ret:.2f}%")
            
            # YTD return (from 2026-01-01)
            ytd_data = df[df['trade_date'] >= '2026-01-01']
            if len(ytd_data) > 1:
                ytd_start = ytd_data.iloc[0]['close']
                ytd_ret = (latest['close'] - ytd_start) / ytd_start * 100
                print(f"年初至今涨跌幅: {ytd_ret:.2f}%")
            
            # Volatility (20-day annualized)
            if len(df) >= 20:
                df['returns'] = df['close'].pct_change()
                vol_20d = df['returns'].tail(20).std() * (252 ** 0.5) * 100
                print(f"20日年化波动率: {vol_20d:.2f}%")
            
            # 52-week high/low
            if len(df) >= 252:
                high_52w = df['high'].tail(252).max()
                low_52w = df['low'].tail(252).min()
                print(f"52周最高价: {high_52w}")
                print(f"52周最低价: {low_52w}")
                print(f"当前价格距52周高点: {(latest['close'] - high_52w) / high_52w * 100:.2f}%")
                print(f"当前价格距52周低点: {(latest['close'] - low_52w) / low_52w * 100:.2f}%")
            
            # Moving averages
            for ma_period in [5, 10, 20, 60, 120]:
                if len(df) >= ma_period:
                    ma_val = df['close'].tail(ma_period).mean()
                    diff_pct = (latest['close'] - ma_val) / ma_val * 100
                    print(f"MA{ma_period}: {ma_val:.4f} (偏离: {diff_pct:+.2f}%)")
            
            # Volume analysis
            if len(df) >= 5:
                vol_ma5 = df['volume'].tail(5).mean()
                vol_ma20 = df['volume'].tail(20).mean() if len(df) >= 20 else vol_ma5
                vol_ratio = latest['volume'] / vol_ma5
                print(f"量比(相对5日均量): {vol_ratio:.2f}")
            
            results[symbol] = {
                "info": etf_info,
                "latest_date": str(latest['trade_date']),
                "latest_close": float(latest['close']),
                "latest_volume": float(latest['volume']),
                "data_count": len(df),
                "data_range": [str(df['trade_date'].iloc[0]), str(df['trade_date'].iloc[-1])],
            }
            
            # Save first/last 5 rows for reference
            print(f"\n最近5个交易日:")
            print(df[['trade_date', 'open', 'high', 'low', 'close', 'volume']].tail(5).to_string())
        else:
            print("未获取到K线数据")
    except Exception as e:
        print(f"K线数据获取失败: {e}")
        import traceback
        traceback.print_exc()

# Summary table
print(f"\n\n{'='*80}")
print("=== 三只ETF关键数据对比 ===")
print(f"{'='*80}")
for symbol, data in results.items():
    info = etfs[symbol]
    print(f"{info['name']} ({symbol}): 最新价 {data['latest_close']:.4f}, 数据条数 {data['data_count']}, 范围 {data['data_range']}")
