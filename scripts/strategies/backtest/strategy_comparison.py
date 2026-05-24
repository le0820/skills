#!/usr/bin/env python3
"""
回测分析模块 - 多策略对比分析

功能：
- 运行多种经典策略的回测
- 对比不同策略的表现
- 生成详细的回测报告

策略列表：
1. 双均线策略 (Dual Moving Average): 金叉死叉交易
2. 布林带策略 (Bollinger Bands): 超买超卖反转
3. 海龟策略 (Turtle): 趋势跟踪突破

使用方法：
    scripts/strategies/.venv/bin/python backtest/strategy_comparison.py
"""
import numpy as np
import pandas as pd
import akshare as ak
from akquant import Strategy, run_backtest, Bar
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    加载股票数据
    
    Args:
        symbol: 股票代码，如 "601899"
        start_date: 开始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"
    
    Returns:
        DataFrame: 包含 date, open, high, low, close, volume, symbol 列
    """
    print(f"开始加载 {symbol} 数据...")
    
    # 尝试使用不同的 akshare 函数获取数据
    try:
        # 首先尝试使用 stock_zh_a_daily 函数
        df = ak.stock_zh_a_daily(symbol=f"sh{symbol}", start_date=start_date, end_date=end_date)
        
        # 数据清洗：将 AKShare 的中文列名转换为 AKQuant 需要的英文标准格式
        df = df.rename(columns={
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume"
        })
    except Exception as e:
        print(f"使用 stock_zh_a_daily 失败: {e}")
        try:
            # 尝试使用 stock_zh_a_hist 函数
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", 
                                    start_date=start_date, end_date=end_date, adjust="qfq")
            
            # 数据清洗：将 AKShare 的中文列名转换为 AKQuant 需要的英文标准格式
            df = df.rename(columns={
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume"
            })
        except Exception as e2:
            print(f"使用 stock_zh_a_hist 失败: {e2}")
            # 如果都失败，创建模拟数据
            print("创建模拟数据用于演示...")
            # 创建日期范围
            dates = pd.date_range(start=start_date, end=end_date, freq='B')
            # 创建模拟数据
            np.random.seed(42)
            close = np.random.randn(len(dates)) * 2 + 10
            close = np.cumsum(close) + 100
            
            df = pd.DataFrame({
                "date": dates,
                "open": close * (1 + np.random.randn(len(dates)) * 0.01),
                "high": close * (1 + np.random.randn(len(dates)) * 0.02),
                "low": close * (1 - np.random.randn(len(dates)) * 0.02),
                "close": close,
                "volume": np.random.randint(1000000, 10000000, len(dates))
            })
    
    # 格式转换：确保 date 列是 datetime 类型
    df['date'] = pd.to_datetime(df['date'])
    df['symbol'] = symbol  # 添加代码列
    
    # 筛选需要的列
    df = df[["date", "open", "high", "low", "close", "volume", "symbol"]]
    
    print(f"数据加载完成，共 {len(df)} 条记录")
    return df


class DualMovingAverageStrategy(Strategy):
    """
    双均线策略
    
    规则：
    - 快速均线：20日
    - 慢速均线：60日
    - 金叉（快速上穿慢速）：买入
    - 死叉（快速下穿慢速）：卖出
    """
    
    def __init__(self, fast_window=20, slow_window=60):
        """
        初始化策略
        
        Args:
            fast_window: 快速均线周期
            slow_window: 慢速均线周期
        """
        self.fast_window = fast_window
        self.slow_window = slow_window
        # 启用历史数据跟踪
        self.set_history_depth(slow_window + 1)
    
    def on_bar(self, bar: Bar):
        """
        每根K线执行逻辑
        
        Args:
            bar: 当前K线数据
        """
        # 获取历史收盘价数据
        hist = self.get_history(count=self.slow_window + 1, field="close")
        
        # 如果数据不足，无法计算均线，直接返回
        if len(hist) < self.slow_window:
            return
        
        # 计算短期和长期均线
        closes = hist
        ma_short = np.mean(closes[-self.fast_window:])
        ma_long = np.mean(closes[-self.slow_window:])
        
        # 获取上一时刻的均线值（用于判断交叉）
        prev_ma_short = np.mean(closes[-self.fast_window - 1: -1])
        prev_ma_long = np.mean(closes[-self.slow_window - 1: -1])
        
        # 获取当前持仓
        current_pos = self.get_position(bar.symbol)
        
        # 金叉 (买入信号)
        if prev_ma_short <= prev_ma_long and ma_short > ma_long and current_pos == 0:
            self.buy(bar.symbol, 100)
            print(f"[{bar.timestamp_str}] 金叉 - 买入 {bar.symbol} @ {bar.close:.2f}")
        
        # 死叉 (卖出信号)
        elif prev_ma_short >= prev_ma_long and ma_short < ma_long and current_pos > 0:
            self.sell(bar.symbol, 100)
            print(f"[{bar.timestamp_str}] 死叉 - 卖出 {bar.symbol} @ {bar.close:.2f}")


class BollingerBandsStrategy(Strategy):
    """
    布林带策略
    
    规则：
    - 中轨：20日均线
    - 上轨：中轨 + 2倍标准差
    - 下轨：中轨 - 2倍标准差
    - 买入：价格跌破下轨后反弹
    - 卖出：价格突破上轨或回归中轨
    """
    
    def __init__(self, window=20, num_std=2):
        """
        初始化策略
        
        Args:
            window: 均线周期
            num_std: 标准差倍数
        """
        self.window = window
        self.num_std = num_std
        self.prev_close = None
        # 启用历史数据跟踪
        self.set_history_depth(window + 1)
    
    def on_bar(self, bar: Bar):
        """
        每根K线执行逻辑
        
        Args:
            bar: 当前K线数据
        """
        # 获取历史收盘价数据
        hist = self.get_history(count=self.window + 1, field="close")
        
        # 如果数据不足，无法计算指标，直接返回
        if len(hist) < self.window:
            return
        
        # 计算中轨、上轨和下轨
        closes = hist
        ma = np.mean(closes[-self.window:])
        std = np.std(closes[-self.window:])
        upper = ma + self.num_std * std
        lower = ma - self.num_std * std
        
        # 获取当前价格和持仓
        current_price = bar.close
        current_pos = self.get_position(bar.symbol)
        
        # 买入信号：价格跌破下轨且开始反弹
        if (current_price < lower and 
            self.prev_close is not None and 
            self.prev_close <= current_price and 
            current_pos == 0):
            self.buy(bar.symbol, 100)
            print(f"[{bar.timestamp_str}] 超跌反弹 - 买入 {bar.symbol} @ {current_price:.2f}")
        
        # 卖出信号：价格突破上轨或回归中轨
        elif (current_price > upper or current_price > ma) and current_pos > 0:
            self.sell(bar.symbol, 100)
            print(f"[{bar.timestamp_str}] 超买或回归 - 卖出 {bar.symbol} @ {current_price:.2f}")
        
        # 更新上一收盘价
        self.prev_close = current_price


class TurtleStrategy(Strategy):
    """
    海龟策略 (简化版)
    
    规则：
    - 入场：20日唐奇安上轨突破
    - 止损：ATR回撤2N或跌破10日低点
    - 加仓：每0.5N上涨加1Unit，最多4Unit
    - 资金管理：单笔风险固定1%账户权益
    """
    
    def __init__(
        self,
        risk_per_trade: float = 0.01,
        max_units: int = 4,
        atr_period: int = 20,
        breakout_period: int = 20,
        stop_period: int = 10,
        max_positions: int = 10
    ):
        """
        初始化策略
        
        Args:
            risk_per_trade: 单笔交易风险比例
            max_units: 最大加仓次数
            atr_period: ATR 计算周期
            breakout_period: 突破周期
            stop_period: 止损周期
            max_positions: 最大持仓数
        """
        self.risk_per_trade = risk_per_trade
        self.max_units = max_units
        self.atr_period = atr_period
        self.breakout_period = breakout_period
        self.stop_period = stop_period
        self.max_positions = max_positions
        
        self.set_history_depth(max(55, atr_period, breakout_period, stop_period))
        
        self.positions = {}
    
    def _calc_atr(self, symbol: str) -> float:
        """
        计算 ATR (Average True Range)
        
        Args:
            symbol: 股票代码
        
        Returns:
            float: ATR 值
        """
        highs = self.get_history(count=self.atr_period, field="high")
        lows = self.get_history(count=self.atr_period, field="low")
        closes = self.get_history(count=self.atr_period, field="close")
        
        if len(highs) < self.atr_period or len(closes) < self.atr_period:
            return 0.0
        
        trs = []
        for i in range(1, len(highs)):
            h = highs[i]
            l = lows[i]
            c_prev = closes[i-1]
            
            if np.isnan(h) or np.isnan(l) or np.isnan(c_prev):
                continue
            
            tr = max(
                h - l,
                abs(h - c_prev),
                abs(l - c_prev),
            )
            trs.append(tr)
        
        if not trs:
            return 0.0
        
        return np.mean(trs) if trs else 0.0
    
    def _maybe_open(self, bar: Bar, high_20: float):
        """
        尝试开仓
        
        Args:
            bar: 当前K线数据
            high_20: 20日最高价
        """
        symbol = bar.symbol
        price = bar.close
        
        if price <= high_20 or price <= 0:
            return
        
        atr = self._calc_atr(symbol)
        if atr <= 0 or np.isnan(atr):
            return
        
        account = self.get_account()
        equity = account.get("equity", 0.0)
        if equity <= 0 or np.isnan(equity):
            return
        
        try:
            unit_value = equity * self.risk_per_trade / (2 * atr)
            if unit_value <= 0 or np.isnan(unit_value):
                return
            
            qty_unit = int(unit_value / price)
            
            if qty_unit <= 0:
                return
        except (ValueError, TypeError, ZeroDivisionError):
            return
        
        self.buy(symbol=symbol, quantity=qty_unit)
        print(f"[{bar.timestamp_str}] [ENTRY] {symbol} 价格={price:.2f} 突破20日高点={high_20:.2f}, 开仓1Unit={qty_unit}股")
        
        self.positions[symbol] = {
            "units": 1,
            "qty_per_unit": qty_unit,
            "avg_entry": price,
            "max_price": price,
            "last_add_price": price,
            "atr": atr,
        }
    
    def _manage_position(self, bar: Bar, low_10: float):
        """
        管理持仓（加仓/止损）
        
        Args:
            bar: 当前K线数据
            low_10: 10日最低价
        """
        symbol = bar.symbol
        price = bar.close
        pos = self.positions[symbol]
        atr = pos["atr"]
        
        if price > pos["max_price"]:
            pos["max_price"] = price
        
        add_threshold = pos["last_add_price"] + 0.5 * atr
        if price >= add_threshold and pos["units"] < self.max_units:
            qty_add = pos["qty_per_unit"]
            self.buy(symbol=symbol, quantity=qty_add)
            pos["units"] += 1
            pos["last_add_price"] = price
            print(f"[{bar.timestamp_str}] [ADD] {symbol} 价格={price:.2f} 加仓1Unit={qty_add}股, 总Units={pos['units']}")
        
        drawdown = pos["max_price"] - price
        hit_atr_stop = drawdown >= 2 * atr
        hit_channel_stop = price <= low_10
        
        if hit_atr_stop or hit_channel_stop:
            total_qty = pos["units"] * pos["qty_per_unit"]
            self.sell(symbol=symbol, quantity=total_qty)
            reason = "ATR回撤2N" if hit_atr_stop else "跌破10日低点"
            print(f"[{bar.timestamp_str}] [EXIT] {symbol} {reason}, 平仓 {total_qty} 股, 价格={price:.2f}")
            del self.positions[symbol]
    
    def on_bar(self, bar: Bar):
        """
        每根K线执行逻辑
        
        Args:
            bar: 当前K线数据
        """
        symbol = bar.symbol
        price = bar.close
        
        if price is None or np.isnan(price):
            return
        
        pos = self.positions.get(symbol)
        
        if pos is None and len(self.positions) >= self.max_positions:
            return
        
        highs_20 = self.get_history(count=self.breakout_period, field="high")
        lows_10 = self.get_history(count=self.stop_period, field="low")
        
        if len(highs_20) < self.breakout_period or len(lows_10) < self.stop_period:
            return
        
        highs_20_valid = highs_20[:-1][~np.isnan(highs_20[:-1])]
        lows_10_valid = lows_10[:-1][~np.isnan(lows_10[:-1])]
        
        if len(highs_20_valid) == 0 or len(lows_10_valid) == 0:
            return
        
        high_20 = highs_20_valid.max()
        low_10 = lows_10_valid.min()
        
        if pos is None:
            self._maybe_open(bar, high_20)
        else:
            self._manage_position(bar, low_10)


def print_strategy_result(name: str, result):
    """
    打印策略回测结果
    
    Args:
        name: 策略名称
        result: 回测结果对象
    """
    print(f"\n{'='*60}")
    print(f"{name} 回测结果")
    print(f"{'='*60}")
    print(f"总收益率: {result.metrics.total_return_pct*100:.2f}%")
    print(f"年化收益率: {result.metrics.annualized_return*100:.2f}%")
    print(f"最大回撤: {result.metrics.max_drawdown_pct*100:.2f}%")
    print(f"夏普比率: {result.metrics.sharpe_ratio:.2f}")
    print(f"胜率: {result.metrics.win_rate:.2f}%")
    print(f"交易次数: {result.metrics.trade_count}")


def main():
    """主函数"""
    # 配置参数
    symbol = "601899"
    start_date = "20200212"
    end_date = "20250212"
    initial_cash = 100000.0
    
    # 加载数据
    df = load_data(symbol, start_date, end_date)
    
    # 策略列表
    strategies = [
        ("双均线策略", DualMovingAverageStrategy),
        ("布林带策略", BollingerBandsStrategy),
        ("海龟策略", TurtleStrategy),
    ]
    
    results = []
    
    # 运行各策略回测
    for name, strategy_class in strategies:
        print(f"\n{'='*60}")
        print(f"运行 {name} 回测...")
        print(f"{'='*60}")
        
        result = run_backtest(
            strategy=strategy_class,
            data=df,
            initial_cash=initial_cash
        )
        
        results.append((name, result))
        
        # 打印结果
        print_strategy_result(name, result)
        
        # 生成交互式报告
        report_filename = f"{name}_report.html"
        result.report(show=False, filename=report_filename)
        print(f"交互式报告已保存: {report_filename}")
    
    # 保存文本报告
    print(f"\n{'='*60}")
    print("保存文本报告...")
    print(f"{'='*60}")
    
    for name, result in results:
        filename = f"{name}_result.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# {name} 回测结果\n\n")
            f.write(f"- 标的: {symbol}\n")
            f.write(f"- 回测期间: {start_date} 至 {end_date}\n")
            f.write(f"- 初始资金: {initial_cash:,.0f}\n\n")
            f.write("## 绩效指标\n\n")
            f.write(f"- 总收益率: {result.metrics.total_return_pct*100:.2f}%\n")
            f.write(f"- 年化收益率: {result.metrics.annualized_return*100:.2f}%\n")
            f.write(f"- 最大回撤: {result.metrics.max_drawdown_pct*100:.2f}%\n")
            f.write(f"- 夏普比率: {result.metrics.sharpe_ratio:.2f}\n")
            f.write(f"- 胜率: {result.metrics.win_rate:.2f}%\n")
            f.write(f"- 交易次数: {result.metrics.trade_count}\n")
        print(f"报告已保存: {filename}")
    
    # 打印对比总结
    print(f"\n{'='*60}")
    print("策略对比总结")
    print(f"{'='*60}")
    print(f"{'策略名称':<12} {'总收益率':>10} {'年化收益':>10} {'最大回撤':>10} {'夏普比率':>10}")
    print("-"*52)
    for name, result in results:
        print(f"{name:<12} {result.metrics.total_return_pct*100:>9.2f}% "
              f"{result.metrics.annualized_return*100:>9.2f}% "
              f"{result.metrics.max_drawdown_pct*100:>9.2f}% "
              f"{result.metrics.sharpe_ratio:>10.2f}")
    
    print(f"\n{'='*60}")
    print("回测完成！请查看生成的 HTML 报告获取详细分析。")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
