# coding=utf=8
"""
算法交易模块 - Algorithm Trading Module

提供算法交易功能：
- TWAP (Time Weighted Average Price)
- VWAP (Volume Weighted Average Price)
- 跟单算法 (Implementation Shortfall)
"""
from typing import Optional, Dict, Callable
from decimal import Decimal
from datetime import datetime, timedelta
from enum import Enum
import logging
from dataclasses import dataclass
import asyncio

from django.utils import timezone

from panel.models import (
    Instrument, Broker, DirectionType
)


logger = logging.getLogger('AlgorithmTrading')


class AlgoType(Enum):
    """算法类型"""
    TWAP = "twap"           # 时间加权平均
    VWAP = "vwap"           # 成交量加权平均
    SNAPSHOT = "snapshot"   # �狙击算法
    POV = "pov"             # 市场参与率
    iceberg = "iceberg"      # 冰山单


@dataclass
class AlgoOrder:
    """算法订单"""
    algo_type: AlgoType
    instrument: Instrument
    direction: DirectionType
    side: str  # buy/sell
    total_volume: int
    price_limit: Optional[Decimal] = None
    price_limit_hard: Optional[Decimal] = None  # 硬价格限制
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # 执行参数
    urgency: int = 3  # 紧急程度 1-5
    sweep_range: float = 0.001  # 扫单范围 (%)
    sweep_to_fill: bool = False
    display_size: int = 1  # 每次下单数量
    min_size: int = 1
    max_size: int = 10

    # 状态
    filled_volume: int = 0
    avg_price: Decimal = Decimal('0')
    status: str = "pending"  # pending, running, completed, cancelled, failed


