#!/usr/bin/env python3
"""
Run Backtest Comparison - Parameter Optimization and Equity Curve Comparison
With T+1 / T+0 automatic detection based on symbol
Enhanced analysis and visualization based on akquant documentation
"""
import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import gridspec

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from akquant import Strategy, Bar, run_backtest
from tickflow import TickFlow


# Symbol config: define which symbols use T+1 (A-share ETFs)
T1_SYMBOLS = {
    "159682": True,   # 创业板50ETF
    "513130": False,   # 恒生科技ETF
    "510300": True,   # 沪深300ETF
    "159967": True,   # 创成长ETF
}


def is_t1_symbol(symbol):
    """Check if symbol uses T+1 trading rule"""
    return T1_SYMBOLS.get(symbol, False)


class MomentumStrategy(Strategy):
    """
    Momentum Strategy with configurable lookback period
    Supports both T+0 and T+1 markets
    """
    def __init__(self, lookback_period=20):
        self.lookback_period = lookback_period
        self.warmup_period = lookback_period + 5

    def on_bar(self, bar: Bar):
        hist = self.get_history(count=self.lookback_period + 1, field="close", symbol=bar.symbol)
        if len(hist) < self.lookback_period + 1:
            return
        current_close = hist[-1]
        past_close = hist[0]
        position = self.get_position(bar.symbol)
        if current_close > past_close:
            if position == 0:
                self.buy(bar.symbol, 100000)
        elif current_close < past_close:
            if position > 0:
                self.close_position(bar.symbol)


def get_data(symbol="159682", tickflow_symbol="159682.SZ",
             start_date="2024-01-01", api_key="tk_79be48bd8f2144f294041db3f28a7ade"):
    """Fetch and prepare data"""
    print(f"Fetching data for {symbol}...")
    tf = TickFlow(api_key=api_key)
    df_tf = tf.klines.get(tickflow_symbol, count=1200, as_dataframe=True)
    df_tf['date'] = pd.to_datetime(df_tf['trade_date'])
    df_tf['symbol'] = symbol
    df = df_tf[["date", "open", "high", "low", "close", "volume", "symbol"]].copy()
    df = df.sort_values('date').reset_index(drop=True)
    if start_date:
        df = df[df['date'] >= pd.to_datetime(start_date)].reset_index(drop=True)
    print(f"  Data ready: {len(df)} records from {df['date'].min().date()} to {df['date'].max().date()}")
    return df


def calculate_strategy_stats(result, initial_cash=100000.0):
    """Calculate comprehensive strategy statistics"""
    end_value = result.metrics.end_market_value
    total_return = (end_value - initial_cash) / initial_cash * 100

    stats = {
        'end_value': end_value,
        'total_return': total_return,
        'sharpe': result.metrics.sharpe_ratio,
        'max_drawdown': result.metrics.max_drawdown_pct,
    }

    # Add optional metrics if available
    for attr in ['win_rate', 'trade_count', 'annualized_return', 'volatility', 'sortino_ratio', 'calmar_ratio']:
        if hasattr(result.metrics, attr):
            key = attr.replace('annualized_return', 'annual_return').replace('sortino_ratio', 'sortino').replace('calmar_ratio', 'calmar')
            value = getattr(result.metrics, attr)
            if 'return' in key or 'volatility' in key:
                value = value * 100  # Convert to percentage
            stats[key] = value

    return stats


