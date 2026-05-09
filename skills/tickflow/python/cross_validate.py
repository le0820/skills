"""
交叉验证：获取对标指数K线和Qveris校验数据
"""
from tickflow import TickFlow

tf = TickFlow.free()

# Get underlying index data
index_symbols = {
    "HSTECH.HK": "恒生科技指数",
    "399637.SZ": "中韩半导体(人民币)指数",
    "399673.SZ": "创业板50指数",
}

for idx_sym, idx_name in index_symbols.items():
    print(f"\n{'='*60}")
    print(f"### {idx_name} ({idx_sym})")
    print(f"{'='*60}")
    
    try:
        # Get index info
        inst = tf.instruments.batch(symbols=[idx_sym])
        if inst:
            print(f"标的: {inst[0].get('name', 'N/A')}")
    except Exception as e:
        print(f"信息获取失败: {e}")
    
    try:
        df = tf.klines.get(idx_sym, period="1d", count=400, as_dataframe=True)
        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            print(f"数据范围: {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}")
            print(f"最新收盘价: {latest['close']}")
            
            # Calculate returns
            if len(df) >= 22:
                month_ret = (latest['close'] - df.iloc[-22]['close']) / df.iloc[-22]['close'] * 100
                print(f"近一月涨跌幅: {month_ret:.2f}%")
            
            # YTD
            ytd = df[df['trade_date'] >= '2026-01-01']
            if len(ytd) > 1:
                ytd_ret = (latest['close'] - ytd.iloc[0]['close']) / ytd.iloc[0]['close'] * 100
                print(f"年初至今涨跌幅: {ytd_ret:.2f}%")
            
            # PE/PB if available
            print(f"\n最近5个交易日:")
            print(df[['trade_date', 'close', 'volume']].tail(5).to_string())
        else:
            print("无数据")
    except Exception as e:
        print(f"K线获取失败: {e}")
