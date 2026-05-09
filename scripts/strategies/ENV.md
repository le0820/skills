# strategies 环境说明

## 项目结构

```
strategies/
├── data_fetch/              # 数据获取模块
│   └── fetch_market_data.py
├── data_engineering/        # 数据工程模块
│   └── bond_pca_analysis.py
├── factor_mining/           # 因子挖掘及筛选模块
│   └── lgbm_macro_timing.py
├── backtest/                # 回测分析模块
│   ├── run_backtest_comparison.py
│   ├── strategy_comparison.py
│   └── turtle_only.py
├── output/                  # 输出目录（CSV、图表等）
├── .venv/                   # 虚拟环境
├── ENV.md                   # 本文件
└── requirements.txt         # 依赖列表
```

## 模块说明

### 1. 数据获取 (data_fetch)
获取A股、港股、美股、期货等市场数据。
- 支持 akshare 和 tickflow 两个数据源
- 输出标准格式的CSV文件

```bash
scripts/strategies/.venv/bin/python data_fetch/fetch_market_data.py
```

### 2. 数据工程 (data_engineering)
数据清洗、特征工程、降维分析等。
- PCA分析（债券收益率曲线）

```bash
scripts/strategies/.venv/bin/python data_engineering/bond_pca_analysis.py
```

### 3. 因子挖掘及筛选 (factor_mining)
基于机器学习的因子挖掘和择时策略。
- LightGBM宏观择时策略

```bash
scripts/strategies/.venv/bin/python factor_mining/lgbm_macro_timing.py
```

### 4. 回测分析 (backtest)
策略回测和绩效分析。
- 动量策略回测比较
- 多策略对比（双均线、布林带、海龟）
- 综合分析图表

```bash
scripts/strategies/.venv/bin/python backtest/run_backtest_comparison.py
scripts/strategies/.venv/bin/python backtest/strategy_comparison.py
scripts/strategies/.venv/bin/python backtest/turtle_only.py
```

## 虚拟环境

路径: `.venv/`

## 激活环境

```bash
source scripts/strategies/.venv/bin/activate
```

## 运行脚本

```bash
# 方式一：激活后运行
source scripts/strategies/.venv/bin/activate
python data_fetch/fetch_market_data.py

# 方式二：直接调用 venv 中的 python
scripts/strategies/.venv/bin/python data_fetch/fetch_market_data.py
```

## 依赖包

| 包名 | 版本 | 用途 |
|------|------|------|
| akquant | 0.2.23 | 量化回测框架 |
| akshare | 1.18.60 | A股数据获取 |
| tickflow | 0.1.21 | TickFlow数据源（A股/港股/美股/期货） |
| pandas | 3.0.2 | 数据处理 |
| numpy | 2.4.4 | 数值计算 |
| lightgbm | 4.6.0 | 机器学习模型 |
| scikit-learn | 1.8.0 | 机器学习工具 |
| matplotlib | 3.10.9 | 数据可视化 |
| plotly | 6.7.0 | 交互式图表 |
| polars | 1.40.1 | 高性能数据处理 |
| pyarrow | 24.0.0 | 列式数据格式 |

## 安装新依赖

```bash
scripts/strategies/.venv/bin/pip install <package_name>
```

pip 已配置清华源 (`~/.pip/pip.conf`)。

---

## AKQuant 框架参考文档

### 官方文档
- **完整文档**: https://akquant.akfamily.xyz
- **英文文档**: https://akquant.akfamily.xyz/en/
- **GitHub**: https://github.com/akfamily/akquant

### 核心 API 索引

#### 1. 回测引擎
```python
from akquant import Strategy, Bar, run_backtest, ExecutionMode

# 运行回测
result = run_backtest(
    strategy=MyStrategy,
    data=df,
    initial_cash=100000.0,
    symbols="sh600000",
    t_plus_one=True,          # T+1 交易规则
    commission_rate=0.0003,   # 佣金费率
    stamp_tax_rate=0.001      # 印花税
)
```

#### 2. 策略基类
```python
class MyStrategy(Strategy):
    warmup_period = 20  # 预热期
    
    def on_bar(self, bar: Bar):
        # bar 属性: open, high, low, close, volume, timestamp, symbol
        # 获取历史数据
        hist = self.get_history(count=20, field="close", symbol=bar.symbol)
        
        # 获取持仓
        position = self.get_position(bar.symbol)
        
        # 下单
        self.buy(symbol, quantity=100)
        self.sell(symbol, quantity=100)
        self.close_position(symbol)
        self.order_target_percent(symbol, 0.5)  # 调整至50%仓位
```

#### 3. 回测结果
```python
# 获取指标
result.metrics.total_return_pct    # 总收益率
result.metrics.annualized_return   # 年化收益率
result.metrics.max_drawdown_pct    # 最大回撤
result.metrics.sharpe_ratio        # 夏普比率
result.metrics.sortino_ratio       # 索提诺比率
result.metrics.win_rate            # 胜率
result.metrics.trade_count         # 交易次数

# 生成报告
result.report(show=True)           # 交互式HTML报告
result.report(filename="report.html", show=False, benchmark=benchmark_returns)

# 结构化数据
result.exposure_df()               # 暴露分解
result.attribution_df(by="symbol") # 归因分析
result.capacity_df()               # 容量分析
```

#### 4. 机器学习集成
```python
from akquant import Strategy, ExecutionMode, run_backtest
from akquant.ml import SklearnAdapter

class MLStrategy(Strategy):
    def __init__(self):
        pipeline = Pipeline([
            ('scaler', StandardScaler()),
            ('model', lgb.LGBMClassifier())
        ])
        self.model = SklearnAdapter(pipeline)
        
        # Walk-forward Validation
        self.model.set_validation(
            method='walk_forward',
            train_window=250,
            rolling_step=20,
            frequency='1d'
        )
```

#### 5. 复杂订单
```python
from akquant import OrderStatus, Strategy

class BracketStrategy(Strategy):
    def on_bar(self, bar):
        # Bracket 订单（止损+止盈）
        order_id = self.place_bracket_order(
            symbol=bar.symbol,
            quantity=100,
            stop_trigger_price=bar.close * 0.98,
            take_profit_price=bar.close * 1.04
        )
```

### API 参考文档链接
- **快速入门**: https://akquant.akfamily.xyz/start/quickstart/
- **API 参考**: https://akquant.akfamily.xyz/reference/api/
- **机器学习指南**: https://akquant.akfamily.xyz/advanced/ml/
- **安装指南**: https://akquant.akfamily.xyz/start/installation/