def run_momentum_optimization(df, initial_cash=100000.0):
    """Run momentum strategy with different lookback periods"""
    print("\n" + "="*80)
    print("MOMENTUM STRATEGY OPTIMIZATION")
    print("="*80)

    symbol = df['symbol'].iloc[0]
    use_t1 = is_t1_symbol(symbol)
    print(f"\nSymbol: {symbol}, T+1: {use_t1}")

    periods = [5, 20, 60, 120]
    results = []

    for period in periods:
        print(f"\nRunning momentum {period}D...")

        class MomentumStrategyFixed(MomentumStrategy):
            def __init__(self):
                super().__init__(lookback_period=period)

        run_kwargs = {
            'strategy': MomentumStrategyFixed,
            'data': df,
            'initial_cash': initial_cash,
        }

        if use_t1:
            run_kwargs.update({
                't_plus_one': True,
                'commission_rate': 0.0003,
                'stamp_tax_rate': 0.001,
            })

        result = run_backtest(**run_kwargs)
        stats = calculate_strategy_stats(result, initial_cash)

        results.append({
            'name': f'Momentum {period}D',
            'period': period,
            'result': result,
            **stats
        })

        t1_tag = " (T+1)" if use_t1 else ""
        print(f"  End Value: {stats['end_value']:.2f}, Return: {stats['total_return']:.2f}%, "
              f"Sharpe: {stats['sharpe']:.2f}, MaxDD: {stats['max_drawdown']:.2f}%{t1_tag}")

    # Print detailed summary table
    print("\n" + "="*80)
    print(f"MOMENTUM STRATEGY SUMMARY (Symbol: {symbol}, T+1: {use_t1})")
    print("="*80)

    # Build header based on available stats
    headers = ['Period', 'Return', 'Annual', 'Sharpe', 'Sortino', 'MaxDD', 'Trades', 'WinRate']
    print(f"{headers[0]:<10} {headers[1]:<12} {headers[2]:<12} {headers[3]:<10} {headers[4]:<10} {headers[5]:<12} {headers[6]:<10} {headers[7]:<10}")
    print("-"*86)

    for r in results:
        annual = f"{r.get('annual_return', 0):.2f}%" if r.get('annual_return') is not None else "-"
        sortino = f"{r.get('sortino', 0):.2f}" if r.get('sortino') is not None else "-"
        trades = f"{int(r['trade_count'])}" if r.get('trade_count') is not None else "-"
        winrate = f"{r.get('win_rate', 0):.2f}%" if r.get('win_rate') is not None else "-"
        print(f"{r['period']:<10} {r['total_return']:<12.2f}% {annual:<12} {r['sharpe']:<10.2f} {sortino:<10} {r['max_drawdown']:<12.2f}% {trades:<10} {winrate:<10}")

    return results


