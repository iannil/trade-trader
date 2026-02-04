# coding=utf-8
"""
策略组合模块 - Strategy Portfolio Module

提供策略组合功能：
- 信号组合
- 风险平价
- 等权重分配
- 动态权重调整
"""
from typing import Dict, List, Optional
from decimal import Decimal
import logging
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

import numpy as np
from django.db.models import Sum

from panel.models import (
    StrategyInstance, Trade, Position
)


logger = logging.getLogger('StrategyPortfolio')


class WeightMethod(Enum):
    """权重分配方法"""
    EQUAL_WEIGHT = "equal_weight"       # 等权重
    RISK_PARITY = "risk_parity"         # 风险平价
    INVERSE_VOLATILITY = "inverse_vol"  # 反波动率
    EQUAL_MARGINAL = "equal_marginal"   # 等边际贡献
    CUSTOM = "custom"                   # 自定义权重


@dataclass
class PortfolioSignal:
    """组合信号"""
    code: str
    signals: Dict[int, Dict]  # {instance_id: signal_dict}
    combined_signal: int      # -1, 0, 1 (卖空, 无信号, 买入)
    combined_confidence: float  # 0-1
    voting_result: Dict[str, int]  # {'buy': N, 'sell': M}


class StrategyPortfolio:
    """
    策略组合

    功能：
    1. 组合多个策略的信号
    2. 分配资金权重
    3. 计算组合风险
    4. 动态调整权重
    """

    def __init__(self, instances: List[StrategyInstance]):
        """
        初始化策略组合

        Args:
            instances: 策略实例列表
        """
        self.instances = instances
        self.instance_ids = [inst.id for inst in instances]
        self.weights: Dict[int, Decimal] = {}  # instance_id -> weight
        self.weight_method = WeightMethod.EQUAL_WEIGHT
        self.signals_cache: Dict[str, PortfolioSignal] = {}

        # 初始化等权重
        self._init_equal_weights()

    def _init_equal_weights(self):
        """初始化等权重分配"""
        if self.instances:
            weight = Decimal('1') / len(self.instances)
            for inst in self.instances:
                self.weights[inst.id] = weight

    def set_weights(self, weights: Dict[int, Decimal], method: WeightMethod = WeightMethod.CUSTOM):
        """
        设置策略权重

        Args:
            weights: {instance_id: weight}
            method: 权重方法
        """
        total = sum(weights.values())
        if abs(total - Decimal('1')) > Decimal('0.01'):
            logger.warning(f"权重总和不为1: {total}, 进行归一化")
            weights = {k: v / total for k, v in weights.items()}

        self.weights = weights
        self.weight_method = method
        logger.info(f"设置权重: method={method.value}, weights={weights}")

    def calculate_equal_weights(self) -> Dict[int, Decimal]:
        """
        计算等权重

        Returns:
            Dict[int, Decimal]: {instance_id: weight}
        """
        n = len(self.instances)
        if n == 0:
            return {}
        weight = Decimal('1') / n
        return {inst.id: weight for inst in self.instances}

    def calculate_risk_parity_weights(
        self,
        lookback: int = 60
    ) -> Dict[int, Decimal]:
        """
        计算风险平价权重

        Args:
            lookback: 历史数据回看期 (天数)

        Returns:
            Dict[int, Decimal]: {instance_id: weight}
        """
        # 获取各策略的历史收益率
        returns = {}
        for inst in self.instances:
            trades = Trade.objects.filter(
                strategy=inst.strategy,
                close_time__isnull=False
            ).order_by('-close_time')[:lookback]

            if trades.count() < 10:
                logger.warning(f"策略 {inst.name} 历史数据不足")
                returns[inst.id] = np.array([])
                continue

            # 计算日收益率
            profits = [float(t.profit) for t in trades if t.profit]
            returns[inst.id] = np.array(profits)

        # 计算波动率
        volatilities = {}
        for inst_id, ret in returns.items():
            if len(ret) > 0:
                volatilities[inst_id] = np.std(ret) if np.std(ret) > 0 else 1
            else:
                volatilities[inst_id] = 1

        # 反比权重
        inv_vols = {k: 1 / v for k, v in volatilities.items()}
        total_inv_vol = sum(inv_vols.values())

        if total_inv_vol == 0:
            return self.calculate_equal_weights()

        weights = {k: Decimal(str(v / total_inv_vol)) for k, v in inv_vols.items()}
        return weights

    def calculate_inverse_volatility_weights(
        self,
        lookback: int = 60
    ) -> Dict[int, Decimal]:
        """
        计算反波动率权重

        Args:
            lookback: 历史数据回看期 (天数)

        Returns:
            Dict[int, Decimal]: {instance_id: weight}
        """
        return self.calculate_risk_parity_weights(lookback)

    def rebalance_weights(
        self,
        method: WeightMethod,
        lookback: int = 60
    ):
        """
        重新平衡权重

        Args:
            method: 权重方法
            lookback: 历史数据回看期
        """
        if method == WeightMethod.EQUAL_WEIGHT:
            weights = self.calculate_equal_weights()
        elif method == WeightMethod.RISK_PARITY:
            weights = self.calculate_risk_parity_weights(lookback)
        elif method == WeightMethod.INVERSE_VOLATILITY:
            weights = self.calculate_inverse_volatility_weights(lookback)
        else:
            logger.warning(f"未知权重方法: {method}, 使用等权重")
            weights = self.calculate_equal_weights()

        self.set_weights(weights, method)

    def combine_signals(
        self,
        signals: Dict[int, Dict],
        method: str = "voting"
    ) -> Dict[str, PortfolioSignal]:
        """
        组合多个策略的信号

        Args:
            signals: {instance_id: signal_dict}
                signal_dict 格式: {'code': 'cu2501', 'type': SignalType, 'price': Decimal, 'volume': int}
            method: 组合方法
                - voting: 投票法 (多数同意)
                - weighted: 加权投票
                - unanimous: 全票通过
                - priority: 优先级法

        Returns:
            Dict[str, PortfolioSignal]: {code: combined_signal}
        """
        combined = {}

        # 按合约分组
        by_code = {}
        for inst_id, sig in signals.items():
            code = sig.get('code', '')
            if code:
                if code not in by_code:
                    by_code[code] = {}
                by_code[code][inst_id] = sig

        # 对每个合约组合信号
        for code, sigs in by_code.items():
            portfolio_signal = self._combine_single_code(sigs, method)
            combined[code] = portfolio_signal

        self.signals_cache = combined
        return combined

    def _combine_single_code(
        self,
        signals: Dict[int, Dict],
        method: str
    ) -> PortfolioSignal:
        """组合单个合约的信号"""
        buy_votes = 0
        sell_votes = 0
        weighted_buy = Decimal('0')
        weighted_sell = Decimal('0')

        for inst_id, sig in signals.items():
            weight = self.weights.get(inst_id, Decimal('0'))
            sig_type = sig.get('type')

            if sig_type in ['BUY', 'ROLL_OPEN']:
                buy_votes += 1
                weighted_buy += weight
            elif sig_type in ['SELL', 'BUY_COVER', 'ROLL_CLOSE']:
                sell_votes += 1
                weighted_sell += weight

        # 投票结果
        voting_result = {'buy': buy_votes, 'sell': sell_votes}

        # 组合信号
        if method == "voting":
            # 简单多数投票
            if buy_votes > sell_votes:
                combined = 1
            elif sell_votes > buy_votes:
                combined = -1
            else:
                combined = 0
            confidence = abs(buy_votes - sell_votes) / len(signals) if signals else 0

        elif method == "weighted":
            # 加权投票
            if weighted_buy > weighted_sell:
                combined = 1
                confidence = float(weighted_buy / (weighted_buy + weighted_sell)) if (weighted_buy + weighted_sell) > 0 else 0
            elif weighted_sell > weighted_buy:
                combined = -1
                confidence = float(weighted_sell / (weighted_buy + weighted_sell)) if (weighted_buy + weighted_sell) > 0 else 0
            else:
                combined = 0
                confidence = 0

        elif method == "unanimous":
            # 全票通过
            all_buy = buy_votes == len(signals)
            all_sell = sell_votes == len(signals)
            if all_buy:
                combined = 1
                confidence = 1.0
            elif all_sell:
                combined = -1
                confidence = 1.0
            else:
                combined = 0
                confidence = 0

        elif method == "priority":
            # 按权重最高的策略决定
            max_weight_inst = max(self.weights.items(), key=lambda x: x[1])[0]
            max_weight_sig = signals.get(max_weight_inst, {})
            sig_type = max_weight_sig.get('type')

            if sig_type in ['BUY', 'ROLL_OPEN']:
                combined = 1
                confidence = float(self.weights.get(max_weight_inst, 0))
            elif sig_type in ['SELL', 'BUY_COVER', 'ROLL_CLOSE']:
                combined = -1
                confidence = float(self.weights.get(max_weight_inst, 0))
            else:
                combined = 0
                confidence = 0

        else:
            combined = 0
            confidence = 0

        return PortfolioSignal(
            code=next(iter(signals.values())).get('code', ''),
            signals=signals,
            combined_signal=combined,
            combined_confidence=confidence,
            voting_result=voting_result
        )

    def get_portfolio_pnl(
        self,
        start_date: Optional[datetime.date] = None,
        end_date: Optional[datetime.date] = None
    ) -> Dict[str, float]:
        """
        计算组合盈亏

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            Dict: 组合盈亏统计
        """
        total_profit = Decimal('0')
        total_volume = 0
        profit_by_strategy = {}
        profit_by_code = {}

        for inst in self.instances:
            trades = Trade.objects.filter(
                strategy=inst.strategy,
                broker__id=inst.broker.id
            )

            if start_date:
                trades = trades.filter(close_time__date__gte=start_date)
            if end_date:
                trades = trades.filter(close_time__date__lte=end_date)

            strategy_profit = trades.aggregate(Sum('profit'))['profit__sum'] or Decimal('0')
            total_profit += strategy_profit
            profit_by_strategy[inst.name] = float(strategy_profit)

            # 按合约统计
            for trade in trades:
                code = trade.code or trade.instrument.product_code
                if code not in profit_by_code:
                    profit_by_code[code] = Decimal('0')
                if trade.profit:
                    profit_by_code[code] += trade.profit
                total_volume += trade.shares or 0

        return {
            'total_profit': float(total_profit),
            'profit_by_strategy': profit_by_strategy,
            'profit_by_code': {k: float(v) for k, v in profit_by_code.items()},
            'total_volume': total_volume,
            'num_strategies': len(self.instances),
        }

    def get_portfolio_risk(self) -> Dict[str, float]:
        """
        计算组合风险

        Returns:
            Dict: 风险指标
        """
        # 计算各策略的波动率
        volatilities = {}
        for inst in self.instances:
            trades = Trade.objects.filter(
                strategy=inst.strategy,
                close_time__isnull=False
            ).order_by('-close_time')[:60]

            profits = [float(t.profit) for t in trades if t.profit]
            if len(profits) > 10:
                volatilities[inst.name] = np.std(profits)
            else:
                volatilities[inst.name] = 0

        # 计算加权波动率
        weighted_vol = 0
        for inst_id, weight in self.weights.items():
            inst = next((i for i in self.instances if i.id == inst_id), None)
            if inst:
                vol = volatilities.get(inst.name, 0)
                weighted_vol += (float(weight) * vol) ** 2

        portfolio_vol = np.sqrt(weighted_vol) if weighted_vol > 0 else 0

        return {
            'portfolio_volatility': portfolio_vol,
            'strategy_volatilities': {k: float(v) for k, v in volatilities.items()},
            'volatility_contribution': {},  # TODO: 计算各策略的波动率贡献
        }

    def get_current_positions(self) -> Dict[str, Dict]:
        """
        获取当前组合持仓

        Returns:
            Dict: {code: {position_info}}
        """
        positions = {}
        total_long = 0
        total_short = 0

        for inst in self.instances:
            strategy_positions = Position.objects.filter(
                strategy=inst.strategy,
                position__gt=0
            )

            for pos in strategy_positions:
                code = pos.code or pos.instrument.product_code
                if code not in positions:
                    positions[code] = {
                        'long': 0,
                        'short': 0,
                        'net': 0,
                        'strategies': []
                    }

                weight = self.weights.get(inst.id, Decimal('0'))
                if pos.direction == '0':  # LONG
                    positions[code]['long'] += pos.position
                    total_long += pos.position * float(weight)
                else:  # SHORT
                    positions[code]['short'] += pos.position
                    total_short += pos.position * float(weight)

                positions[code]['net'] = positions[code]['long'] - positions[code]['short']
                positions[code]['strategies'].append(inst.name)

        return {
            'positions': positions,
            'total_long': total_long,
            'total_short': total_short,
            'net_exposure': total_long - total_short,
        }


def create_portfolio(instances: List[StrategyInstance]) -> StrategyPortfolio:
    """
    创建策略组合的工厂函数

    Args:
        instances: 策略实例列表

    Returns:
        StrategyPortfolio: 策略组合实例
    """
    return StrategyPortfolio(instances)
