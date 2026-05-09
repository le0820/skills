#!/usr/bin/env python3
"""
因子挖掘模块 - 基于 LightGBM 的宏观择时策略

功能：
- 使用 LightGBM 分类模型预测市场涨跌
- 集成宏观因子（CPI、PPI、汇率、利率等）和技术因子
- 实现 Walk-forward Validation（滚动训练）避免过拟合

特征体系：
- 微观量价特征: 收益率、波动率
- 技术指标特征: MACD、RSI、布林带
- 宏观因子特征: CPI、PPI、美元指数、汇率、国债收益率、黄金、原油

使用方法：
    scripts/strategies/.venv/bin/python factor_mining/lgbm_macro_timing.py

注意：
    需要预先准备合并后的数据文件: data/merged_dataset.csv
"""
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, classification_report
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from akquant import Strategy, ExecutionMode, run_backtest
from akquant.ml import SklearnAdapter


class LightGBMMacroTiming(Strategy):
    """
    基于 LightGBM 与宏观数据的单资产择时策略
    
    特点：
    1. 使用 Walk-forward Validation 避免过拟合
    2. 集成微观量价、技术指标、宏观因子三类特征
    3. 基于概率阈值的仓位控制
    """

    def __init__(self, buy_threshold=0.55, sell_threshold=0.45):
        """
        初始化策略
        
        Args:
            buy_threshold: 买入概率阈值，预测概率超过此值时买入
            sell_threshold: 卖出概率阈值，预测概率低于此值时卖出
        """
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        
        # 1. Pipeline 封装：标准化 + LightGBM 二分类器
        pipeline = Pipeline([
            ('scaler', StandardScaler()),
            ('model', lgb.LGBMClassifier(
                n_estimators=100,
                max_depth=3,
                learning_rate=0.05,
                random_state=42,
                n_jobs=-1,
                verbose=-1
            ))
        ])

        # 2. 注入 AKQuant 适配器
        self.model = SklearnAdapter(pipeline)

        # 3. 配置 Walk-forward Validation
        self.model.set_validation(
            method='walk_forward',
            train_window=250,    # 过去250个交易日(1年)作为训练集
            rolling_step=20,     # 每隔20个交易日(约1个月)重新训练一次模型
            frequency='1d',      # 数据频率为日频
            incremental=False,   # 每次使用新窗口从头重训
            verbose=True
        )

        # 4. 设置历史深度
        # 必须大于 train_window + 提取特征所需的最大历史窗口
        self.set_history_depth(300)

    def prepare_features(self, df: pd.DataFrame, mode: str = "training"):
        """
        特征工程：计算微观+宏观特征，以及预测标签
        
        Args:
            df: 历史数据 DataFrame
            mode: "training" 或 "inference"
            
        Returns:
            训练模式: (X, y) 特征矩阵和标签
            推理模式: X 特征矩阵（仅最新一行）
        """
        df = df.copy()
        X = pd.DataFrame(index=df.index)

        # --- 1. 微观量价特征 ---
        X['ret_1d'] = df['close'].pct_change(1)      # 1日收益率
        X['ret_5d'] = df['close'].pct_change(5)      # 5日收益率
        X['ret_10d'] = df['close'].pct_change(10)    # 10日收益率
        X['volatility_20d'] = df['close'].pct_change().rolling(20).std()  # 20日波动率
        X['volatility_60d'] = df['close'].pct_change().rolling(60).std()  # 60日波动率

        # --- 2. 技术指标特征 ---
        # 均线
        X['ma5'] = df['close'].rolling(5).mean()
        X['ma20'] = df['close'].rolling(20).mean()
        X['ma60'] = df['close'].rolling(60).mean()
        X['ma5_ratio'] = df['close'] / X['ma5'] - 1    # 价格/MA5 偏离度
        X['ma20_ratio'] = df['close'] / X['ma20'] - 1  # 价格/MA20 偏离度
        
        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        X['macd'] = exp1 - exp2
        X['macd_signal'] = X['macd'].ewm(span=9, adjust=False).mean()
        X['macd_hist'] = X['macd'] - X['macd_signal']
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        X['rsi'] = 100 - (100 / (1 + rs))
        
        # 布林带
        X['bb_middle'] = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        X['bb_upper'] = X['bb_middle'] + 2 * bb_std
        X['bb_lower'] = X['bb_middle'] - 2 * bb_std
        X['bb_width'] = (X['bb_upper'] - X['bb_lower']) / X['bb_middle']  # 布林带宽度
        X['bb_position'] = (df['close'] - X['bb_lower']) / (X['bb_upper'] - X['bb_lower'])  # 价格在布林带中的位置

        # --- 3. 宏观因子特征 ---
        macro_mapping = {
            'cpi_china_cpi_yoy': 'macro_cpi_cn',           # 中国CPI
            'cpi_usa_cpi_yoy': 'macro_cpi_us',             # 美国CPI
            'ppi_china_ppi_yoy': 'macro_ppi_cn',           # 中国PPI
            'usd_index_close': 'macro_usd_idx',            # 美元指数
            'usd_cny_rate': 'macro_usd_cny',               # 美元/人民币汇率
            'us_bond_10y_close': 'macro_ust10y',           # 美国10年期国债收益率
            'us_bond_2y_close': 'macro_ust2y',             # 美国2年期国债收益率
            'gold_close': 'macro_gold',                    # 黄金价格
            'brent_oil_close': 'macro_oil',                # 布伦特原油价格
            'gold_oil_ratio_gold_oil_ratio': 'macro_gor',  # 金油比
            'us_bond_term_premium_term_premium': 'macro_ustp'  # 美国期限溢价
        }

        for df_col, feature_name in macro_mapping.items():
            if df_col in df.columns:
                X[feature_name] = df[df_col]
                X[f'{feature_name}_chg5'] = df[df_col].pct_change(5)  # 5日变化率
                X[f'{feature_name}_chg20'] = df[df_col].pct_change(20)  # 20日变化率

        # --- 4. 模式分支 ---
        if mode == 'inference':
            # 推理模式：只返回最新一行，且不能包含 NaN
            X_infer = X.ffill().iloc[-1:]
            return X_infer

        # --- 5. 训练模式：构建标签 (y) ---
        # 预测目标：未来 5 天的累计收益率是否 > 0
        future_ret_5d = df['close'].shift(-5) / df['close'] - 1

        # 合并 X 和 y，保证 dropna 时同步删除
        data = pd.concat([X, future_ret_5d.rename("future_ret")], axis=1)

        # 清洗数据：删除特征因为计算产生的 NaN，删除标签因为 shift 产生的最后 5 行 NaN
        data = data.dropna()

        # 生成最终的 X 和 二分类 y (1为涨，0为跌)
        y_clean = (data["future_ret"] > 0).astype(int)
        X_clean = data[X.columns]

        return X_clean, y_clean

    def on_bar(self, bar):
        """
        实盘/回测逐根 K 线执行逻辑
        
        Args:
            bar: 当前K线数据
        """
        # 获取用于计算特征的历史数据
        hist_df = self.get_history_df(30)

        if len(hist_df) < 25:  # 数据不足跳过
            return

        # 提取当前特征
        X_curr = self.prepare_features(hist_df, mode='inference')

        try:
            # 获取预测信号（由于是二分类，predict() 返回上涨概率）
            prob_up = self.model.predict(X_curr)[0]

            # 获取当前持仓
            pos = self.get_position(bar.symbol)

            # 策略逻辑：基于概率的简单阈值控制
            trade_qty = 1000  # 固定交易数量

            if prob_up > self.buy_threshold and pos == 0:
                # 胜率较高，且当前空仓 -> 买入
                self.buy(bar.symbol, trade_qty)

            elif prob_up < self.sell_threshold and pos > 0:
                # 胜率较低，且当前有持仓 -> 平仓
                self.sell(bar.symbol, pos)

        except Exception as e:
            # 模型在最开始 warmup 期间可能尚未 fit，捕获异常跳过
            pass


