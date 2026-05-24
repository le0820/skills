import numpy as np
import pandas as pd
import akshare as ak
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import warnings
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

    def get_china_bond_yield(self, maturity: str = "10y") -> Optional[pd.DataFrame]:
        """
        获取中国国债收益率

        Parameters:
        -----------
        maturity : str
            期限，"10y" 或 "30y"

        Returns:
        --------
        pd.DataFrame
            包含 date, 收益率 列
        """
        symbol_map = {
            "10y": "中国10年期国债",
            "30y": "中国30年期国债"
        }

        symbol = symbol_map.get(maturity, "中国10年期国债")
        print(f"[MacroData] 获取{symbol}收益率...")

        try:
            df = ak.bond_china_sse_deal()
            # 过滤对应品种
            df = df[df['name'].str.contains(symbol.split()[1], na=False)].copy()
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            df['yield'] = pd.to_numeric(df['price'], errors='coerce')  # 这里价格就是收益率百分比

            print(f"  ✓ 获取完成，共 {len(df)} 条记录，时间范围 {df['date'].min().date()} 至 {df['date'].max().date()}")
            self.data_cache[f"china_bond_{maturity}"] = df
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
            包含 date, close 收益率列
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
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
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
            df['close'] = pd.to_numeric(df['最新价'], errors='coerce')

            print(f"  ✓ 获取完成，共 {len(df)} 条记录，时间范围 {df['date'].min().date()} 至 {df['date'].max().date()}")
            self.data_cache["usd_index"] = df
            return df

        except Exception as e:
            print(f"  ✗ 获取失败: {e}")
            return None

    def get_exchange_rate(self, currency_pair: str = "usd_cnh") -> Optional[pd.DataFrame]:
        """
        获取汇率数据，默认离岸人民币对美元

        Parameters:
        -----------
        currency_pair : str
            货币对，如 "usd_cnh" (离岸人民币对美元)

        Returns:
        --------
        pd.DataFrame
            包含 date, rate 列，rate 为 1美元兑换多少离岸人民币
        """
        print(f"[MacroData] 获取{currency_pair}汇率数据...")

        try:
            # 获取所有汇率
            df = ak.currency_boc_safe()
            df['date'] = pd.to_datetime(df['日期'])
            df = df.sort_values('date')

            # 这里使用akshare的离岸人民币汇率，如果没有则近似用在岸汇率
            # 补充获取离岸人民币汇率
            if currency_pair == "usd_cnh":
                cnh_df = ak.currency_exchange_usd_cnh()
                cnh_df['date'] = pd.to_datetime(cnh_df['date'])
                cnh_df = cnh_df.sort_values('date')
                result = pd.DataFrame()
                result['date'] = cnh_df['date']
                result['rate'] = pd.to_numeric(cnh_df['收盘'], errors='coerce')
            else:
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

    def get_all_required_macro_data(self) -> Dict[str, pd.DataFrame]:
        """
        获取所有你要求的核心宏观数据，包括:
        - CPI (中国)
        - PPI (中国)
        - 10年期中国国债收益率
        - 30年期中国国债收益率
        - 离岸人民币对美元汇率 (usd_cnh)
        - 美元指数
        - 2年期美债收益率
        - 10年期美债收益率

        Returns:
        --------
        Dict[str, pd.DataFrame]
            包含所有宏观数据的字典
        """
        print("\n" + "="*60)
        print("开始获取核心宏观数据")
        print("="*60)

        # 核心需求指标
        self.get_cpi("china")
        self.get_ppi()
        
        # 中国国债收益率
        self.get_china_bond_yield("10y")
        self.get_china_bond_yield("30y")

        # 全球汇率和指数
        self.get_usd_index()
        self.get_exchange_rate("usd_cnh")
        
        # 美债收益率
        self.get_us_bond_yield("10y")
        self.get_us_bond_yield("2y")

        print("\n" + "="*60)
        print("核心宏观数据获取完成")
        print("="*60)

        return self.data_cache

    def get_all_macro_data(self) -> Dict[str, pd.DataFrame]:
        """
        获取所有宏观数据（包括扩展）

        Returns:
        --------
        Dict[str, pd.DataFrame]
            包含所有宏观数据的字典
        """
        print("\n" + "="*60)
        print("开始获取所有宏观数据")
        print("="*60)

        # 宏观经济指标
        self.get_cpi("china")
        self.get_cpi("usa")
        self.get_ppi()

        # 中国国债
        self.get_china_bond_yield("10y")
        self.get_china_bond_yield("30y")

        # 全球市场价格数据
        self.get_usd_index()
        self.get_exchange_rate("usd_cnh")
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
