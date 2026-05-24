#!/usr/bin/env python3
"""
数据工程模块 - 债券收益率曲线 PCA 分析

功能：
- 获取中国国债收益率数据
- 执行主成分分析 (PCA)
- 识别收益率曲线的三个主要因子：水平因子、斜率因子、曲率因子

输出：
- bond_pca_charts.png: PCA 分析图表
- bond_pca_loadings.csv: 载荷矩阵
- bond_pca_timeseries.csv: 主成分时间序列
- bond_pca_timeseries.png: 主成分时间序列图

使用方法：
    scripts/strategies/.venv/bin/python data_engineering/bond_pca_analysis.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

try:
    import akshare as ak
except ImportError:
    print("Warning: akshare not installed")
    print("Install: pip install akshare")
    sys.exit(1)


def get_bond_data() -> pd.DataFrame:
    """
    获取中国国债收益率数据
    
    Returns:
        DataFrame: 包含各期限国债收益率的原始数据
    """
    print("=" * 80)
    print("获取中国国债收益率数据...")
    print("=" * 80)

    df = ak.bond_zh_us_rate(start_date="19901219")

    print(f"\n数据获取成功: {len(df)} 条记录")
    print(f"日期范围: {df.iloc[-1, 0]} 至 {df.iloc[0, 0]}")
    print(f"\n列名: {df.columns.tolist()}")

    return df


def prepare_pca_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    准备 PCA 分析数据
    
    Args:
        df: 原始债券收益率数据
    
    Returns:
        DataFrame: 清洗后的收益率数据，包含 2Y, 5Y, 10Y, 30Y 期限
    """
    print("\n" + "=" * 80)
    print("数据清洗与准备...")
    print("=" * 80)

    # 查找可用的债券收益率列
    print("\n可用的债券收益率列:")
    for col in df.columns:
        if '国债' in col or 'China' in col:
            print(f"  - {col}")

    # 匹配期限列
    bond_columns = {}
    for term in ['2年', '5年', '10年', '30年']:
        for col in df.columns:
            if term in col and '国债' in col:
                bond_columns[term] = col
                break

    print(f"\n匹配的列:")
    for term, col in bond_columns.items():
        print(f"  {term}: {col}")

    if len(bond_columns) < 2:
        print("\n警告: 匹配的列不足，使用所有国债列")
        for col in df.columns:
            if '国债' in col:
                bond_columns[col] = col

    # 提取数据
    terms = list(bond_columns.keys())
    cols = list(bond_columns.values())

    df_clean = df.copy()

    # 转换日期并设置索引
    date_col = df_clean.columns[0]
    df_clean[date_col] = pd.to_datetime(df_clean[date_col])
    df_clean = df_clean.set_index(date_col)
    df_clean = df_clean.sort_index()

    # 保留需要的列并删除缺失值
    df_pca = df_clean[cols].copy()
    df_pca.columns = terms
    df_pca = df_pca.dropna()

    print(f"\n清洗后数据: {len(df_pca)} 条记录")
    print(f"日期范围: {df_pca.index[0].date()} 至 {df_pca.index[-1].date()}")
    print(f"\n前 5 行:")
    print(df_pca.head())

    return df_pca