def plot_comprehensive_analysis(results_list, df, output_dir):
    """Plot comprehensive analysis charts"""
    print("\nGenerating comprehensive analysis charts...")

    symbol = df['symbol'].iloc[0]
    use_t1 = is_t1_symbol(symbol)
    t1_tag = " (T+1)" if use_t1 else ""

    # Create figure with grid layout
    fig = plt.figure(figsize=(16, 12))
    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.35, wspace=0.3)

    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']
    strategy_names = [r['name'] for r in results_list]

    # 1. Equity Curve Comparison
    ax1 = fig.add_subplot(gs[0, :])
    for idx, strategy_data in enumerate(results_list):
        name = strategy_data['name']
        result = strategy_data['result']
        if hasattr(result, 'equity_curve'):
            equity_curve = result.equity_curve
            ax1.plot(equity_curve.index, equity_curve.values,
                    label=name, linewidth=2, color=colors[idx % len(colors)])
    ax1.set_title(f'Equity Curve Comparison - {symbol}{t1_tag}', fontsize=14, fontweight='bold')
    ax1.set_ylabel('Equity', fontsize=11)
    ax1.legend(fontsize=10, loc='best')
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(axis='x', rotation=30)

    # 2. Return Comparison Bar Chart
    ax2 = fig.add_subplot(gs[1, 0])
    returns = [r['total_return'] for r in results_list]
    bars = ax2.bar(strategy_names, returns, color=colors[:len(returns)], alpha=0.7)
    ax2.set_title('Total Return Comparison', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Return (%)', fontsize=10)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax2.tick_params(axis='x', rotation=30)
    for bar, ret in zip(bars, returns):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{ret:.1f}%', ha='center', va='bottom' if height>0 else 'top', fontsize=9)

    # 3. Sharpe & Sortino Ratio Comparison
    ax3 = fig.add_subplot(gs[1, 1])
    x = np.arange(len(strategy_names))
    width = 0.35
    sharpes = [r['sharpe'] for r in results_list]
    sortinos = [r.get('sortino', 0) if r.get('sortino') is not None else 0 for r in results_list]
    bars1 = ax3.bar(x - width/2, sharpes, width, label='Sharpe', alpha=0.7, color=colors[0])
    bars2 = ax3.bar(x + width/2, sortinos, width, label='Sortino', alpha=0.7, color=colors[1])
    ax3.set_title('Risk-Adjusted Returns', fontsize=12, fontweight='bold')
    ax3.set_ylabel('Ratio', fontsize=10)
    ax3.set_xticks(x)
    ax3.set_xticklabels(strategy_names, rotation=30)
    ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax3.legend(fontsize=9)

    # 4. Max Drawdown Comparison
    ax4 = fig.add_subplot(gs[2, 0])
    drawdowns = [r['max_drawdown'] for r in results_list]
    bars = ax4.bar(strategy_names, drawdowns, color=colors[:len(drawdowns)], alpha=0.7)
    ax4.set_title('Max Drawdown Comparison', fontsize=12, fontweight='bold')
    ax4.set_ylabel('Max Drawdown (%)', fontsize=10)
    ax4.tick_params(axis='x', rotation=30)
    for bar, dd in zip(bars, drawdowns):
        height = bar.get_height()
        ax4.text(bar.get_x() + bar.get_width()/2., height,
                f'{dd:.1f}%', ha='center', va='top', fontsize=9)

    # 5. Risk-Return Scatter Plot
    ax5 = fig.add_subplot(gs[2, 1])
    for idx, r in enumerate(results_list):
        ax5.scatter(r['max_drawdown'], r['total_return'],
                    s=200, color=colors[idx % len(colors)], alpha=0.7, label=r['name'])
        ax5.annotate(r['name'], (r['max_drawdown'], r['total_return']),
                    xytext=(5, 5), textcoords='offset points', fontsize=9)
    ax5.set_title('Risk-Return Profile', fontsize=12, fontweight='bold')
    ax5.set_xlabel('Max Drawdown (%)', fontsize=10)
    ax5.set_ylabel('Total Return (%)', fontsize=10)
    ax5.grid(True, alpha=0.3)
    ax5.legend(fontsize=8, loc='best')

    chart_path = os.path.join(output_dir, 'comprehensive_analysis.png')
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    print(f"Comprehensive analysis chart saved: {chart_path}")

    # Also save individual equity curve chart
    fig2, ax = plt.subplots(figsize=(14, 7))
    for idx, strategy_data in enumerate(results_list):
        name = strategy_data['name']
        result = strategy_data['result']
        if hasattr(result, 'equity_curve'):
            equity_curve = result.equity_curve
            ax.plot(equity_curve.index, equity_curve.values,
                    label=name, linewidth=2, color=colors[idx % len(colors)])
    ax.set_title(f'Equity Curve Comparison - {symbol}{t1_tag}', fontsize=14, fontweight='bold')
    ax.set_xlabel('Date', fontsize=11)
    ax.set_ylabel('Equity', fontsize=11)
    ax.legend(fontsize=10, loc='best')
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    equity_path = os.path.join(output_dir, 'equity_curve_comparison.png')
    plt.savefig(equity_path, dpi=150, bbox_inches='tight')
    print(f"Equity curve chart saved: {equity_path}")

    return chart_path, equity_path


def main():
    print("\n" + "="*80)
    print("STRATEGY BACKTEST COMPARISON - ENHANCED ANALYSIS")
    print("="*80)

    output_dir = os.path.dirname(os.path.abspath(__file__))

    df = get_data(
        symbol="159967",
        tickflow_symbol="159967.SZ",
        start_date="2020-01-01"
    )

    momentum_results = run_momentum_optimization(df)
    all_results = momentum_results
    plot_comprehensive_analysis(all_results, df, output_dir)

    print("\n" + "="*80)
    print("BACKTEST COMPLETE!")
    print("="*80)


if __name__ == "__main__":
    main()
