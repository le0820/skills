#!/usr/bin/env python3
"""
投研数据获取系统 - 基础投研体系
包含三个核心模块：
1. TechnicalData - 技术面价格数据（个股价格、成交量等）
2. FundamentalData - 企业基本面数据（财务报表、估值指标等）
3. MacroData - 宏观数据（宏观经济指标、全球市场价格数据等）

Author: AI Assistant
Date: 2026-03-12
"""

import numpy as np
import pandas as pd
import akshare as ak
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import warnings

warnings.filterwarnings('ignore')
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''


class TechnicalData:
    """
    技术面价格数据类
    负责获取个股价格、成交量等市场交易数据
    """

    def __init__(self):
        self.data_cache = {}

    def get_stock_price(self, symbol: str, start_date: str, end_date: str,
                       exchange: str = "sh") -> Optional[pd.DataFrame]:
        """
        获取A股股价数据

        Parameters:
        -----------
        symbol : str
            股票代码，如 "601899"
        start_date : str
            开始日期，格式 "YYYYMMDD"
        end_date : str
            结束日期，格式 "YYYYMMDD"
        exchange : str
            交易所代码，"sh" 或 "sz"

        Returns:
        --------
        pd.DataFrame
            包含 date, open, high, low, close, volume, symbol 列
        """
        print(f"[TechnicalData] 获取股票 {symbol} 价格数据...")

        try:
            df = ak.stock_zh_a_daily(symbol=f"{exchange}{symbol}",
                                     start_date=start_date,
                                     end_date=end_date)

            df = df.rename(columns={
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume"
            })
        except Exception as e:
            print(f"  使用 stock_zh_a_daily 失败: {e}")
            try:
                df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                       start_date=start_date,
                                       end_date=end_date,
                                       adjust="qfq")

                df = df.rename(columns={
                    "日期": "date",
                    "开盘": "open",
                    "最高": "high",
                    "最低": "low",
                    "收盘": "close",
                    "成交量": "volume"
                })
            except Exception as e2:
                print(f"  使用 stock_zh_a_hist 失败: {e2}")
                return None

        df['date'] = pd.to_datetime(df['date'])
        df['symbol'] = symbol
        df = df[["date", "open", "high", "low", "close", "volume", "symbol"]]

        print(f"  ✓ 获取完成，共 {len(df)} 条记录")
        self.data_cache[f"stock_{symbol}"] = df
        return df

    def get_all_technical_data(self, stock_symbol: str = "601899") -> Dict[str, pd.DataFrame]:
        """
        获取所有技术面数据

        Returns:
        --------
        Dict[str, pd.DataFrame]
            包含所有技术面数据的字典
        """
        print("\n" + "="*60)
        print("开始获取技术面数据")
        print("="*60)

        # 股票数据
        self.get_stock_price(stock_symbol, "20200212", "20250212")

        print("\n" + "="*60)
        print("技术面数据获取完成")
        print("="*60)

        return self.data_cache