class AlgoEngine:
    """
    算法交易引擎

    功能：
    1. TWAP算法
    2. VWAP算法
    3. 执行监控
    """

    def __init__(self, broker: Broker):
        """
        初始化算法交易引擎

        Args:
            broker: 券商/账户对象
        """
        self.broker = broker
        self.active_orders: Dict[str, AlgoOrder] = {}
        self.order_func: Optional[Callable] = None

    def set_order_function(self, func: Callable):
        """
        设置下单函数

        Args:
            func: 下单函数
        """
        self.order_func = func

    async def execute_twap(self, order: AlgoOrder) -> bool:
        """
        执行TWAP算法

        Args:
            order: 算法订单

        Returns:
            bool: 是否成功执行
        """
        logger.info(f"开始TWAP算法: {order.instrument.code} {order.side} {order.total_volume}手")

        if not order.start_time:
            order.start_time = timezone.now()

        if not order.end_time:
            # 默认在1小时内完成
            order.end_time = order.start_time + timedelta(hours=1)

        total_duration = (order.end_time - order.start_time).total_seconds()

        if total_duration <= 0:
            logger.error("TWAP订单时间范围无效")
            return False

        # 计算切片数量和每次数量
        num_slices = max(1, int(total_duration / 60))  # 每分钟一个切片
        volume_per_slice = order.total_volume / num_slices

        # 确保每次数量是整数
        volume_per_slice = max(1, round(volume_per_slice))

        # 调整切片数量
        num_slices = int(order.total_volume / volume_per_slice)

        order.status = "running"

        # 执行TWAP
        for i in range(num_slices):
            if order.status != "running":
                break

            # 检查是否在有效时间范围内
            now = timezone.now()

            if now < order.start_time:
                await asyncio.sleep((order.start_time - now).total_seconds())
                now = timezone.now()

            if now >= order.end_time:
                break

            # 计算当前切片应该下单的数量
            remaining = order.total_volume - order.filled_volume
            if remaining <= 0:
                break

            slice_volume = min(volume_per_slice, remaining)

            # 获取当前价格
            current_price = await self._get_current_price(order.instrument)

            # 应用价格限制
            if order.price_limit:
                if order.side == "buy":
                    # 买单不超过限价
                    price = min(current_price, order.price_limit)
                else:
                    # 卖单不低于限价
                    price = max(current_price, order.price_limit)
            else:
                price = current_price

            # 执行下单
            success = await self._place_order(order, price, slice_volume)

            if success:
                order.filled_volume += slice_volume
                logger.info(f"TWAP执行 [{i+1}/{num_slices}]: "
                           f"{order.instrument.code} {slice_volume}手 @{price}")

            # 等待下一个切片
            time_per_slice = total_duration / num_slices
            await asyncio.sleep(time_per_slice)

        # 完成状态
        if order.filled_volume >= order.total_volume:
            order.status = "completed"
        else:
            order.status = "partial"

        logger.info(f"TWAP算法完成: {order.instrument.code} "
                   f"已成交:{order.filled_volume}/{order.total_volume}")

        return order.status == "completed"

    async def execute_vwap(self, order: AlgoOrder) -> bool:
        """
        执行VWAP算法

        Args:
            order: 算法订单

        Returns:
            bool: 是否成功执行
        """
        logger.info(f"开始VWAP算法: {order.instrument.code} {order.side} {order.total_volume}手")

        # 获取历史成交量分布
        volume_profile = await self._get_volume_profile(order.instrument, lookback=20)

        total_volume = sum(volume_profile.values())
        if total_volume <= 0:
            logger.warning("无法获取成交量分布，回退到TWAP")
            return await self.execute_twap(order)

        # 按成交量比例分配订单
        order.status = "running"
        cumulative_ratio = 0

        for time_bucket, bucket_volume in sorted(volume_profile.items()):
            if order.status != "running":
                break

            ratio = bucket_volume / total_volume
            slice_volume = max(1, int(order.total_volume * (ratio - cumulative_ratio)))

            if slice_volume > 0:
                # 获取当前价格
                current_price = await self._get_current_price(order.instrument)

                if order.price_limit:
                    if order.side == "buy":
                        current_price = min(current_price, order.price_limit)
                    else:
                        current_price = max(current_price, order.price_limit)

                # 执行下单
                success = await self._place_order(order, current_price, slice_volume)

                if success:
                    order.filled_volume += slice_volume
                    cumulative_ratio += ratio

                logger.info(f"VWAP执行 [{time_bucket}]: "
                           f"{order.instrument.code} {slice_volume}手 @{current_price} "
                           f"占比:{ratio:.2%}")

            # 等待下一个时间段
            await asyncio.sleep(60)  # 假设1分钟一个时间段

        order.status = "completed" if order.filled_volume >= order.total_volume else "partial"
        return order.status == "completed"

    async def execute_snapshot(self, order: AlgoOrder) -> bool:
        """
        执行狙击算法

        快速执行大单，尽量减少市场冲击

        Args:
            order: 算法订单

        Returns:
            bool: 是否成功执行
        """
        logger.info(f"开始Snapshot算法: {order.instrument.code} {order.side} {order.total_volume}手")

        # 获取当前买卖价
        best_bid, best_ask, best_bid_size, best_ask_size = await self._get_order_book(order.instrument)

        if order.side == "buy":
            # 买单：吃单
            if order.total_volume <= best_bid_size:
                # 小单直接吃单
                price = best_ask
                volume = order.total_volume
            else:
                # 大单使用限价单
                price = best_ask
                volume = order.total_volume
        else:
            # 卖单
            if order.total_volume <= best_ask_size:
                price = best_bid
                volume = order.total_volume
            else:
                price = best_bid
                volume = order.total_volume

        # 应用价格限制
        if order.price_limit:
            if order.side == "buy":
                price = min(price, order.price_limit)
            else:
                price = max(price, order.price_limit)

        # 执行下单
        order.status = "running"
        success = await self._place_order(order, price, volume)

        if success:
            order.filled_volume = volume

        order.status = "completed" if success else "failed"
        return success

    async def _place_order(
        self,
        order: AlgoOrder,
        price: Decimal,
        volume: int
    ) -> bool:
        """
        下单

        Args:
            order: 算法订单
            price: 价格
            volume: 数量

        Returns:
            bool: 是否成功
        """
        # TODO: 调用实际的下单接口
        if self.order_func:
            try:
                return await self.order_func(
                    instrument=order.instrument,
                    direction=order.direction,
                    price=price,
                    volume=volume
                )
            except Exception as e:
                logger.error(f"算法交易下单失败: {repr(e)}")
                return False

        # 模拟下单成功
        logger.debug(f"算法交易模拟下单: {order.instrument.code} "
                     f"{order.direction.label} {volume}手 @{price}")
        return True

    async def _get_current_price(self, instrument: Instrument) -> Decimal:
        """
        获取当前价格

        Args:
            instrument: 合约

        Returns:
            Decimal: 当前价格
        """
        # TODO: 从tick数据或Redis获取最新价格
        # 这里先从DailyBar获取最新收盘价
        from panel.models import DailyBar

        bar = DailyBar.objects.filter(
            instrument=instrument,
            exchange=instrument.exchange
        ).order_by('-time').first()

        if bar:
            return bar.close

        # 返回默认价格
        return Decimal('0')

    async def _get_order_book(self, instrument: Instrument) -> tuple:
        """
        获取订单簿数据

        Args:
            instrument: 合约

        Returns:
            tuple: (bid, ask, bid_size, ask_size)
        """
        # TODO: 从tick数据获取订单簿
        current_price = await self._get_current_price(instrument)
        spread = current_price * Decimal('0.0002')  # 0.02% 价差

        if current_price > 0:
            return current_price - spread, current_price + spread, 100, 100
        return Decimal('0'), Decimal('0'), 0, 0

    async def _get_volume_profile(
        self,
        instrument: Instrument,
        lookback: int = 20
    ) -> Dict[str, float]:
        """
        获取历史成交量分布

        Args:
            instrument: 合约
            lookback: 回看天数

        Returns:
            Dict: 时间段成交量
        """
        # TODO: 从历史数据获取成交量分布
        # 这里简化处理，假设均匀分布
        now = timezone.now()
        profile = {}

        for i in range(lookback):
            time_key = (now - timedelta(minutes=i)).strftime('%H:%M')
            profile[time_key] = 1.0 / lookback

        return profile

    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        获取算法订单状态

        Args:
            order_id: 订单ID

        Returns:
            Dict: 订单状态
        """
        if order_id not in self.active_orders:
            return None

        order = self.active_orders[order_id]

        return {
            'order_id': order_id,
            'algo_type': order.algo_type.value,
            'instrument': order.instrument.code,
            'side': order.side,
            'total_volume': order.total_volume,
            'filled_volume': order.filled_volume,
            'fill_ratio': order.filled_volume / order.total_volume if order.total_volume > 0 else 0,
            'status': order.status,
            'avg_price': float(order.avg_price) if order.avg_price else 0,
            'start_time': order.start_time.isoformat() if order.start_time else None,
            'end_time': order.end_time.isoformat() if order.end_time else None,
        }

    def cancel_algo_order(self, order_id: str) -> bool:
        """
        取消算法订单

        Args:
            order_id: 订单ID

        Returns:
            bool: 是否成功取消
        """
        if order_id in self.active_orders:
            order = self.active_orders[order_id]
            order.status = "cancelled"
            logger.info(f"取消算法订单: {order_id}")
            return True
        return False


def create_algo_engine(broker: Broker) -> AlgoEngine:
    """创建算法交易引擎"""
    return AlgoEngine(broker)


# 算法交易便捷函数
def twap_order(
    instrument: Instrument,
    direction: DirectionType,
    volume: int,
    duration_minutes: int = 60,
    broker: Broker = None,
    price_limit: Optional[Decimal] = None
) -> AlgoOrder:
    """
    创建TWAP订单

    Args:
        instrument: 合约
        direction: 方向
        volume: 数量
        duration_minutes: 执行时长(分钟)
        broker: 券商
        price_limit: 价格限制

    Returns:
        AlgoOrder: TWAP订单
    """
    start_time = timezone.now()
    end_time = start_time + timedelta(minutes=duration_minutes)

    side = "buy" if direction == DirectionType.LONG else "sell"

    return AlgoOrder(
        algo_type=AlgoType.TWAP,
        instrument=instrument,
        direction=direction,
        side=side,
        total_volume=volume,
        price_limit=price_limit,
        start_time=start_time,
        end_time=end_time
    )


def vwap_order(
    instrument: Instrument,
    direction: DirectionType,
    volume: int,
    duration_minutes: int = 60,
    broker: Broker = None
) -> AlgoOrder:
    """
    创建VWAP订单

    Args:
        instrument: 合约
        direction: 方向
        volume: 数量
        duration_minutes: 执行时长(分钟)
        broker: 券商

    Returns:
        AlgoOrder: VWAP订单
    """
    return twap_order(
        instrument=instrument,
        direction=direction,
        volume=volume,
        duration_minutes=duration_minutes,
        broker=broker
    )
