# coding=utf-8
"""
条件单模块 - Conditional Order Module

提供条件单功能：
- 止损限价单
- 冰山单
- 时间条件单
- 价格条件单
"""
from typing import Optional, Dict, List, Callable, Any
from decimal import Decimal
from datetime import datetime
from enum import Enum
import logging
from dataclasses import dataclass, field
import asyncio

from django.utils import timezone

from panel.models import (
    Instrument, Broker, DirectionType, OffsetFlag
)
from trade_trader.utils.read_config import config


logger = logging.getLogger('ConditionalOrder')


class ConditionType(Enum):
    """条件类型"""
    PRICE_GT = "price_gt"           # 价格大于
    PRICE_LT = "price_lt"           # 价格小于
    PRICE_GE = "price_ge"           # 价格大于等于
    PRICE_LE = "price_le"           # 价格小于等于
    TIME_GT = "time_gt"             # 时间晚于
    TIME_LT = "time_lt"             # 时间早于
    POSITION_GT = "position_gt"     # 持仓大于
    POSITION_LT = "position_lt"     # 持仓小于
    PROFIT_GT = "profit_gt"         # 盈利大于
    PROFIT_LT = "profit_lt"         # 盈利小于
    DRAWDOWN_GT = "drawdown_gt"     # 回撤大于


class OrderType(Enum):
    """订单类型"""
    LIMIT = "limit"                 # 限价单
    MARKET = "market"               # 市价单
    STOP_LIMIT = "stop_limit"       # 止损限价单


@dataclass
class Condition:
    """条件"""
    type: ConditionType
    value: Any
    instrument: Optional[str] = None  # 合约代码
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConditionalOrder:
    """条件单"""
    order_id: str
    strategy_id: Optional[int] = None
    broker: Broker = None

    # 订单信息
    instrument: Instrument = None
    direction: DirectionType = None
    offset: OffsetFlag = None
    order_type: OrderType = OrderType.LIMIT
    price: Optional[Decimal] = None
    volume: int = 1

    # 触发条件
    conditions: List[Condition] = field(default_factory=list)
    condition_logic: str = "AND"  # AND / OR

    # 有效期
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # 状态
    is_active: bool = True
    is_triggered: bool = False
    triggered_time: Optional[datetime] = None
    created_time: datetime = field(default_factory=timezone.now)

    # 执行参数
    expire_time: Optional[int] = None  # 订单过期时间(秒)

    # 冰山单参数
    is_iceberg: bool = False
    display_volume: int = 0  # 冰山单显示数量
    total_volume: int = 0    # 冰山单总数量
    min_volume: int = 1       # 冰山单最小每次数量

    # 高级参数
    fill_or_kill: bool = False   # 全成或撤
    all_or_none: bool = False    # 全部成交或撤
    immediate_or_cancel: bool = False  # 立即成交或撤