class FundamentalData:
    """
    企业基本面数据类
    负责获取企业财务报表、估值指标等数据
    """

    def __init__(self):
        self.data_cache = {}

    def get_financial_abstract(self, symbol: str, start_year: int = 2020,
                               end_year: int = 2025) -> Optional[pd.DataFrame]:
        """
        获取企业财务摘要数据（季度）

        Parameters:
        -----------
        symbol : str
            股票代码
        start_year : int
            开始年份
        end_year : int
            结束年份

        Returns:
        --------
        pd.DataFrame
            包含 report_date, roe, total_revenue, net_profit_parent, eps 等列
        """
        print(f"[FundamentalData] 获取 {symbol} 财务摘要数据...")

        try:
            df = ak.stock_financial_abstract_ths(symbol=symbol, indicator="按单季度")

            df['report_date'] = pd.to_datetime(df['报告期'])
            df = df.sort_values('report_date')
            df = df[df['report_date'].dt.year >= start_year]
            df = df[df['report_date'].dt.year <= end_year]

            result = pd.DataFrame()
            result['report_date'] = df['report_date']
            result['year'] = result['report_date'].dt.year
            result['quarter'] = result['report_date'].dt.quarter

            # 提取关键指标
            if '净资产收益率(%)' in df.columns:
                result['roe'] = pd.to_numeric(df['净资产收益率(%)'], errors='coerce')
            elif '加权净资产收益率(%)' in df.columns:
                result['roe'] = pd.to_numeric(df['加权净资产收益率(%)'], errors='coerce')

            if '营业总收入' in df.columns:
                result['total_revenue'] = pd.to_numeric(df['营业总收入'], errors='coerce')
            elif '营业收入' in df.columns:
                result['total_revenue'] = pd.to_numeric(df['营业收入'], errors='coerce')

            if '归属于母公司所有者的净利润' in df.columns:
                result['net_profit_parent'] = pd.to_numeric(df['归属于母公司所有者的净利润'], errors='coerce')
            elif '净利润' in df.columns:
                result['net_profit_parent'] = pd.to_numeric(df['净利润'], errors='coerce')

            if '基本每股收益' in df.columns:
                result['eps'] = pd.to_numeric(df['基本每股收益'], errors='coerce')

            print(f"  ✓ 获取完成，共 {len(result)} 条记录")
            self.data_cache[f"financial_{symbol}"] = result
            return result

        except Exception as e:
            print(f"  ✗ 获取失败: {e}")
            return None

    def get_financial_analysis(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        获取财务分析指标

        Parameters:
        -----------
        symbol : str
            股票代码

        Returns:
        --------
        pd.DataFrame
            财务分析指标数据
        """
        print(f"[FundamentalData] 获取 {symbol} 财务分析指标...")

        try:
            df = ak.stock_financial_analysis_indicator(symbol=f"sh{symbol}")
            print(f"  ✓ 获取完成，共 {len(df)} 条记录")
            self.data_cache[f"analysis_{symbol}"] = df
            return df

        except Exception as e:
            print(f"  ✗ 获取失败: {e}")
            return None

    def get_all_fundamental_data(self, symbol: str = "601899") -> Dict[str, pd.DataFrame]:
        """
        获取所有基本面数据

        Returns:
        --------
        Dict[str, pd.DataFrame]
            包含所有基本面数据的字典
        """
        print("\n" + "="*60)
        print("开始获取基本面数据")
        print("="*60)

        self.get_financial_abstract(symbol)
        self.get_financial_analysis(symbol)

        print("\n" + "="*60)
        print("基本面数据获取完成")
        print("="*60)

        return self.data_cache


class MacroData:
    """
    宏观数据类
    负责获取宏观经济指标、全球市场价格数据等
    """

    def __init__(self):
        self.data_cache = {}

    def get_cpi(self, country: str = "china") -> Optional[pd.DataFrame]:
        """
        获取CPI数据

        Parameters:
        -----------
        country : str
            国家，"china" 或 "usa"

        Returns:
        --------
        pd.DataFrame
            CPI数据
        """
        print(f"[MacroData] 获取{country.upper()} CPI数据...")

        try:
            if country == "china":
                df = ak.macro_china_cpi()
                df['date'] = pd.to_datetime(df['月份'], format='%Y年%m月份')
                df['cpi_yoy'] = pd.to_numeric(df.get('全国-当月', df.get('全国')), errors='coerce')
            else:
                df = ak.macro_usa_cpi_yoy()
                df['date'] = pd.to_datetime(df['时间'])
                df['cpi_yoy'] = pd.to_numeric(df.get('现值'), errors='coerce')

            df = df.sort_values('date')
            print(f"  ✓ 获取完成，共 {len(df)} 条记录")
            self.data_cache[f"cpi_{country}"] = df
            return df

        except Exception as e:
            print(f"  ✗ 获取失败: {e}")
            return None

    def get_ppi(self) -> Optional[pd.DataFrame]:
        """
        获取中国PPI数据

        Returns:
        --------
        pd.DataFrame
            PPI数据
        """
        print(f"[MacroData] 获取中国PPI数据...")

        try:
            df = ak.macro_china_ppi()
            df['date'] = pd.to_datetime(df['月份'].str.replace('年', '-').str.replace('月份', ''))
            df['ppi_yoy'] = pd.to_numeric(df.get('当月', df.iloc[:, 1]), errors='coerce')
            df = df.sort_values('date')

            print(f"  ✓ 获取完成，共 {len(df)} 条记录")
            self.data_cache["ppi_china"] = df
            return df

        except Exception as e:
            print(f"  ✗ 获取失败: {e}")
            return None

    def get_futures_price(self, symbol: str, name: str = "") -> Optional[pd.DataFrame]:
        """
        获取国际期货价格数据（黄金、原油等）

        Parameters:
        -----------
        symbol : str
            期货代码，如 "GC"(黄金), "OIL"(布伦特原油), "CL"(WTI原油)
        name : str
            数据名称标识

        Returns:
        --------
        pd.DataFrame
            包含 date, open, high, low, close, volume 列
        """
        display_name = name if name else symbol
        print(f"[MacroData] 获取{display_name}期货数据...")

        try:
            df = ak.futures_foreign_hist(symbol=symbol)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            df['symbol'] = symbol

            print(f"  ✓ 获取完成，共 {len(df)} 条记录，时间范围 {df['date'].min().date()} 至 {df['date'].max().date()}")
            cache_key = name if name else f"futures_{symbol}"
            self.data_cache[cache_key] = df
            return df

        except Exception as e:
            print(f"  ✗ 获取失败: {e}")
            return None

    def get_us_bond_yield(self, maturity: str = "10y") -> Optional[pd.DataFrame]:
        """
        获取美国国债收益率

        Parameters:
        -----------
        maturity : str
            期限，"2y" 或 "10y"

        Returns:
        --------
        pd.DataFrame
            包含 date, open, high, low, close, volume 列
        """
        symbol_map = {
            "2y": "美国2年期国债",
            "10y": "美国10年期国债"
        }

        symbol = symbol_map.get(maturity, "美国10年期国债")
        print(f"[MacroData] 获取美债{maturity}收益率...")

        try:
            df = ak.bond_gb_us_sina(symbol=symbol)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            df['maturity'] = maturity

            print(f"  ✓ 获取完成，共 {len(df)} 条记录，时间范围 {df['date'].min().date()} 至 {df['date'].max().date()}")
            self.data_cache[f"us_bond_{maturity}"] = df
            return df

        except Exception as e:
            print(f"  ✗ 获取失败: {e}")
            return None

    def get_usd_index(self) -> Optional[pd.DataFrame]:
        """
        获取美元指数

        Returns:
        --------
        pd.DataFrame
            包含 date, close 等列
        """
        print(f"[MacroData] 获取美元指数...")

        try:
            df = ak.index_global_hist_em(symbol="美元指数")
            df['date'] = pd.to_datetime(df['日期'])
            df = df.sort_values('date')
            df['close'] = df['最新价']

            print(f"  ✓ 获取完成，共 {len(df)} 条记录，时间范围 {df['date'].min().date()} 至 {df['date'].max().date()}")
            self.data_cache["usd_index"] = df
            return df

        except Exception as e:
            print(f"  ✗ 获取失败: {e}")
            return None

    def get_exchange_rate(self, currency_pair: str = "usd_cny") -> Optional[pd.DataFrame]:
        """
        获取汇率数据

        Parameters:
        -----------
        currency_pair : str
            货币对，如 "usd_cny"

        Returns:
        --------
        pd.DataFrame
            包含 date, rate, ma250 列
        """
        print(f"[MacroData] 获取{currency_pair}汇率数据...")

        try:
            df = ak.currency_boc_safe()
            df['date'] = pd.to_datetime(df['日期'])
            df = df.sort_values('date')

            # 提取美元汇率并转换
            result = pd.DataFrame()
            result['date'] = df['date']
            result['rate'] = df['美元'] / 100  # 转换为1美元兑换多少人民币
            result['ma250'] = result['rate'].rolling(window=250).mean()

            print(f"  ✓ 获取完成，共 {len(result)} 条记录，时间范围 {result['date'].min().date()} 至 {result['date'].max().date()}")
            self.data_cache[currency_pair] = result
            return result

        except Exception as e:
            print(f"  ✗ 获取失败: {e}")
            return None

    def get_gold_oil_ratio(self) -> Optional[pd.DataFrame]:
        """
        获取金油比数据（黄金/原油价格比）

        Returns:
        --------
        pd.DataFrame
            包含 date, gold_price, oil_price, gold_oil_ratio 列
        """
        print(f"[MacroData] 计算金油比...")

        gold_df = self.get_futures_price("GC", "gold")
        oil_df = self.get_futures_price("OIL", "brent_oil")

        if gold_df is None or oil_df is None:
            print("  ✗ 获取黄金或原油数据失败")
            return None

        # 合并数据
        merged = pd.merge(
            gold_df[['date', 'close']].rename(columns={'close': 'gold_price'}),
            oil_df[['date', 'close']].rename(columns={'close': 'oil_price'}),
            on='date',
            how='inner'
        )

        merged['gold_oil_ratio'] = merged['gold_price'] / merged['oil_price']

        # 计算统计指标
        stats = {
            'current': merged['gold_oil_ratio'].iloc[-1],
            'mean': merged['gold_oil_ratio'].mean(),
            'median': merged['gold_oil_ratio'].median(),
            'std': merged['gold_oil_ratio'].std(),
            'min': merged['gold_oil_ratio'].min(),
            'max': merged['gold_oil_ratio'].max()
        }

        print(f"  ✓ 金油比计算完成，共 {len(merged)} 条记录")
        print(f"    当前值: {stats['current']:.2f}, 平均值: {stats['mean']:.2f}, 中位数: {stats['median']:.2f}")

        self.data_cache["gold_oil_ratio"] = merged
        return merged

    def get_us_bond_term_premium(self) -> Optional[pd.DataFrame]:
        """
        获取美债期限溢价（10年期 - 2年期收益率）

        Returns:
        --------
        pd.DataFrame
            包含 date, yield_10y, yield_2y, term_premium 列
        """
        print(f"[MacroData] 计算美债期限溢价...")

        bond_10y = self.get_us_bond_yield("10y")
        bond_2y = self.get_us_bond_yield("2y")

        if bond_10y is None or bond_2y is None:
            print("  ✗ 获取美债数据失败")
            return None

        # 合并数据
        merged = pd.merge(
            bond_10y[['date', 'close']].rename(columns={'close': 'yield_10y'}),
            bond_2y[['date', 'close']].rename(columns={'close': 'yield_2y'}),
            on='date',
            how='inner'
        )

        merged['term_premium'] = merged['yield_10y'] - merged['yield_2y']

        print(f"  ✓ 期限溢价计算完成，共 {len(merged)} 条记录")
        print(f"    当前10Y: {merged['yield_10y'].iloc[-1]:.2f}%, 2Y: {merged['yield_2y'].iloc[-1]:.2f}%, 期限溢价: {merged['term_premium'].iloc[-1]:.2f}%")

        self.data_cache["us_bond_term_premium"] = merged
        return merged

    def get_all_macro_data(self) -> Dict[str, pd.DataFrame]:
        """
        获取所有宏观数据

        Returns:
        --------
        Dict[str, pd.DataFrame]
            包含所有宏观数据的字典
        """
        print("\n" + "="*60)
        print("开始获取宏观数据")
        print("="*60)

        # 宏观经济指标
        self.get_cpi("china")
        self.get_cpi("usa")
        self.get_ppi()

        # 全球市场价格数据
        self.get_usd_index()
        self.get_exchange_rate("usd_cny")
        self.get_us_bond_yield("10y")
        self.get_us_bond_yield("2y")

        # 大宗商品价格
        self.get_futures_price("GC", "gold")
        self.get_futures_price("OIL", "brent_oil")

        # 计算衍生指标
        self.get_gold_oil_ratio()
        self.get_us_bond_term_premium()

        print("\n" + "="*60)
        print("宏观数据获取完成")
        print("="*60)

        return self.data_cache


class ResearchDataSystem:
    """
    投研数据系统主类
    整合技术面、基本面、宏观数据三个模块
    """

    def __init__(self):
        self.technical = TechnicalData()
        self.fundamental = FundamentalData()
        self.macro = MacroData()
        self.all_data = {}

    def collect_all_data(self, stock_symbol: str = "601899") -> Dict[str, Dict[str, pd.DataFrame]]:
        """
        收集所有投研数据

        Parameters:
        -----------
        stock_symbol : str
            目标股票代码

        Returns:
        --------
        Dict[str, Dict[str, pd.DataFrame]]
            包含所有分类数据的字典
        """
        print("\n" + "="*70)
        print("投研数据系统 - 开始收集所有数据")
        print("="*70)

        # 技术面数据（个股价格）
        technical_data = self.technical.get_all_technical_data(stock_symbol)

        # 基本面数据
        fundamental_data = self.fundamental.get_all_fundamental_data(stock_symbol)

        # 宏观数据（宏观经济指标 + 全球市场价格）
        macro_data = self.macro.get_all_macro_data()

        self.all_data = {
            "technical": technical_data,
            "fundamental": fundamental_data,
            "macro": macro_data
        }

        print("\n" + "="*70)
        print("投研数据系统 - 所有数据收集完成")
        print("="*70)

        return self.all_data

    def save_all_data(self, output_dir: str = "data"):
        """
        保存所有数据到CSV文件

        Parameters:
        -----------
        output_dir : str
            输出目录
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        print(f"\n[ResearchDataSystem] 保存数据到 {output_dir}/")

        for category, data_dict in self.all_data.items():
            category_dir = os.path.join(output_dir, category)
            if not os.path.exists(category_dir):
                os.makedirs(category_dir)

            for name, df in data_dict.items():
                if df is not None:
                    file_path = os.path.join(category_dir, f"{name}.csv")
                    df.to_csv(file_path, index=False, encoding='utf-8-sig')
                    print(f"  ✓ 保存: {category}/{name}.csv")

        print(f"  所有数据保存完成")

    def get_summary(self) -> str:
        """
        获取数据汇总信息

        Returns:
        --------
        str
            数据汇总报告
        """
        summary = []
        summary.append("\n" + "="*70)
        summary.append("投研数据系统 - 数据汇总")
        summary.append("="*70)

        for category, data_dict in self.all_data.items():
            summary.append(f"\n【{category.upper()}】")
            for name, df in data_dict.items():
                if df is not None:
                    summary.append(f"  {name}: {len(df)} 条记录")
                else:
                    summary.append(f"  {name}: 获取失败")

        summary.append("\n" + "="*70)
        return "\n".join(summary)


# 兼容旧版本的函数接口
def get_stock_data(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """兼容旧接口：获取股票数据"""
    tech = TechnicalData()
    return tech.get_stock_price(symbol, start_date, end_date)


def get_fundamental_data(symbol: str, start_year: int = 2020, end_year: int = 2025) -> Optional[pd.DataFrame]:
    """兼容旧接口：获取基本面数据"""
    fund = FundamentalData()
    return fund.get_financial_abstract(symbol, start_year, end_year)


def get_macro_data(start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    """兼容旧接口：获取宏观数据"""
    macro = MacroData()
    return macro.get_all_macro_data()


def save_data(stock_df, fundamental_df, macro_data, output_dir: str = "data"):
    """兼容旧接口：保存数据"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if stock_df is not None:
        stock_file = os.path.join(output_dir, "stock_price.csv")
        stock_df.to_csv(stock_file, index=False, encoding='utf-8-sig')
        print(f"\n股价数据已保存到 {stock_file}")

    if fundamental_df is not None:
        fundamental_file = os.path.join(output_dir, "fundamental_data.csv")
        fundamental_df.to_csv(fundamental_file, index=False, encoding='utf-8-sig')
        print(f"基本面数据已保存到 {fundamental_file}")

    for key, df in macro_data.items():
        if df is not None:
            macro_file = os.path.join(output_dir, f"{key}.csv")
            df.to_csv(macro_file, index=False, encoding='utf-8-sig')
            print(f"宏观数据 {key} 已保存到 {macro_file}")


def build_merged_dataset(stock_symbol: str = "601899",
                         data_dir: str = "data",
                         save_path: str = None) -> pd.DataFrame:
    """
    构建合并后的数据集：以股票日线数据为主表，合并技术指标和宏观数据

    Parameters:
    -----------
    stock_symbol : str
        股票代码，默认 "601899"
    data_dir : str
        数据根目录，默认 "data"
    save_path : str, optional
        如果提供，将结果保存到该路径

    Returns:
    --------
    pd.DataFrame
        合并后的完整数据集
    """
    print("\n" + "="*70)
    print("开始构建合并数据集")
    print("="*70)

    # 1. 读取主表：股票日线数据（含技术指标）
    stock_path = os.path.join(data_dir, "technical", f"stock_{stock_symbol}.csv")
    if not os.path.exists(stock_path):
        raise FileNotFoundError(f"股票数据文件不存在: {stock_path}")

    main_df = pd.read_csv(stock_path)
    main_df['date'] = pd.to_datetime(main_df['date'])
    print(f"✓ 读取主表: {len(main_df)} 条记录")

    # 2. 提取技术指标（后七列）
    tech_columns = ['MACD', 'MACD_signal', 'MACD_hist', 'RSI', 'BB_upper', 'BB_middle', 'BB_lower']

    # 主表保留：date, open, high, low, close, volume, symbol
    main_cols = ['date', 'open', 'high', 'low', 'close', 'volume', 'symbol']
    result_df = main_df[main_cols].copy()

    # 添加技术指标
    for col in tech_columns:
        if col in main_df.columns:
            result_df[col] = main_df[col]
    print(f"✓ 添加技术指标: {len([c for c in tech_columns if c in main_df.columns])} 列")

    # 3. 读取并合并宏观数据
    macro_dir = os.path.join(data_dir, "macro")
    macro_files = [
        ("cpi_china.csv", "cpi_china", ["date", "cpi_yoy"]),
        ("cpi_usa.csv", "cpi_usa", ["date", "cpi_yoy"]),
        ("ppi_china.csv", "ppi_china", ["date", "ppi_yoy"]),
        ("usd_index.csv", "usd_index", ["date", "close"]),
        ("usd_cny.csv", "usd_cny", ["date", "rate", "ma250"]),
        ("us_bond_10y.csv", "us_bond_10y", ["date", "close"]),
        ("us_bond_2y.csv", "us_bond_2y", ["date", "close"]),
        ("gold.csv", "gold", ["date", "close"]),
        ("brent_oil.csv", "brent_oil", ["date", "close"]),
        ("gold_oil_ratio.csv", "gold_oil_ratio", ["date", "gold_price", "oil_price", "gold_oil_ratio"]),
        ("us_bond_term_premium.csv", "us_bond_term_premium", ["date", "yield_10y", "yield_2y", "term_premium"])
    ]

    for filename, prefix, cols_to_keep in macro_files:
        filepath = os.path.join(macro_dir, filename)
        if os.path.exists(filepath):
            try:
                df = pd.read_csv(filepath)
                df['date'] = pd.to_datetime(df['date'])

                # 只保留存在的列
                available_cols = [c for c in cols_to_keep if c in df.columns]
                df = df[available_cols].copy()

                # 重命名列，添加前缀避免冲突
                rename_map = {}
                for col in df.columns:
                    if col != 'date':
                        rename_map[col] = f"{prefix}_{col}"
                df = df.rename(columns=rename_map)

                # 合并
                result_df = pd.merge(result_df, df, on='date', how='left')
                print(f"✓ 合并宏观数据: {prefix}")
            except Exception as e:
                print(f"✗ 合并 {prefix} 失败: {e}")

    # 4. 向前填充缺失值
    result_df = result_df.sort_values('date').reset_index(drop=True)
    result_df = result_df.ffill()
    print("✓ 向前填充缺失值完成")

    print("\n" + "="*70)
    print(f"合并数据集构建完成: {len(result_df)} 行 × {len(result_df.columns)} 列")
    print(f"列名: {list(result_df.columns)}")
    print("="*70)

    # 保存文件（如果指定了路径）
    if save_path:
        result_df.to_csv(save_path, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存到: {save_path}")

    return result_df


def main():
    """
    主函数 - 演示新投研数据系统的使用
    """
    # 创建投研数据系统实例
    research_system = ResearchDataSystem()

    # 收集所有数据
    all_data = research_system.collect_all_data(stock_symbol="601899")

    # 打印数据汇总
    print(research_system.get_summary())

    # 保存所有数据
    research_system.save_all_data(output_dir="data")

    # 示例：访问特定数据
    print("\n" + "="*70)
    print("数据访问示例")
    print("="*70)

    # 宏观数据示例
    if "gold_oil_ratio" in research_system.macro.data_cache:
        gold_oil = research_system.macro.data_cache["gold_oil_ratio"]
        print(f"\n金油比最新数据:")
        print(gold_oil.tail(3))

    # 美债期限溢价示例
    if "us_bond_term_premium" in research_system.macro.data_cache:
        term_premium = research_system.macro.data_cache["us_bond_term_premium"]
        print(f"\n美债期限溢价最新数据:")
        print(term_premium.tail(3))

    print("\n" + "="*70)
    print("投研数据系统运行完成")
    print("="*70)


if __name__ == "__main__":
    main()