def prepare_merged_data(data_path: str = 'data/merged_dataset.csv') -> pd.DataFrame:
    """
    准备合并后的数据
    
    Args:
        data_path: 数据文件路径
    
    Returns:
        DataFrame: 合并后的数据，包含价格、技术指标、宏观因子
    """
    # 读取之前合并好的数据
    df = pd.read_csv(data_path)
    df['date'] = pd.to_datetime(df['date'])

    # 重命名 date 为 timestamp 以适配 AKQuant 要求
    df = df.rename(columns={'date': 'timestamp'})

    return df


if __name__ == "__main__":
    print("="*70)
    print("LightGBM 宏观择时策略滚动回测")
    print("="*70)

    # 准备数据
    data_path = 'data/merged_dataset.csv'
    if not os.path.exists(data_path):
        print(f"错误: 数据文件不存在: {data_path}")
        print("请先运行数据获取脚本准备数据")
        sys.exit(1)
    
    df = prepare_merged_data(data_path)

    print(f"\n数据加载完成: {len(df)} 行")
    print(f"日期范围: {df['timestamp'].min().date()} 至 {df['timestamp'].max().date()}")
    print(f"列: {list(df.columns)}")
    print()

    # 运行回测
    result = run_backtest(
        data=df,
        strategy=LightGBMMacroTiming,
        symbol="601899",         # 标的代码
        lot_size=100,            # A股买卖最小单位 1手=100股
        execution_mode=ExecutionMode.CurrentClose,  # 使用收盘价成交
        history_depth=300,       # 对应 strategy 中的设置
        warmup_period=250        # 初始化模型需要的最小天数(等同于train_window)
    )

    print("\n" + "="*70)
    print("回测结束！绩效指标如下：")
    print("="*70)
    print(result)
    
    # 输出关键指标
    print("\n" + "="*70)
    print("关键指标:")
    print("="*70)
    print(f"总收益率: {result.metrics.total_return_pct*100:.2f}%")
    print(f"年化收益率: {result.metrics.annualized_return*100:.2f}%")
    print(f"最大回撤: {result.metrics.max_drawdown_pct*100:.2f}%")
    print(f"夏普比率: {result.metrics.sharpe_ratio:.2f}")
    print(f"胜率: {result.metrics.win_rate:.2f}%")
    print(f"交易次数: {result.metrics.trade_count}")
