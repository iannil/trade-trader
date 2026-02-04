# coding=utf-8
"""
策略管理器模块 - Strategy Manager Module

提供多策略并行运行和统一管理功能：
- StrategyManager: 策略管理器主类
- 策略注册、启动、停止
- 资金分配
- 策略隔离
"""
from typing import Dict, List, Optional
from decimal import Decimal
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass, field

from django.utils import timezone
from django.db.models import Sum

from panel.models import (
    Strategy, StrategyInstance, Broker, Account, Trade,
)
from trade_trader.strategy import BaseModule
from trade_trader.strategy.brother2 import TradeStrategy


logger = logging.getLogger('StrategyManager')


@dataclass
class StrategyConfig:
    """策略配置"""
    strategy_id: int
    name: str
    broker_id: int
    instruments: List[str] = field(default_factory=list)
    allocated_capital: Decimal = Decimal('0')
    capital_ratio: Decimal = Decimal('1')
    parameters: Dict = field(default_factory=dict)
    enabled: bool = True


@dataclass
class StrategyStatus:
    """策略状态"""
    instance_id: int
    name: str
    status: str  # running, stopped, paused, error
    allocated_capital: Decimal
    current_capital: Decimal
    total_profit: Decimal
    total_trades: int
    start_time: Optional[datetime] = None
    last_signal_time: Optional[datetime] = None
    error_message: str = ""


