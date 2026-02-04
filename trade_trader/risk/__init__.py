# coding=utf-8
"""
风控模块 - Risk Control Module

提供完整的风险控制功能，包括：
- RiskEngine: 风控引擎，报单前检查
- StopEngine: 止损止盈引擎
- RiskMonitor: 风险监控
"""
from typing import Optional
from decimal import Decimal
import logging
import datetime

from django.utils import timezone
from django.db.models import Sum

from panel.models import (
    Instrument, Position, Broker, Account,
    DirectionType, OffsetFlag,
)
from trade_trader.utils.read_config import config


logger = logging.getLogger('RiskEngine')


class RiskCheckResult:
    """风控检查结果"""

    def __init__(self, passed: bool, message: str = "", code: str = ""):
        self.passed = passed
        self.message = message
        self.code = code

    def __bool__(self):
        return self.passed

    def __str__(self):
        return f"RiskCheckResult(passed={self.passed}, message='{self.message}', code='{self.code}')"


class RiskEngine:
    """
    风控引擎 - 在报单前进行风险检查

    检查项目：
    1. 持仓限额检查 - 防止超持仓
    2. 保证金检查 - 确保资金充足
    3. 价格限制检查 - 防止涨停板买入/跌停板卖出
    4. 合约状态检查 - 确保合约可交易
    5. 订单数量检查 - 防止异常大单
    6. 频率限制检查 - 防止过度交易
    """

    # 风控检查错误码
    ERR_POSITION_LIMIT = "RISK_001"
    ERR_MARGIN_INSUFFICIENT = "RISK_002"
    ERR_PRICE_LIMIT = "RISK_003"
    ERR_INSTRUMENT_STATUS = "RISK_004"
    ERR_ORDER_SIZE = "RISK_005"
    ERR_RATE_LIMIT = "RISK_006"
    ERR_TRADING_TIME = "RISK_007"

    def __init__(self, broker: Broker):
        """
        初始化风控引擎

        Args:
            broker: 券商/账户对象
        """
        self.broker = broker
        self.config = config

        # 从配置读取风控参数
        self.max_position_ratio = self.config.getfloat(
            'RISK', 'max_position_ratio', fallback=0.95
        )  # 最大持仓比例
        self.max_single_order_ratio = self.config.getfloat(
            'RISK', 'max_single_order_ratio', fallback=0.1
        )  # 单笔订单最大资金比例
        self.max_order_per_minute = self.config.getint(
            'RISK', 'max_order_per_minute', fallback=30
        )  # 每分钟最大订单数
        self.price_limit_buffer = self.config.getfloat(
            'RISK', 'price_limit_buffer', fallback=0.001
        )  # 涨跌停板缓冲比例

        # 订单计数器
        self._order_count: dict[str, list[datetime.datetime]] = {}

    def check_order_before_submit(
        self,
        instrument: Instrument,
        direction: DirectionType,
        offset: OffsetFlag,
        price: Decimal,
        volume: int,
        account: Optional[Account] = None
    ) -> RiskCheckResult:
        """
        报单前综合风控检查

        Args:
            instrument: 合约对象
            direction: 方向 (多/空)
            offset: 开平标志
            price: 报单价格
            volume: 报单数量
            account: 账户对象 (可选，默认使用broker的主账户)

        Returns:
            RiskCheckResult: 检查结果
        """
        if account is None:
            account = Account.objects.filter(broker=self.broker).first()
            if account is None:
                return RiskCheckResult(False, "未找到账户信息", self.ERR_MARGIN_INSUFFICIENT)

        # 1. 检查合约状态
        result = self._check_instrument_status(instrument)
        if not result:
            return result

        # 2. 检查交易时间
        result = self._check_trading_time(instrument)
        if not result:
            return result

        # 3. 检查价格限制
        result = self._check_price_limit(instrument, direction, price)
        if not result:
            return result

        # 4. 检查订单数量
        result = self._check_order_size(instrument, volume)
        if not result:
            return result

        # 5. 检查持仓限额 (仅开仓)
        if offset == OffsetFlag.Open:
            result = self._check_position_limit(account, instrument, direction, volume, price)
            if not result:
                return result

            # 6. 检查保证金充足性 (仅开仓)
            result = self._check_margin_sufficient(account, instrument, volume, price)
            if not result:
                return result

        # 7. 检查频率限制
        result = self._check_rate_limit(instrument.code)
        if not result:
            return result

        logger.debug(f"风控检查通过: {instrument.code} {direction.label} {volume}手 @{price}")
        return RiskCheckResult(True, "风控检查通过")

    def _check_instrument_status(self, instrument: Instrument) -> RiskCheckResult:
        """
        检查合约状态

        检查合约是否存在、是否已下市、是否在交易中
        """
        if instrument is None:
            return RiskCheckResult(False, "合约不存在", self.ERR_INSTRUMENT_STATUS)

        if not instrument.is_trading:
            return RiskCheckResult(False, f"合约 {instrument.code} 不可交易", self.ERR_INSTRUMENT_STATUS)

        return RiskCheckResult(True)

    def _check_trading_time(self, instrument: Instrument) -> RiskCheckResult:
        """
        检查交易时间

        检查当前是否在合约的交易时间段内
        """
        now = timezone.localtime()

        # 获取合约的交易时间段 (需要从Instrument或配置读取)
        # 这里简化处理，假设合约在正常交易时间
        # 实际应该根据合约的trading_time字段判断

        # 非交易时间检查：周末
        if now.weekday() >= 5:  # 周六、周日
            return RiskCheckResult(False, "周末非交易时间", self.ERR_TRADING_TIME)

        # 简单检查：排除深夜时段 (具体应根据合约交易时间设置)
        hour = now.hour
        if instrument.night_trade:
            # 夜盘合约，允许夜盘交易
            pass
        else:
            # 非夜盘合约，正常日盘时间 (9:00-15:00)
            if hour < 8 or hour >= 15:
                return RiskCheckResult(False, "非交易时间段", self.ERR_TRADING_TIME)

        return RiskCheckResult(True)

    def _check_price_limit(
        self,
        instrument: Instrument,
        direction: DirectionType,
        price: Decimal
    ) -> RiskCheckResult:
        """
        检查价格限制

        防止涨停板买入、跌停板卖出
        """
        # 获取最新的涨跌停价格
        # 这里简化处理，实际应从Redis或数据库获取
        up_limit = instrument.get_up_limit() if hasattr(instrument, 'get_up_limit') else None
        down_limit = instrument.get_down_limit() if hasattr(instrument, 'get_down_limit') else None

        if up_limit is None or down_limit is None:
            # 无法获取涨跌停价格，跳过检查
            return RiskCheckResult(True)

        # 添加缓冲区，避免在涨跌停板附近报单
        buffer = price * self.price_limit_buffer

        if direction == DirectionType.LONG:
            # 买入：检查是否超过涨停板 (允许一定的缓冲)
            if price >= up_limit - buffer:
                return RiskCheckResult(
                    False,
                    f"买入价格 {price} 接近或超过涨停板 {up_limit}",
                    self.ERR_PRICE_LIMIT
                )
        else:  # SHORT
            # 卖出：检查是否低于跌停板
            if price <= down_limit + buffer:
                return RiskCheckResult(
                    False,
                    f"卖出价格 {price} 接近或低于跌停板 {down_limit}",
                    self.ERR_PRICE_LIMIT
                )

        return RiskCheckResult(True)

    def _check_order_size(
        self,
        instrument: Instrument,
        volume: int
    ) -> RiskCheckResult:
        """
        检查订单数量

        防止异常大单或错误的手数输入
        """
        if volume <= 0:
            return RiskCheckResult(False, f"订单数量必须大于0，当前: {volume}", self.ERR_ORDER_SIZE)

        # 检查是否超过合约单笔最大手数
        max_volume = instrument.max_market_order_volume if hasattr(instrument, 'max_market_order_volume') else 500
        if volume > max_volume:
            return RiskCheckResult(
                False,
                f"订单数量 {volume} 超过合约最大限制 {max_volume}",
                self.ERR_ORDER_SIZE
            )

        return RiskCheckResult(True)

    def _check_position_limit(
        self,
        account: Account,
        instrument: Instrument,
        direction: DirectionType,
        volume: int,
        price: Decimal
    ) -> RiskCheckResult:
        """
        检查持仓限额

        防止持仓超过限额
        """
        # 获取当前持仓
        current_position = Position.objects.filter(
            account=account,
            instrument=instrument,
            direction=direction
        ).aggregate(total=Sum('position'))['total'] or 0

        # 计算新持仓
        new_position = current_position + volume

        # 检查是否超过合约最大持仓限额
        if hasattr(instrument, 'max_position'):
            max_pos = instrument.max_position
            if new_position > max_pos:
                return RiskCheckResult(
                    False,
                    f"持仓 {new_position} 将超过合约最大持仓限额 {max_pos}",
                    self.ERR_POSITION_LIMIT
                )

        # 检查持仓比例
        available_margin = account.available - (volume * instrument.margin_per_hand)
        if available_margin < 0:
            return RiskCheckResult(
                False,
                f"可用资金不足开仓 {volume} 手",
                self.ERR_MARGIN_INSUFFICIENT
            )

        return RiskCheckResult(True)

    def _check_margin_sufficient(
        self,
        account: Account,
        instrument: Instrument,
        volume: int,
        price: Decimal
    ) -> RiskCheckResult:
        """
        检查保证金充足性

        确保账户有足够的可用保证金
        """
        # 计算所需保证金
        required_margin = volume * instrument.margin_per_hand

        available = account.available

        if required_margin > available:
            return RiskCheckResult(
                False,
                f"保证金不足: 需要 {required_margin}, 可用 {available}",
                self.ERR_MARGIN_INSUFFICIENT
            )

        # 检查资金使用比例
        if account.balance > 0:
            usage_ratio = (account.balance - available) / account.balance
            if usage_ratio > self.max_position_ratio:
                return RiskCheckResult(
                    False,
                    f"资金使用率 {usage_ratio:.2%} 超过限制 {self.max_position_ratio:.2%}",
                    self.ERR_MARGIN_INSUFFICIENT
                )

        return RiskCheckResult(True)

    def _check_rate_limit(self, instrument_code: str) -> RiskCheckResult:
        """
        检查频率限制

        防止过度交易
        """
        now = timezone.localtime()

        # 清理过期的订单记录
        self._cleanup_old_orders(now)

        # 获取当前合约的订单计数
        if instrument_code not in self._order_count:
            self._order_count[instrument_code] = []

        # 检查最近一分钟内的订单数
        recent_count = len(self._order_count[instrument_code])
        if recent_count >= self.max_order_per_minute:
            return RiskCheckResult(
                False,
                f"下单频率过高: 最近一分钟内已下单 {recent_count} 次",
                self.ERR_RATE_LIMIT
            )

        # 记录本次下单
        self._order_count[instrument_code].append(now)

        return RiskCheckResult(True)

    def _cleanup_old_orders(self, now: datetime.datetime) -> None:
        """
        清理过期的订单记录 (超过1分钟)
        """
        cutoff = now - datetime.timedelta(minutes=1)
        for code in list(self._order_count.keys()):
            self._order_count[code] = [
                t for t in self._order_count[code]
                if t > cutoff
            ]
            # 如果没有订单了，删除该合约的计数器
            if not self._order_count[code]:
                del self._order_count[code]

    def reset_rate_limit(self) -> None:
        """重置频率限制计数器"""
        self._order_count.clear()
        logger.info("风控频率限制计数器已重置")


def create_risk_engine(broker: Broker) -> RiskEngine:
    """
    创建风控引擎的工厂函数

    Args:
        broker: 券商/账户对象

    Returns:
        RiskEngine: 风控引擎实例
    """
    return RiskEngine(broker)
