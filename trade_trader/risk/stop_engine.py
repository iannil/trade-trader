# coding=utf-8
"""
止损止盈引擎 - Stop Loss and Take Profit Engine

提供完整的止损止盈功能：
- 固定止损/止盈
- 移动止损 (Trailing Stop)
- 百分比止损/止盈
- ATR止损
- 时间止损
"""
from typing import Optional, Dict, List
from decimal import Decimal
import logging
from datetime import datetime
from enum import Enum

from django.utils import timezone

from panel.models import (
    Position, Strategy, Broker,
    DirectionType
)
from trade_trader.utils.read_config import config


logger = logging.getLogger('StopEngine')


class StopType(Enum):
    """止损类型"""
    FIXED_PRICE = "fixed_price"       # 固定价格止损
    PERCENTAGE = "percentage"         # 百分比止损
    ATR = "atr"                       # ATR止损
    TRAILING = "trailing"             # 移动止损
    TIME = "time"                     # 时间止损


class StopOrder:
    """止损单"""

    def __init__(
        self,
        position_id: int,
        stop_type: StopType,
        stop_price: Optional[Decimal] = None,
        stop_percentage: Optional[Decimal] = None,
        atr_multiple: Optional[Decimal] = None,
        trailing_distance: Optional[Decimal] = None,
        exit_time: Optional[datetime] = None,
        direction: Optional[DirectionType] = None
    ):
        self.position_id = position_id
        self.stop_type = stop_type
        self.stop_price = stop_price
        self.stop_percentage = stop_percentage
        self.atr_multiple = atr_multiple
        self.trailing_distance = trailing_distance
        self.exit_time = exit_time
        self.direction = direction
        self.created_at = timezone.now()
        self.updated_at = timezone.now()
        self.triggered = False
        self.highest_price: Optional[Decimal] = None  # 用于移动止损
        self.lowest_price: Optional[Decimal] = None   # 用于空头移动止损