def perform_pca_analysis(df_pca: pd.DataFrame) -> tuple:
    """
    执行 PCA 分析
    
    Args:
        df_pca: 清洗后的收益率数据
    
    Returns:
        tuple: (pca模型, 载荷矩阵, 主成分时间序列)
    """
    print("\n" + "=" * 80)
    print("执行 PCA 分析...")
    print("=" * 80)

    # 标准化数据
    scaler = StandardScaler()
    data_scaled = scaler.fit_transform(df_pca)

    # 执行 PCA
    pca = PCA()
    pca_result = pca.fit_transform(data_scaled)

    # 输出结果
    print("\n各主成分解释的方差比例:")
    for i, var in enumerate(pca.explained_variance_ratio_, 1):
        print(f"  PC{i}: {var*100:.2f}%")

    print(f"\n累计解释方差:")
    cumulative = np.cumsum(pca.explained_variance_ratio_)
    for i, var in enumerate(cumulative, 1):
        print(f"  前 {i} 个主成分: {var*100:.2f}%")

    # 载荷矩阵
    print("\n载荷矩阵 (各期限在主成分上的权重):")
    loadings = pd.DataFrame(
        pca.components_.T,
        index=df_pca.columns,
        columns=[f'PC{i+1}' for i in range(len(df_pca.columns))]
    )
    print(loadings.round(4))

    # 保存结果
    output_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(output_dir, exist_ok=True)

    # 绘制图表
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. 方差解释比例
    axes[0, 0].bar(range(1, len(pca.explained_variance_ratio_)+1),
                   pca.explained_variance_ratio_ * 100)
    axes[0, 0].set_title('各主成分解释的方差比例')
    axes[0, 0].set_xlabel('主成分')
    axes[0, 0].set_ylabel('解释方差 (%)')
    axes[0, 0].grid(True, alpha=0.3)

    # 2. 累计方差
    axes[0, 1].plot(range(1, len(cumulative)+1), cumulative * 100, 'o-', linewidth=2)
    axes[0, 1].set_title('累计解释方差')
    axes[0, 1].set_xlabel('主成分数量')
    axes[0, 1].set_ylabel('累计方差 (%)')
    axes[0, 1].grid(True, alpha=0.3)
    axes[0, 1].axhline(y=90, color='r', linestyle='--', alpha=0.5)

    # 3. PC1 载荷
    terms = df_pca.columns
    x_pos = np.arange(len(terms))
    axes[1, 0].bar(x_pos, loadings['PC1'])
    axes[1, 0].set_title('PC1 载荷 (水平因子)')
    axes[1, 0].set_xlabel('期限')
    axes[1, 0].set_ylabel('载荷')
    axes[1, 0].set_xticks(x_pos)
    axes[1, 0].set_xticklabels(terms)
    axes[1, 0].grid(True, alpha=0.3, axis='y')

    # 4. PC2 载荷
    if len(loadings.columns) >= 2:
        axes[1, 1].bar(x_pos, loadings['PC2'])
        axes[1, 1].set_title('PC2 载荷 (斜率因子)')
        axes[1, 1].set_xlabel('期限')
        axes[1, 1].set_ylabel('载荷')
        axes[1, 1].set_xticks(x_pos)
        axes[1, 1].set_xticklabels(terms)
        axes[1, 1].grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    chart_path = os.path.join(output_dir, 'bond_pca_charts.png')
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    print(f"\n图表已保存: {chart_path}")

    # 保存载荷矩阵
    loadings_path = os.path.join(output_dir, 'bond_pca_loadings.csv')
    loadings.to_csv(loadings_path, encoding='utf-8-sig')
    print(f"载荷矩阵已保存: {loadings_path}")

    # 保存主成分时间序列
    pca_ts = pd.DataFrame(
        pca_result[:, :3],
        index=df_pca.index,
        columns=['PC1', 'PC2', 'PC3']
    )
    pca_ts_path = os.path.join(output_dir, 'bond_pca_timeseries.csv')
    pca_ts.to_csv(pca_ts_path, encoding='utf-8-sig')
    print(f"主成分时间序列已保存: {pca_ts_path}")

    # 绘制主成分时间序列图
    fig, ax = plt.subplots(figsize=(12, 6))
    pca_ts.plot(ax=ax)
    ax.set_title('债券收益率主成分时间序列')
    ax.set_ylabel('标准化值')
    ax.grid(True, alpha=0.3)
    ts_chart_path = os.path.join(output_dir, 'bond_pca_timeseries.png')
    plt.savefig(ts_chart_path, dpi=150, bbox_inches='tight')
    print(f"主成分时间序列图已保存: {ts_chart_path}")

    return pca, loadings, pca_ts


def interpret_results(loadings: pd.DataFrame):
    """
    解释 PCA 结果
    
    Args:
        loadings: 载荷矩阵
    """
    print("\n" + "=" * 80)
    print("结果解释")
    print("=" * 80)

    print("\n[收益率曲线 PCA 的经典解释]")
    print("PC1 (水平因子): 所有期限同号 - 平行移动")
    print("PC2 (斜率因子): 短端和长端异号 - 斜率变化")
    print("PC3 (曲率因子): 中端与两端异号 - 曲率变化")

    print("\n[当前结果分析]")
    pc1 = loadings['PC1']
    if all(pc1 > 0) or all(pc1 < 0):
        print("PC1: 水平因子 - 所有期限同号")
    else:
        print("PC1: 非纯水平因子")

    if len(loadings.columns) >= 2:
        pc2 = loadings['PC2']
        if pc2.iloc[0] * pc2.iloc[-1] < 0:
            print("PC2: 斜率因子 - 短端和长端异号")
        else:
            print("PC2: 非纯斜率因子")


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("中国国债收益率 PCA 分析")
    print("=" * 80)

    output_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(output_dir, exist_ok=True)

    # 获取数据
    df_raw = get_bond_data()
    
    # 准备数据
    df_pca = prepare_pca_data(df_raw)
    
    # 执行 PCA 分析
    pca, loadings, pca_ts = perform_pca_analysis(df_pca)
    
    # 解释结果
    interpret_results(loadings)

    print("\n" + "=" * 80)
    print("分析完成！")
    print("=" * 80)


if __name__ == "__main__":
    main()
