#!/usr/bin/env python3
"""
数据获取模块 - 获取A股、港股、美股、期货等市场数据
支持 akshare 和 tickflow 两个数据源
"""
import os
import sys
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def fetch_stock_data_akshare(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    使用 akshare 获取A股数据
    
    Args:
        symbol: 股票代码，如 "600000"
        start_date: 开始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"
    
    Returns:
        DataFrame with columns: date, open, high, low, close, volume, symbol
    """
    import akshare as ak
    
    print(f"使用 akshare 获取 {symbol} 数据...")
    
    try:
        df = ak.stock_zh_a_daily(symbol=f"sh{symbol}", start_date=start_date, end_date=end_date)
        df = df.rename(columns={
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume"
        })
    except Exception as e:
        print(f"stock_zh_a_daily 失败: {e}")
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", 
                                start_date=start_date, end_date=end_date, adjust="qfq")
        df = df.rename(columns={
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume"
        })
    
    df['date'] = pd.to_datetime(df['date'])
    df['symbol'] = symbol
    df = df[["date", "open", "high", "low", "close", "volume", "symbol"]]
    
    print(f"  获取完成: {len(df)} 条记录, {df['date'].min().date()} 至 {df['date'].max().date()}")
    return df


def fetch_etf_data_akshare(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    使用 akshare 获取ETF数据
    
    Args:
        symbol: ETF代码，如 "513130"
        start_date: 开始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"
    
    Returns:
        DataFrame with columns: date, open, high, low, close, volume, symbol
    """
    import akshare as ak
    
    print(f"使用 akshare 获取ETF {symbol} 数据...")
    
    df = ak.fund_etf_hist_em(symbol=symbol, period="daily",
                              start_date=start_date, end_date=end_date)
    df = df.rename(columns={
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume"
    })
    
    df['date'] = pd.to_datetime(df['date'])
    df['symbol'] = symbol
    df = df[["date", "open", "high", "low", "close", "volume", "symbol"]]
    
    print(f"  获取完成: {len(df)} 条记录, {df['date'].min().date()} 至 {df['date'].max().date()}")
    return df


def fetch_data_tickflow(symbol: str, tickflow_symbol: str, 
                        count: int = 1200, start_date: str = None) -> pd.DataFrame:
    """
    使用 tickflow 获取市场数据（支持A股、港股、美股、期货）
    
    Args:
        symbol: 标的代码，如 "159967"
        tickflow_symbol: tickflow格式代码，如 "159967.SZ"
        count: 获取K线数量
        start_date: 开始日期，格式 "YYYY-MM-DD"
    
    Returns:
        DataFrame with columns: date, open, high, low, close, volume, symbol
    """
    from tickflow import TickFlow
    
    print(f"使用 tickflow 获取 {tickflow_symbol} 数据...")
    
    tf = TickFlow()
    df_tf = tf.klines.get(tickflow_symbol, count=count, as_dataframe=True)
    df_tf['date'] = pd.to_datetime(df_tf['trade_date'])
    df_tf['symbol'] = symbol
    df = df_tf[["date", "open", "high", "low", "close", "volume", "symbol"]].copy()
    df = df.sort_values('date').reset_index(drop=True)
    
    if start_date:
        df = df[df['date'] >= pd.to_datetime(start_date)].reset_index(drop=True)
    
    print(f"  获取完成: {len(df)} 条记录, {df['date'].min().date()} 至 {df['date'].max().date()}")
    return df


def fetch_bond_data_akshare(start_date: str = "19901219") -> pd.DataFrame:
    """
    使用 akshare 获取国债收益率数据
    
    Args:
        start_date: 开始日期，格式 "YYYYMMDD"
    
    Returns:
        DataFrame with bond yield data
    """
    import akshare as ak
    
    print(f"使用 akshare 获取国债收益率数据...")
    
    df = ak.bond_zh_us_rate(start_date=start_date)
    
    print(f"  获取完成: {len(df)} 条记录")
    return df


def save_data(df: pd.DataFrame, output_path: str):
    """保存数据到CSV文件"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"数据已保存到: {output_path}")


if __name__ == "__main__":
    # 示例：获取A股数据
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=365*3)).strftime("%Y%m%d")
    
    # 获取浦发银行数据
    df = fetch_stock_data_akshare("600000", start_date, end_date)
    save_data(df, "output/stock_600000.csv")
    
    # 获取恒生科技ETF数据
    df_etf = fetch_etf_data_akshare("513130", start_date, end_date)
    save_data(df_etf, "output/etf_513130.csv")
    
    print("\n数据获取完成！")