class ConditionalOrderEngine:
    """
    条件单引擎

    功能：
    1. 注册条件单
    2. 检查条件触发
    3. 执行条件单
    4. 管理条件单生命周期
    """

    def __init__(self, broker: Broker):
        """
        初始化条件单引擎

        Args:
            broker: 券商/账户对象
        """
        self.broker = broker
        self.orders: Dict[str, ConditionalOrder] = {}  # order_id -> ConditionalOrder
        self.price_cache: Dict[str, Decimal] = {}  # code -> latest_price

        # 从配置读取参数
        self.check_interval = config.getint('CONDITIONAL_ORDER', 'check_interval', fallback=1)

    def register_order(self, order: ConditionalOrder) -> bool:
        """
        注册条件单

        Args:
            order: 条件单对象

        Returns:
            bool: 是否成功注册
        """
        if not order.instrument:
            logger.error("条件单缺少合约信息")
            return False

        # 生成订单ID
        if not order.order_id:
            order.order_id = f"CO_{timezone.now().strftime('%Y%m%d%H%M%S')}_{order.instrument.product_code}"

        self.orders[order.order_id] = order
        logger.info(f"注册条件单: {order.order_id}")

        return True

    def cancel_order(self, order_id: str) -> bool:
        """
        取消条件单

        Args:
            order_id: 订单ID

        Returns:
            bool: 是否成功取消
        """
        if order_id in self.orders:
            del self.orders[order_id]
            logger.info(f"取消条件单: {order_id}")
            return True
        return False

    def update_price(self, code: str, price: Decimal):
        """
        更新价格缓存

        Args:
            code: 合约代码
            price: 最新价格
        """
        self.price_cache[code] = price

    def check_conditions(self, order: ConditionalOrder) -> bool:
        """
        检查条件是否触发

        Args:
            order: 条件单

        Returns:
            bool: 是否触发
        """
        if not order.conditions:
            return False

        # 检查有效期
        now = timezone.now()

        if order.start_time and now < order.start_time:
            return False

        if order.end_time and now > order.end_time:
            logger.info(f"条件单已过期: {order.order_id}")
            return False

        results = []

        for condition in order.conditions:
            result = self._check_single_condition(condition)
            results.append(result)

        # 逻辑判断
        if order.condition_logic == "AND":
            return all(results)
        else:  # OR
            return any(results)

    def _check_single_condition(self, condition: Condition) -> bool:
        """
        检查单个条件

        Args:
            condition: 条件

        Returns:
            bool: 是否满足
        """
        try:
            if condition.type == ConditionType.PRICE_GT:
                code = condition.instrument
                if code not in self.price_cache:
                    return False
                return self.price_cache[code] > Decimal(str(condition.value))

            elif condition.type == ConditionType.PRICE_LT:
                code = condition.instrument
                if code not in self.price_cache:
                    return False
                return self.price_cache[code] < Decimal(str(condition.value))

            elif condition.type == ConditionType.PRICE_GE:
                code = condition.instrument
                if code not in self.price_cache:
                    return False
                return self.price_cache[code] >= Decimal(str(condition.value))

            elif condition.type == ConditionType.PRICE_LE:
                code = condition.instrument
                if code not in self.price_cache:
                    return False
                return self.price_cache[code] <= Decimal(str(condition.value))

            elif condition.type == ConditionType.TIME_GT:
                return timezone.now() > condition.value

            elif condition.type == ConditionType.TIME_LT:
                return timezone.now() < condition.value

            elif condition.type == ConditionType.PROFIT_GT:
                # 检查持仓盈利
                return self._check_position_profit(condition.instrument, float(condition.value), '>')

            elif condition.type == ConditionType.PROFIT_LT:
                # 检查持仓盈利
                return self._check_position_profit(condition.instrument, float(condition.value), '<')

            elif condition.type == ConditionType.DRAWDOWN_GT:
                # 检查回撤
                return self._check_position_drawdown(condition.instrument, float(condition.value), '>')

            return False

        except Exception as e:
            logger.error(f"检查条件失败: {repr(e)}", exc_info=True)
            return False

    def _check_position_profit(self, code: str, threshold: float, op: str) -> bool:
        """
        检查持仓盈利

        Args:
            code: 合约代码
            threshold: 阈值
            op: 比较操作符

        Returns:
            bool: 是否满足条件
        """
        try:
            from panel.models import Position
            positions = Position.objects.filter(
                broker=self.broker,
                code__contains=code,
                position__gt=0
            )

            total_profit = Decimal('0')
            for pos in positions:
                if pos.position_profit:
                    total_profit += pos.position_profit

            if op == '>':
                return float(total_profit) > threshold
            elif op == '<':
                return float(total_profit) < threshold
            elif op == '>=':
                return float(total_profit) >= threshold
            elif op == '<=':
                return float(total_profit) <= threshold

            return False

        except Exception as e:
            logger.error(f"检查持仓盈利失败: {repr(e)}")
            return False

    def _check_position_drawdown(self, code: str, threshold: float, op: str) -> bool:
        """
        检查持仓回撤

        Args:
            code: 合约代码
            threshold: 阈值
            op: 比较操作符

        Returns:
            bool: 是否满足条件
        """
        try:
            from panel.models import Position, Trade

            positions = Position.objects.filter(
                broker=self.broker,
                code__contains=code,
                position__gt=0
            )

            for pos in positions:
                trades = Trade.objects.filter(
                    broker=self.broker,
                    instrument=pos.instrument,
                    close_time__isnull=False
                ).order_by('-close_time')[:20]

                if trades.count() < 2:
                    continue

                # 计算最高盈利
                max_profit = 0
                # peak_price = Decimal('0')  # TODO: implement peak price tracking

                if pos.direction == '0':  # LONG
                    for t in trades:
                        if t.profit:
                            max_profit = max(max_profit, float(t.profit))

                    current_profit = float(pos.position_profit or 0)
                    drawdown = max_profit - current_profit if max_profit > 0 else 0

                else:  # SHORT
                    for t in trades:
                        if t.profit:
                            max_profit = max(max_profit, float(t.profit))

                    current_profit = float(pos.position_profit or 0)
                    # 空头回撤 = 最高盈利 - 当前盈利
                    drawdown = max_profit - current_profit if max_profit > 0 else 0

                if op == '>':
                    return drawdown > threshold
                elif op == '<':
                    return drawdown < threshold
                elif op == '>=':
                    return drawdown >= threshold
                elif op == '<=':
                    return drawdown <= threshold

            return False

        except Exception as e:
            logger.error(f"检查持仓回撤失败: {repr(e)}")
            return False

    async def execute_order(self, order: ConditionalOrder, order_func: Callable) -> bool:
        """
        执行条件单

        Args:
            order: 条件单
            order_func: 下单函数

        Returns:
            bool: 是否成功执行
        """
        try:
            order.is_triggered = True
            order.triggered_time = timezone.now()

            # 冰山单特殊处理
            if order.is_iceberg:
                return await self._execute_iceberg_order(order, order_func)
            else:
                # 普通订单
                return await self._execute_normal_order(order, order_func)

        except Exception as e:
            logger.error(f"执行条件单失败 {order.order_id}: {repr(e)}", exc_info=True)
            return False

    async def _execute_normal_order(self, order: ConditionalOrder, order_func: Callable) -> bool:
        """执行普通订单"""
        # TODO: 调用实际的下单接口
        logger.info(f"执行条件单: {order.order_id} {order.instrument.code} "
                   f"{order.direction.label} {order.volume}手 @{order.price}")

        # 这里应该调用实际的CTP下单接口
        # order_func(order)
        return True

    async def _execute_iceberg_order(self, order: ConditionalOrder, order_func: Callable) -> bool:
        """执行冰山单"""
        logger.info(f"执行冰山单: {order.order_id} 总量:{order.total_volume} "
                   f"显示:{order.display_volume}")

        remaining = order.total_volume

        while remaining > 0 and order.is_active:
            volume = min(order.display_volume, remaining)
            # TODO: 下单
            remaining -= volume

            # 等待一段时间再下单下一批
            await asyncio.sleep(1)

        return True

    async def monitoring_loop(self):
        """条件单监控循环"""
        while True:
            try:
                # 检查所有激活的条件单
                for order_id, order in list(self.orders.items()):
                    if not order.is_active or order.is_triggered:
                        continue

                    if self.check_conditions(order):
                        logger.info(f"条件单触发: {order_id}")
                        # TODO: 获取下单函数并执行
                        # await self.execute_order(order, order_func)

                # 清理已过期或已触发的订单
                self._cleanup_orders()

            except Exception as e:
                logger.error(f"条件单监控循环错误: {repr(e)}", exc_info=True)

            await asyncio.sleep(self.check_interval)

    def _cleanup_orders(self):
        """清理无效订单"""
        now = timezone.now()
        to_remove = []

        for order_id, order in self.orders.items():
            # 移除已触发的订单
            if order.is_triggered:
                to_remove.append(order_id)
                continue

            # 移除已过期的订单
            if order.end_time and now > order.end_time:
                logger.info(f"条件单过期: {order_id}")
                to_remove.append(order_id)
                continue

        for order_id in to_remove:
            del self.orders[order_id]


