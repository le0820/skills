import numpy as np
import pandas as pd
import akshare as ak
from akquant import Strategy, run_backtest, Bar

# 加载数据
def load_data(symbol, start_date, end_date):
    print(f"开始加载 {symbol} 数据...")
    
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
        print(f"使用 stock_zh_a_daily 失败: {e}")
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
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
            dates = pd.date_range(start=start_date, end=end_date, freq='B')
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
    
    df['date'] = pd.to_datetime(df['date'])
    df['symbol'] = symbol
    df = df[["date", "open", "high", "low", "close", "volume", "symbol"]]
    
    print(f"数据加载完成，共 {len(df)} 条记录")
    return df

# 海龟策略
class TurtleStrategy(Strategy):
    """
    短版海龟策略：
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
        self.risk_per_trade = risk_per_trade
        self.max_units = max_units
        self.atr_period = atr_period
        self.breakout_period = breakout_period
        self.stop_period = stop_period
        self.max_positions = max_positions
        
        self.set_history_depth(max(55, atr_period, breakout_period, stop_period))
        
        self.positions = {}
        self.trade_log = []  # 记录所有交易
    
    def _calc_atr(self, symbol: str) -> float:
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
        
        trade_info = {
            "time": bar.timestamp_str,
            "type": "买入(开仓)",
            "symbol": symbol,
            "price": price,
            "quantity": qty_unit,
            "high_20": high_20,
            "atr": atr,
            "units": 1
        }
        self.trade_log.append(trade_info)
        
        print(f"[{bar.timestamp_str}] 【买入开仓】 {symbol} 价格={price:.2f} 数量={qty_unit}股 突破20日高点={high_20:.2f} ATR={atr:.3f}")
        
        self.positions[symbol] = {
            "units": 1,
            "qty_per_unit": qty_unit,
            "avg_entry": price,
            "max_price": price,
            "last_add_price": price,
            "atr": atr,
        }
    
    def _manage_position(self, bar: Bar, low_10: float):
        symbol = bar.symbol
        price = bar.close
        pos = self.positions[symbol]
        atr = pos["atr"]
        
        if price > pos["max_price"]:
            pos["max_price"] = price
        
        # 加仓逻辑
        add_threshold = pos["last_add_price"] + 0.5 * atr
        if price >= add_threshold and pos["units"] < self.max_units:
            qty_add = pos["qty_per_unit"]
            self.buy(symbol=symbol, quantity=qty_add)
            pos["units"] += 1
            pos["last_add_price"] = price
            
            trade_info = {
                "time": bar.timestamp_str,
                "type": "买入(加仓)",
                "symbol": symbol,
                "price": price,
                "quantity": qty_add,
                "units": pos["units"]
            }
            self.trade_log.append(trade_info)
            
            print(f"[{bar.timestamp_str}] 【买入加仓】 {symbol} 价格={price:.2f} 数量={qty_add}股 总Units={pos['units']}")
        
        # 止损逻辑
        drawdown = pos["max_price"] - price
        hit_atr_stop = drawdown >= 2 * atr
        hit_channel_stop = price <= low_10
        
        if hit_atr_stop or hit_channel_stop:
            total_qty = pos["units"] * pos["qty_per_unit"]
            self.sell(symbol=symbol, quantity=total_qty)
            
            reason = "ATR回撤2N" if hit_atr_stop else "跌破10日低点"
            
            trade_info = {
                "time": bar.timestamp_str,
                "type": "卖出(平仓)",
                "symbol": symbol,
                "price": price,
                "quantity": total_qty,
                "reason": reason,
                "units": pos["units"]
            }
            self.trade_log.append(trade_info)
            
            print(f"[{bar.timestamp_str}] 【卖出平仓】 {symbol} 价格={price:.2f} 数量={total_qty}股 原因={reason}")
            del self.positions[symbol]
    
    def on_bar(self, bar: Bar):
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

# 主函数
def main():
    # 配置参数
    symbol = "601899"
    start_date = "20200212"
    end_date = "20250212"
    initial_cash = 100000.0
    
    # 加载数据
    df = load_data(symbol, start_date, end_date)
    
    # 运行海龟策略回测
    print("\n" + "="*60)
    print("运行海龟策略回测")
    print("="*60)
    
    strategy = TurtleStrategy()
    result = run_backtest(
        strategy=strategy,
        data=df,
        initial_cash=initial_cash
    )
    
    # 打印回测结果
    print("\n" + "="*60)
    print("海龟策略回测结果")
    print("="*60)
    print(result)
    
    # 打印交易明细
    print("\n" + "="*60)
    print("交易明细")
    print("="*60)
    
    if strategy.trade_log:
        for i, trade in enumerate(strategy.trade_log, 1):
            print(f"\n交易 #{i}:")
            for key, value in trade.items():
                if isinstance(value, float):
                    print(f"  {key}: {value:.2f}")
                else:
                    print(f"  {key}: {value}")
    else:
        print("没有交易记录")
    
    # 统计信息
    print("\n" + "="*60)
    print("交易统计")
    print("="*60)
    
    buy_count = sum(1 for t in strategy.trade_log if "买入" in t["type"])
    sell_count = sum(1 for t in strategy.trade_log if "卖出" in t["type"])
    
    print(f"总交易次数: {len(strategy.trade_log)}")
    print(f"买入次数: {buy_count}")
    print(f"卖出次数: {sell_count}")
    
    # 绘制资金曲线
    print("\n绘制资金曲线...")
    result.report(show=True)
    
    # 保存结果
    with open(f"turtle_detailed_result.md", "w", encoding="utf-8") as f:
        f.write("# 海龟策略详细回测结果\n\n")
        f.write("## 回测配置\n\n")
        f.write(f"- 标的: {symbol}\n")
        f.write(f"- 起始日期: {start_date}\n")
        f.write(f"- 结束日期: {end_date}\n")
        f.write(f"- 初始资金: {initial_cash}\n\n")
        
        f.write("## 回测结果\n\n")
        f.write(str(result))
        f.write("\n\n")
        
        f.write("## 交易明细\n\n")
        if strategy.trade_log:
            for i, trade in enumerate(strategy.trade_log, 1):
                f.write(f"### 交易 #{i}\n\n")
                for key, value in trade.items():
                    if isinstance(value, float):
                        f.write(f"- {key}: {value:.2f}\n")
                    else:
                        f.write(f"- {key}: {value}\n")
                f.write("\n")
        else:
            f.write("没有交易记录\n")
    
    print("\n详细结果已保存到 turtle_detailed_result.md")

if __name__ == "__main__":
    main()