class StrategyManager:
    """
    策略管理器

    功能：
    1. 注册策略
    2. 启动/停止策略
    3. 分配资金
    4. 监控策略状态
    5. 策略隔离
    """

    def __init__(self, broker: Broker):
        """
        初始化策略管理器

        Args:
            broker: 券商/账户对象
        """
        self.broker = broker
        self.strategies: Dict[int, BaseModule] = {}  # instance_id -> strategy instance
        self.configs: Dict[int, StrategyConfig] = {}  # instance_id -> config
        self.status: Dict[int, StrategyStatus] = {}  # instance_id -> status
        self.total_capital: Decimal = Decimal('0')

        # 加载现有策略实例
        self._load_instances()

    def _load_instances(self):
        """从数据库加载现有策略实例"""
        instances = StrategyInstance.objects.filter(broker=self.broker, is_active=True)
        for inst in instances:
            config = StrategyConfig(
                strategy_id=inst.strategy.id,
                name=inst.name,
                broker_id=self.broker.id,
                instruments=list(inst.strategy.instruments.values_list('product_code', flat=True)),
                allocated_capital=inst.allocated_capital,
                capital_ratio=inst.capital_ratio,
                parameters=inst.parameters or {},
                enabled=True
            )
            self.configs[inst.id] = config

            # 创建状态
            self.status[inst.id] = StrategyStatus(
                instance_id=inst.id,
                name=inst.name,
                status=inst.status,
                allocated_capital=inst.allocated_capital,
                current_capital=inst.allocated_capital,
                total_profit=inst.total_profit,
                total_trades=inst.total_trades,
                start_time=inst.start_time
            )

        # 计算总资金
        account = Account.objects.filter(broker=self.broker).first()
        if account:
            self.total_capital = account.balance

        logger.info(f"加载了 {len(instances)} 个策略实例")

    def register_strategy(
        self,
        strategy: Strategy,
        name: str,
        allocated_capital: Optional[Decimal] = None,
        capital_ratio: Optional[Decimal] = None,
        parameters: Optional[Dict] = None
    ) -> StrategyInstance:
        """
        注册新策略

        Args:
            strategy: 策略模板对象
            name: 实例名称
            allocated_capital: 分配资金
            capital_ratio: 资金比例
            parameters: 策略参数

        Returns:
            StrategyInstance: 创建的策略实例
        """
        # 计算分配资金
        if allocated_capital is None and capital_ratio is None:
            capital_ratio = Decimal('1') / (len(self.configs) + 1)

        if allocated_capital is None:
            allocated_capital = self.total_capital * (capital_ratio or Decimal('0'))

        # 创建数据库记录
        instance = StrategyInstance.objects.create(
            strategy=strategy,
            name=name,
            broker=self.broker,
            allocated_capital=allocated_capital,
            capital_ratio=capital_ratio or Decimal('0'),
            parameters=parameters or {}
        )

        # 创建配置
        config = StrategyConfig(
            strategy_id=strategy.id,
            name=name,
            broker_id=self.broker.id,
            instruments=list(strategy.instruments.values_list('product_code', flat=True)),
            allocated_capital=allocated_capital,
            capital_ratio=capital_ratio or Decimal('0'),
            parameters=parameters or {},
            enabled=True
        )
        self.configs[instance.id] = config

        # 创建状态
        self.status[instance.id] = StrategyStatus(
            instance_id=instance.id,
            name=name,
            status='stopped',
            allocated_capital=allocated_capital,
            current_capital=allocated_capital,
            total_profit=Decimal('0'),
            total_trades=0
        )

        logger.info(f"注册策略实例: {name} (ID={instance.id}), 资金={allocated_capital}")
        return instance

    def start_strategy(self, instance_id: int) -> bool:
        """
        启动策略

        Args:
            instance_id: 策略实例ID

        Returns:
            bool: 是否成功启动
        """
        if instance_id not in self.configs:
            logger.error(f"策略实例不存在: {instance_id}")
            return False

        config = self.configs[instance_id]

        if instance_id in self.strategies:
            logger.warning(f"策略实例已在运行: {config.name}")
            return False

        try:
            # 创建策略实例
            strategy_template = Strategy.objects.get(id=config.strategy_id)
            strategy_instance = TradeStrategy(name=strategy_template.name)

            # 应用参数覆盖
            if config.parameters:
                self._apply_parameters(strategy_instance, config.parameters)

            # 启动策略
            asyncio.create_task(strategy_instance.start())

            self.strategies[instance_id] = strategy_instance

            # 更新状态
            self.status[instance_id].status = 'running'
            self.status[instance_id].start_time = timezone.now()

            # 更新数据库
            db_instance = StrategyInstance.objects.get(id=instance_id)
            db_instance.status = 'running'
            db_instance.start_time = timezone.now()
            db_instance.save()

            logger.info(f"启动策略实例: {config.name} (ID={instance_id})")
            return True

        except Exception as e:
            logger.error(f"启动策略失败 {config.name}: {repr(e)}", exc_info=True)
            self.status[instance_id].status = 'error'
            self.status[instance_id].error_message = str(e)
            return False

    def stop_strategy(self, instance_id: int) -> bool:
        """
        停止策略

        Args:
            instance_id: 策略实例ID

        Returns:
            bool: 是否成功停止
        """
        if instance_id not in self.strategies:
            logger.warning(f"策略实例未运行: {instance_id}")
            return False

        config = self.configs[instance_id]
        strategy_instance = self.strategies[instance_id]

        try:
            # 停止策略
            asyncio.create_task(strategy_instance.stop())

            del self.strategies[instance_id]

            # 更新状态
            self.status[instance_id].status = 'stopped'

            # 更新数据库
            db_instance = StrategyInstance.objects.get(id=instance_id)
            db_instance.status = 'stopped'
            db_instance.stop_time = timezone.now()
            db_instance.save()

            logger.info(f"停止策略实例: {config.name} (ID={instance_id})")
            return True

        except Exception as e:
            logger.error(f"停止策略失败 {config.name}: {repr(e)}", exc_info=True)
            return False

    def pause_strategy(self, instance_id: int) -> bool:
        """
        暂停策略

        Args:
            instance_id: 策略实例ID

        Returns:
            bool: 是否成功暂停
        """
        if instance_id not in self.strategies:
            return False

        config = self.configs[instance_id]
        self.status[instance_id].status = 'paused'

        # 更新数据库
        db_instance = StrategyInstance.objects.get(id=instance_id)
        db_instance.status = 'paused'
        db_instance.save()

        logger.info(f"暂停策略实例: {config.name} (ID={instance_id})")
        return True

    def resume_strategy(self, instance_id: int) -> bool:
        """
        恢复策略

        Args:
            instance_id: 策略实例ID

        Returns:
            bool: 是否成功恢复
        """
        if instance_id not in self.strategies:
            return False

        config = self.configs[instance_id]
        self.status[instance_id].status = 'running'

        # 更新数据库
        db_instance = StrategyInstance.objects.get(id=instance_id)
        db_instance.status = 'running'
        db_instance.save()

        logger.info(f"恢复策略实例: {config.name} (ID={instance_id})")
        return True

    def allocate_capital(self, instance_id: int, amount: Decimal) -> bool:
        """
        分配资金给策略

        Args:
            instance_id: 策略实例ID
            amount: 分配金额

        Returns:
            bool: 是否成功分配
        """
        if instance_id not in self.configs:
            return False

        # 检查可用资金
        allocated = sum(c.allocated_capital for c in self.configs.values()) - self.configs[instance_id].allocated_capital
        if allocated + amount > self.total_capital:
            logger.warning(f"资金不足: 总资金={self.total_capital}, 已分配={allocated}, 请求={amount}")
            return False

        # 更新配置
        self.configs[instance_id].allocated_capital = amount

        # 更新状态
        self.status[instance_id].allocated_capital = amount

        # 更新数据库
        db_instance = StrategyInstance.objects.get(id=instance_id)
        db_instance.allocated_capital = amount
        db_instance.save()

        logger.info(f"分配资金: {self.configs[instance_id].name} = {amount}")
        return True

    def reallocate_capital(self, ratios: Dict[int, Decimal]) -> bool:
        """
        按比例重新分配资金

        Args:
            ratios: {instance_id: ratio} 比例字典

        Returns:
            bool: 是否成功重新分配
        """
        total_ratio = sum(ratios.values())
        if abs(total_ratio - Decimal('1')) > Decimal('0.01'):
            logger.error(f"比例总和必须为1, 当前={total_ratio}")
            return False

        # 计算分配金额
        allocations = {}
        for instance_id, ratio in ratios.items():
            if instance_id not in self.configs:
                logger.warning(f"策略实例不存在: {instance_id}")
                continue
            allocations[instance_id] = self.total_capital * ratio

        # 应用分配
        for instance_id, amount in allocations.items():
            self.allocate_capital(instance_id, amount)

        return True

    def get_status(self, instance_id: Optional[int] = None) -> Dict:
        """
        获取策略状态

        Args:
            instance_id: 策略实例ID (None=获取所有)

        Returns:
            Dict: 策略状态信息
        """
        if instance_id:
            if instance_id not in self.status:
                return {}
            status = self.status[instance_id]
            return {
                'instance_id': status.instance_id,
                'name': status.name,
                'status': status.status,
                'allocated_capital': float(status.allocated_capital),
                'current_capital': float(status.current_capital),
                'total_profit': float(status.total_profit),
                'total_trades': status.total_trades,
                'start_time': status.start_time,
                'last_signal_time': status.last_signal_time,
                'error_message': status.error_message,
            }
        else:
            return {
                str(i): self.get_status(i)
                for i in self.status.keys()
            }

    def update_statistics(self):
        """更新策略统计信息"""
        for instance_id, status in self.status.items():
            if instance_id not in self.configs:
                continue

            config = self.configs[instance_id]
            strategy_template = Strategy.objects.get(id=config.strategy_id)

            # 从数据库查询交易统计
            trades = Trade.objects.filter(
                strategy=strategy_template,
                broker=self.broker
            )

            status.total_trades = trades.count()
            status.total_profit = trades.aggregate(Sum('profit'))['profit__sum'] or Decimal('0')

            # 更新数据库
            db_instance = StrategyInstance.objects.filter(id=instance_id).first()
            if db_instance:
                db_instance.total_trades = status.total_trades
                db_instance.total_profit = status.total_profit
                db_instance.save()

    def _apply_parameters(self, strategy: BaseModule, parameters: Dict):
        """应用参数到策略"""
        # 这里需要根据具体的策略实现来应用参数
        # 例如，可以通过修改策略的属性或调用配置方法
        for key, value in parameters.items():
            if hasattr(strategy, f'_{key}'):
                setattr(strategy, f'_{key}', value)
            elif hasattr(strategy, key):
                setattr(strategy, key, value)

    def get_running_strategies(self) -> List[int]:
        """获取正在运行的策略ID列表"""
        return [
            i for i, s in self.status.items()
            if s.status == 'running'
        ]

    def stop_all(self) -> int:
        """
        停止所有策略

        Returns:
            int: 成功停止的策略数量
        """
        count = 0
        for instance_id in list(self.strategies.keys()):
            if self.stop_strategy(instance_id):
                count += 1
        logger.info(f"停止了 {count} 个策略实例")
        return count


def create_strategy_manager(broker: Broker) -> StrategyManager:
    """
    创建策略管理器的工厂函数

    Args:
        broker: 券商/账户对象

    Returns:
        StrategyManager: 策略管理器实例
    """
    return StrategyManager(broker)