def create_conditional_order_engine(broker: Broker) -> ConditionalOrderEngine:
    """创建条件单引擎"""
    return ConditionalOrderEngine(broker)


# 条件单便捷函数
def stop_limit_order(
    instrument: Instrument,
    direction: DirectionType,
    stop_price: Decimal,
    limit_price: Decimal,
    volume: int,
    broker: Broker
) -> ConditionalOrder:
    """
    创建止损限价单

    Args:
        instrument: 合约
        direction: 方向
        stop_price: 止损价格
        limit_price: 限价
        volume: 数量
        broker: 券商

    Returns:
        ConditionalOrder: 条件单
    """
    conditions = []

    if direction == DirectionType.LONG:
        # 多头: 价格跌破止损价
        conditions.append(Condition(
            type=ConditionType.PRICE_LE,
            value=stop_price,
            instrument=instrument.code
        ))
    else:  # SHORT
        # 空头: 价格突破止损价
        conditions.append(Condition(
            type=ConditionType.PRICE_GE,
            value=stop_price,
            instrument=instrument.code
        ))

    return ConditionalOrder(
        instrument=instrument,
        direction=direction,
        offset=OffsetFlag.Close,
        price=limit_price,
        volume=volume,
        broker=broker,
        conditions=conditions,
        order_type=OrderType.STOP_LIMIT
    )


def iceberg_order(
    instrument: Instrument,
    direction: DirectionType,
    price: Decimal,
    total_volume: int,
    display_volume: int,
    broker: Broker,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None
) -> ConditionalOrder:
    """
    创建冰山单

    Args:
        instrument: 合约
        direction: 方向
        price: 价格
        total_volume: 总数量
        display_volume: 每次显示数量
        broker: 券商
        start_time: 开始时间
        end_time: 结束时间

    Returns:
        ConditionalOrder: 条件单
    """
    return ConditionalOrder(
        instrument=instrument,
        direction=direction,
        offset=OffsetFlag.Open,
        price=price,
        volume=display_volume,  # 这个参数在冰山单中不使用
        broker=broker,
        conditions=[],
        start_time=start_time,
        end_time=end_time,
        is_iceberg=True,
        display_volume=display_volume,
        total_volume=total_volume
    )