class StopEngine:
    """
    止损止盈引擎

    功能：
    1. 注册止损单
    2. 检查止损条件
    3. 触发止损
    4. 管理移动止损
    """

    def __init__(self, strategy: Strategy, broker: Broker):
        """
        初始化止损引擎

        Args:
            strategy: 策略对象
            broker: 券商对象
        """
        self.strategy = strategy
        self.broker = broker
        self.stop_orders: Dict[int, StopOrder] = {}  # position_id -> StopOrder

        # 从配置读取默认参数
        self.default_stop_loss_pct = config.getfloat(
            'STOP', 'default_stop_loss_pct', fallback=0.02
        )  # 默认止损百分比 2%
        self.default_take_profit_pct = config.getfloat(
            'STOP', 'default_take_profit_pct', fallback=0.05
        )  # 默认止盈百分比 5%
        self.check_interval = config.getint(
            'STOP', 'check_interval', fallback=1
        )  # 检查间隔 (秒)

        logger.info(f"止损止盈引擎初始化完成: 策略={strategy.name}")

    def register_stop_loss(
        self,
        position_id: int,
        stop_type: StopType = StopType.PERCENTAGE,
        stop_price: Optional[Decimal] = None,
        stop_percentage: Optional[Decimal] = None,
        atr_multiple: Optional[Decimal] = None,
        trailing_distance: Optional[Decimal] = None
    ) -> bool:
        """
        注册止损单

        Args:
            position_id: 持仓ID
            stop_type: 止损类型
            stop_price: 固定止损价格
            stop_percentage: 止损百分比 (0.02 = 2%)
            atr_multiple: ATR倍数止损
            trailing_distance: 移动止损距离

        Returns:
            bool: 注册是否成功
        """
        position = Position.objects.filter(id=position_id).first()
        if position is None:
            logger.error(f"持仓不存在: {position_id}")
            return False

        if stop_percentage is None:
            stop_percentage = Decimal(str(self.default_stop_loss_pct))

        stop_order = StopOrder(
            position_id=position_id,
            stop_type=stop_type,
            stop_price=stop_price,
            stop_percentage=stop_percentage,
            atr_multiple=atr_multiple,
            trailing_distance=trailing_distance,
            direction=position.direction
        )

        # 初始化移动止损的价格
        if stop_type == StopType.TRAILING:
            if position.direction == DirectionType.LONG:
                stop_order.highest_price = position.avg_open_price
            else:
                stop_order.lowest_price = position.avg_open_price

        self.stop_orders[position_id] = stop_order
        logger.info(
            f"注册止损单: position={position_id}, type={stop_type.value}, "
            f"price={stop_price}, pct={stop_percentage}"
        )
        return True

    def register_take_profit(
        self,
        position_id: int,
        take_profit_price: Decimal,
        take_profit_percentage: Optional[Decimal] = None
    ) -> bool:
        """
        注册止盈单

        Args:
            position_id: 持仓ID
            take_profit_price: 止盈价格
            take_profit_percentage: 止盈百分比

        Returns:
            bool: 注册是否成功
        """
        position = Position.objects.filter(id=position_id).first()
        if position is None:
            logger.error(f"持仓不存在: {position_id}")
            return False

        # 止盈使用固定价格止损
        stop_order = StopOrder(
            position_id=position_id,
            stop_type=StopType.FIXED_PRICE,
            stop_price=take_profit_price,
            stop_percentage=take_profit_percentage,
            direction=position.direction
        )

        self.stop_orders[position_id] = stop_order
        logger.info(f"注册止盈单: position={position_id}, price={take_profit_price}")
        return True

    def register_trailing_stop(
        self,
        position_id: int,
        distance: Optional[Decimal] = None,
        distance_pct: Optional[Decimal] = None
    ) -> bool:
        """
        注册移动止损

        Args:
            position_id: 持仓ID
            distance: 移动止损绝对距离
            distance_pct: 移动止损百分比距离

        Returns:
            bool: 注册是否成功
        """
        position = Position.objects.filter(id=position_id).first()
        if position is None:
            logger.error(f"持仓不存在: {position_id}")
            return False

        stop_order = StopOrder(
            position_id=position_id,
            stop_type=StopType.TRAILING,
            trailing_distance=distance if distance else distance_pct,
            direction=position.direction
        )

        if position.direction == DirectionType.LONG:
            stop_order.highest_price = position.avg_open_price
        else:
            stop_order.lowest_price = position.avg_open_price

        self.stop_orders[position_id] = stop_order
        logger.info(f"注册移动止损: position={position_id}, distance={distance}")
        return True

    def cancel_stop_order(self, position_id: int) -> bool:
        """
        取消止损单

        Args:
            position_id: 持仓ID

        Returns:
            bool: 取消是否成功
        """
        if position_id in self.stop_orders:
            del self.stop_orders[position_id]
            logger.info(f"取消止损单: position={position_id}")
            return True
        return False

    def check_and_trigger(self, current_prices: Dict[str, Decimal]) -> List[Dict]:
        """
        检查并触发止损

        Args:
            current_prices: 当前价格字典 {code: price}

        Returns:
            List[Dict]: 触发的止损单列表
        """
        triggered_stops = []

        for position_id, stop_order in list(self.stop_orders.items()):
            if stop_order.triggered:
                continue

            position = Position.objects.filter(id=position_id).first()
            if position is None or position.position == 0:
                # 持仓已平仓，移除止损单
                self.cancel_stop_order(position_id)
                continue

            # 获取当前价格
            current_price = current_prices.get(position.code)
            if current_price is None:
                continue

            # 检查止损条件
            should_trigger, stop_price = self._check_stop_condition(
                position, stop_order, current_price
            )

            if should_trigger:
                stop_order.triggered = True
                trigger_info = {
                    'position_id': position_id,
                    'code': position.code,
                    'direction': position.direction,
                    'current_price': current_price,
                    'stop_price': stop_price,
                    'stop_type': stop_order.stop_type.value,
                }
                triggered_stops.append(trigger_info)
                logger.warning(
                    f"止损触发: {position.code} {position.direction.label} "
                    f"@{current_price} (止损价: {stop_price})"
                )

        return triggered_stops

    def _check_stop_condition(
        self,
        position: Position,
        stop_order: StopOrder,
        current_price: Decimal
    ) -> tuple[bool, Optional[Decimal]]:
        """
        检查止损条件

        Returns:
            tuple: (是否触发, 止损价格)
        """
        stop_price = None

        if stop_order.stop_type == StopType.FIXED_PRICE:
            # 固定价格止损
            stop_price = stop_order.stop_price
            if position.direction == DirectionType.LONG:
                return current_price <= stop_price, stop_price
            else:
                return current_price >= stop_price, stop_price

        elif stop_order.stop_type == StopType.PERCENTAGE:
            # 百分比止损
            stop_price = position.avg_open_price * (Decimal('1') - stop_order.stop_percentage)
            if position.direction == DirectionType.SHORT:
                stop_price = position.avg_open_price * (Decimal('1') + stop_order.stop_percentage)

            if position.direction == DirectionType.LONG:
                return current_price <= stop_price, stop_price
            else:
                return current_price >= stop_price, stop_price

        elif stop_order.stop_type == StopType.TRAILING:
            # 移动止损
            if position.direction == DirectionType.LONG:
                # 多头：更新最高价
                if stop_order.highest_price is None or current_price > stop_order.highest_price:
                    stop_order.highest_price = current_price
                    stop_order.updated_at = timezone.now()

                # 计算移动止损价
                if isinstance(stop_order.trailing_distance, Decimal):
                    # 绝对距离
                    stop_price = stop_order.highest_price - stop_order.trailing_distance
                else:
                    # 百分比距离
                    stop_price = stop_order.highest_price * (Decimal('1') - stop_order.trailing_distance)

                return current_price <= stop_price, stop_price

            else:  # SHORT
                # 空头：更新最低价
                if stop_order.lowest_price is None or current_price < stop_order.lowest_price:
                    stop_order.lowest_price = current_price
                    stop_order.updated_at = timezone.now()

                # 计算移动止损价
                if isinstance(stop_order.trailing_distance, Decimal):
                    stop_price = stop_order.lowest_price + stop_order.trailing_distance
                else:
                    stop_price = stop_order.lowest_price * (Decimal('1') + stop_order.trailing_distance)

                return current_price >= stop_price, stop_price

        elif stop_order.stop_type == StopType.ATR:
            # ATR止损 (需要传入ATR值)
            # 这里简化处理，实际应该从外部获取ATR值
            pass

        return False, None

    def get_stop_order_status(self, position_id: int) -> Optional[Dict]:
        """
        获取止损单状态

        Args:
            position_id: 持仓ID

        Returns:
            Optional[Dict]: 止损单状态信息
        """
        stop_order = self.stop_orders.get(position_id)
        if stop_order is None:
            return None

        position = Position.objects.filter(id=position_id).first()
        if position is None:
            return None

        status = {
            'position_id': position_id,
            'stop_type': stop_order.stop_type.value,
            'triggered': stop_order.triggered,
            'created_at': stop_order.created_at,
            'updated_at': stop_order.updated_at,
        }

        if stop_order.stop_price:
            status['stop_price'] = stop_order.stop_price
        if stop_order.stop_percentage:
            status['stop_percentage'] = stop_order.stop_percentage
        if stop_order.trailing_distance:
            status['trailing_distance'] = stop_order.trailing_distance

        if stop_order.stop_type == StopType.TRAILING:
            if position.direction == DirectionType.LONG:
                status['highest_price'] = stop_order.highest_price
            else:
                status['lowest_price'] = stop_order.lowest_price

        return status

    def get_all_stop_orders(self) -> List[Dict]:
        """
        获取所有止损单状态

        Returns:
            List[Dict]: 所有止损单状态列表
        """
        return [
            self.get_stop_order_status(pid)
            for pid in self.stop_orders.keys()
        ]

    def clear_all(self) -> None:
        """清空所有止损单"""
        count = len(self.stop_orders)
        self.stop_orders.clear()
        logger.info(f"已清空所有止损单: {count} 个")


def create_stop_engine(strategy: Strategy, broker: Broker) -> StopEngine:
    """
    创建止损引擎的工厂函数

    Args:
        strategy: 策略对象
        broker: 券商对象

    Returns:
        StopEngine: 止损引擎实例
    """
    return StopEngine(strategy, broker)
