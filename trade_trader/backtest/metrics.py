# coding=utf-8
"""
绩效指标计算模块 - Performance Metrics Module

提供回测绩效指标计算功能：
- 总收益率、年化收益率
- 最大回撤
- 夏普比率、索提诺比率、卡玛比率
- 胜率、盈亏比
- 月度收益分布
"""
from typing import List, Tuple, Optional
from datetime import date
import logging

import pandas as pd
import numpy as np


logger = logging.getLogger('PerformanceMetrics')


class PerformanceMetrics:
    """
    绩效指标计算器

    提供各种回测绩效指标的计算方法
    """

    def __init__(self, risk_free_rate: float = 0.03):
        """
        初始化绩效指标计算器

        Args:
            risk_free_rate: 无风险利率 (年化)
        """
        self.risk_free_rate = risk_free_rate

    def total_return(self, equity_curve: pd.Series) -> float:
        """
        计算总收益率

        Args:
            equity_curve: 权益曲线

        Returns:
            float: 总收益率
        """
        if equity_curve.empty or len(equity_curve) < 2:
            return 0.0

        initial_value = equity_curve.iloc[0]
        final_value = equity_curve.iloc[-1]

        if initial_value == 0:
            return 0.0

        return (final_value - initial_value) / initial_value

    def annual_return(
        self,
        equity_curve: pd.Series,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> float:
        """
        计算年化收益率

        Args:
            equity_curve: 权益曲线
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            float: 年化收益率
        """
        if equity_curve.empty or len(equity_curve) < 2:
            return 0.0

        total_ret = self.total_return(equity_curve)

        if start_date and end_date:
            days = (end_date - start_date).days
        elif isinstance(equity_curve.index, pd.DatetimeIndex):
            days = (equity_curve.index[-1] - equity_curve.index[0]).days
        else:
            days = len(equity_curve)

        if days <= 0:
            return 0.0

        years = days / 365.0

        if years == 0:
            return 0.0

        return (1 + total_ret) ** (1 / years) - 1

    def max_drawdown(self, equity_curve: pd.Series) -> Tuple[float, float]:
        """
        计算最大回撤

        Args:
            equity_curve: 权益曲线

        Returns:
            Tuple[float, float]: (最大回撤金额, 最大回撤百分比)
        """
        if equity_curve.empty:
            return 0.0, 0.0

        # 计算累计最高点
        running_max = equity_curve.expanding().max()

        # 计算回撤
        drawdown = equity_curve - running_max
        drawdown_pct = drawdown / running_max

        max_dd = drawdown.min()
        max_dd_pct = drawdown_pct.min()

        return max_dd, max_dd_pct

    def max_drawdown_duration(self, equity_curve: pd.Series) -> int:
        """
        计算最大回撤持续天数

        Args:
            equity_curve: 权益曲线

        Returns:
            int: 最大回撤持续天数
        """
        if equity_curve.empty:
            return 0

        # 计算累计最高点
        running_max = equity_curve.expanding().max()

        # 找到回撤区间
        drawdown = equity_curve < running_max

        # 计算连续回撤的最大天数
        max_duration = 0
        current_duration = 0

        for is_drawdown in drawdown:
            if is_drawdown:
                current_duration += 1
                max_duration = max(max_duration, current_duration)
            else:
                current_duration = 0

        return max_duration

    def sharpe_ratio(
        self,
        equity_curve: pd.Series,
        periods: int = 252
    ) -> float:
        """
        计算夏普比率

        Args:
            equity_curve: 权益曲线
            periods: 年化周期 (默认252个交易日)

        Returns:
            float: 夏普比率
        """
        if equity_curve.empty or len(equity_curve) < 2:
            return 0.0

        # 计算日收益率
        returns = equity_curve.pct_change().dropna()

        if returns.empty or returns.std() == 0:
            return 0.0

        # 计算年化夏普比率
        daily_rf = self.risk_free_rate / 365
        excess_returns = returns - daily_rf

        return np.sqrt(periods) * excess_returns.mean() / returns.std()

    def sortino_ratio(
        self,
        equity_curve: pd.Series,
        periods: int = 252
    ) -> float:
        """
        计算索提诺比率

        Args:
            equity_curve: 权益曲线
            periods: 年化周期 (默认252个交易日)

        Returns:
            float: 索提诺比率
        """
        if equity_curve.empty or len(equity_curve) < 2:
            return 0.0

        # 计算日收益率
        returns = equity_curve.pct_change().dropna()

        if returns.empty:
            return 0.0

        # 计算下行偏差
        daily_rf = self.risk_free_rate / 365
        excess_returns = returns - daily_rf

        downside_returns = excess_returns[excess_returns < 0]

        if downside_returns.empty or downside_returns.std() == 0:
            return 0.0 if excess_returns.mean() <= 0 else float('inf')

        return np.sqrt(periods) * excess_returns.mean() / downside_returns.std()

    def calmar_ratio(
        self,
        equity_curve: pd.Series,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> float:
        """
        计算卡玛比率 (年化收益率 / 最大回撤)

        Args:
            equity_curve: 权益曲线
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            float: 卡玛比率
        """
        ann_ret = self.annual_return(equity_curve, start_date, end_date)
        _, max_dd_pct = self.max_drawdown(equity_curve)

        if max_dd_pct == 0:
            return 0.0 if ann_ret <= 0 else float('inf')

        return abs(ann_ret / max_dd_pct)

    def win_rate(self, trades: List[pd.Series]) -> float:
        """
        计算胜率

        Args:
            trades: 交易列表，每笔交易包含 'profit' 字段

        Returns:
            float: 胜率
        """
        if not trades:
            return 0.0

        winning_trades = sum(1 for t in trades if t.get('profit', 0) > 0)
        return winning_trades / len(trades)

    def profit_factor(self, trades: List[pd.Series]) -> float:
        """
        计算盈亏比

        Args:
            trades: 交易列表，每笔交易包含 'profit' 字段

        Returns:
            float: 盈亏比
        """
        if not trades:
            return 0.0

        gross_profit = sum(t.get('profit', 0) for t in trades if t.get('profit', 0) > 0)
        gross_loss = sum(abs(t.get('profit', 0)) for t in trades if t.get('profit', 0) < 0)

        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    def avg_win_loss(self, trades: List[pd.Series]) -> Tuple[float, float]:
        """
        计算平均盈利和平均亏损

        Args:
            trades: 交易列表，每笔交易包含 'profit' 字段

        Returns:
            Tuple[float, float]: (平均盈利, 平均亏损)
        """
        profits = [t.get('profit', 0) for t in trades if t.get('profit', 0) > 0]
        losses = [abs(t.get('profit', 0)) for t in trades if t.get('profit', 0) < 0]

        avg_profit = np.mean(profits) if profits else 0.0
        avg_loss = np.mean(losses) if losses else 0.0

        return avg_profit, avg_loss

    def monthly_returns(self, equity_curve: pd.Series) -> pd.Series:
        """
        计算月度收益率

        Args:
            equity_curve: 权益曲线 (索引为日期)

        Returns:
            pd.Series: 月度收益率
        """
        if equity_curve.empty or not isinstance(equity_curve.index, pd.DatetimeIndex):
            return pd.Series()

        # 按月重采样，取月末值
        monthly_values = equity_curve.resample('M').last()

        # 计算月度收益率
        monthly_returns = monthly_values.pct_change().dropna()

        return monthly_returns

    def calculate_all_metrics(
        self,
        equity_curve: pd.Series,
        trades: Optional[List[pd.Series]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> dict:
        """
        计算所有绩效指标

        Args:
            equity_curve: 权益曲线
            trades: 交易列表
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            dict: 所有绩效指标
        """
        metrics = {
            'total_return': self.total_return(equity_curve),
            'annual_return': self.annual_return(equity_curve, start_date, end_date),
            'max_drawdown': self.max_drawdown(equity_curve)[1],
            'max_drawdown_duration': self.max_drawdown_duration(equity_curve),
            'sharpe_ratio': self.sharpe_ratio(equity_curve),
            'sortino_ratio': self.sortino_ratio(equity_curve),
            'calmar_ratio': self.calmar_ratio(equity_curve, start_date, end_date),
        }

        if trades:
            metrics.update({
                'total_trades': len(trades),
                'win_rate': self.win_rate(trades),
                'profit_factor': self.profit_factor(trades),
                'avg_win': self.avg_win_loss(trades)[0],
                'avg_loss': self.avg_win_loss(trades)[1],
            })

        return metrics


def calculate_metrics(
    equity_curve: pd.Series,
    trades: Optional[List[pd.Series]] = None,
    risk_free_rate: float = 0.03
) -> dict:
    """
    计算绩效指标的便捷函数

    Args:
        equity_curve: 权益曲线
        trades: 交易列表
        risk_free_rate: 无风险利率

    Returns:
        dict: 所有绩效指标
    """
    calculator = PerformanceMetrics(risk_free_rate)
    return calculator.calculate_all_metrics(equity_curve, trades)
