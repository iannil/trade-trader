# coding=utf-8
"""
系统监控模块 - System Monitor Module

提供系统监控功能：
- 进程监控
- 连接监控
- 延迟监控
- 指标采集
"""
from typing import Dict, List, Optional, Callable, Any
from decimal import Decimal
import logging
import psutil
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

import redis
import asyncio
from django.utils import timezone
from django.db import connection
from django.db.models import Q, Count, Sum

from panel.models import (
    Broker, Strategy, Order, Trade, Signal, RiskMonitor
)
from trade_trader.utils.read_config import config


logger = logging.getLogger('SystemMonitor')


class MetricType(Enum):
    """指标类型"""
    COUNTER = "counter"     # 计数器
    GAUGE = "gauge"         # 仪表
    HISTOGRAM = "histogram" # 直方图


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Metric:
    """监控指标"""
    name: str
    value: float
    timestamp: datetime
    type: MetricType
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'value': self.value,
            'timestamp': self.timestamp.isoformat(),
            'type': self.type.value,
            'tags': self.tags,
            'metadata': self.metadata
        }


@dataclass
class SystemStatus:
    """系统状态"""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_used: int
    memory_available: int
    disk_usage_percent: float
    process_count: int
    is_healthy: bool

    # 连接状态
    redis_connected: bool = False
    mysql_connected: bool = False
    ctp_connected: bool = False

    # 延迟
    redis_latency: Optional[float] = None
    mysql_latency: Optional[float] = None
    ctp_latency: Optional[float] = None

    # 交易状态
    pending_orders: int = 0
    open_positions: int = 0
    total_profit: float = 0

    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'memory_used': self.memory_used,
            'memory_available': self.memory_available,
            'disk_usage_percent': self.disk_usage_percent,
            'process_count': self.process_count,
            'is_healthy': self.is_healthy,
            'redis_connected': self.redis_connected,
            'mysql_connected': self.mysql_connected,
            'ctp_connected': self.ctp_connected,
            'redis_latency': self.redis_latency,
            'mysql_latency': self.mysql_latency,
            'ctp_latency': self.ctp_latency,
            'pending_orders': self.pending_orders,
            'open_positions': self.open_positions,
            'total_profit': self.total_profit,
        }


class SystemMonitor:
    """
    系统监控器

    功能：
    1. 监控进程状态
    2. 监控连接状态
    3. 监控延迟
    4. 采集性能指标
    5. 触发告警
    """

    # 告警阈值
    CPU_WARNING = 80
    CPU_CRITICAL = 95
    MEMORY_WARNING = 80
    MEMORY_CRITICAL = 95
    DISK_WARNING = 85
    DISK_CRITICAL = 95
    LATENCY_WARNING = 1000  # ms
    LATENCY_CRITICAL = 5000  # ms

    def __init__(self, broker: Broker):
        """
        初始化系统监控器

        Args:
            broker: 券商/账户对象
        """
        self.broker = broker
        self.metrics: List[Metric] = []
        self.alert_callbacks: List[Callable] = []

        # Redis客户端用于延迟测试
        self.redis_client = redis.StrictRedis(
            host=config.get('REDIS', 'host', fallback='localhost'),
            port=config.getint('REDIS', 'port', fallback=6379),
            db=config.getint('REDIS', 'db', fallback=0),
            decode_responses=True
        )

        # 监控间隔
        self.check_interval = config.getint('MONITOR', 'check_interval', fallback=60)

        # 上次检查时间
        self.last_check: Optional[datetime] = None

    def collect_system_status(self) -> SystemStatus:
        """
        采集系统状态

        Returns:
            SystemStatus: 系统状态
        """
        timestamp = timezone.now()

        # CPU和内存
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # 进程数
        process_count = len(psutil.pids())

        # 连接状态
        redis_connected, redis_latency = self._check_redis()
        mysql_connected, mysql_latency = self._check_mysql()

        # 交易状态
        pending_orders = Order.objects.filter(
            broker=self.broker,
            status__in=['1', '2', '3']  # 部成/未成/队列中
        ).count()

        from panel.models import Position
        open_positions = Position.objects.filter(
            broker=self.broker,
            position__gt=0
        ).count()

        total_profit = Trade.objects.filter(
            broker=self.broker,
            close_time__isnull=False
        ).aggregate(Sum('profit'))['profit__sum'] or 0

        # 健康状态判断
        is_healthy = (
            cpu_percent < self.CPU_CRITICAL and
            memory.percent < self.MEMORY_CRITICAL and
            disk.percent < self.DISK_CRITICAL and
            redis_connected and
            mysql_connected
        )

        status = SystemStatus(
            timestamp=timestamp,
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_used=memory.used,
            memory_available=memory.available,
            disk_usage_percent=disk.percent,
            process_count=process_count,
            is_healthy=is_healthy,
            redis_connected=redis_connected,
            mysql_connected=mysql_connected,
            redis_latency=redis_latency,
            mysql_latency=mysql_latency,
            pending_orders=pending_orders,
            open_positions=open_positions,
            total_profit=float(total_profit)
        )

        # 记录指标
        self._add_metric('cpu', cpu_percent, MetricType.GAUGE)
        self._add_metric('memory', memory.percent, MetricType.GAUGE)
        self._add_metric('disk', disk.percent, MetricType.GAUGE)
        if redis_latency:
            self._add_metric('redis_latency', redis_latency, MetricType.GAUGE)
        if mysql_latency:
            self._add_metric('mysql_latency', mysql_latency, MetricType.GAUGE)

        self.last_check = timestamp

        return status

    def _check_redis(self) -> tuple[bool, Optional[float]]:
        """检查Redis连接"""
        try:
            start = datetime.now()
            self.redis_client.ping()
            latency = (datetime.now() - start).total_seconds() * 1000
            return True, latency
        except Exception as e:
            logger.warning(f"Redis连接检查失败: {repr(e)}")
            return False, None

    def _check_mysql(self) -> tuple[bool, Optional[float]]:
        """检查MySQL连接"""
        try:
            start = datetime.now()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            latency = (datetime.now() - start).total_seconds() * 1000
            return True, latency
        except Exception as e:
            logger.warning(f"MySQL连接检查失败: {repr(e)}")
            return False, None

    def collect_trading_metrics(self) -> Dict[str, Any]:
        """
        采集交易指标

        Returns:
            Dict: 交易指标
        """
        today = timezone.localtime().date()

        # 今日订单统计
        today_orders = Order.objects.filter(
            broker=self.broker,
            send_time__date=today
        )

        orders_by_status = today_orders.values('status').annotate(
            count=Count('id')
        )

        status_counts = {item['status']: item['count'] for item in orders_by_status}

        # 成交率
        total_orders = today_orders.count()
        filled_orders = today_orders.filter(status='0').count()  # 全成
        fill_rate = (filled_orders / total_orders * 100) if total_orders > 0 else 0

        # 今日交易统计
        today_trades = Trade.objects.filter(
            broker=self.broker
        ).filter(
            Q(open_time__date=today) | Q(close_time__date=today)
        )

        # 平均延迟 (从下单到成交)
        avg_latency = 0
        completed_orders = Order.objects.filter(
            broker=self.broker,
            status='0',
            send_time__date=today
        )

        latency_values = []
        for order in completed_orders:
            if order.update_time and order.send_time:
                latency = (order.update_time - order.send_time).total_seconds()
                latency_values.append(latency)

        if latency_values:
            avg_latency = sum(latency_values) / len(latency_values)

        return {
            'date': today.isoformat(),
            'total_orders': total_orders,
            'filled_orders': filled_orders,
            'fill_rate': round(fill_rate, 2),
            'status_breakdown': status_counts,
            'avg_order_latency_ms': round(avg_latency * 1000, 2) if avg_latency else 0,
            'total_trades': today_trades.count(),
            'total_profit': float(today_trades.aggregate(Sum('profit'))['profit__sum'] or 0),
        }

    def collect_strategy_metrics(self, strategy: Strategy) -> Dict[str, Any]:
        """
        采集策略指标

        Args:
            strategy: 策略对象

        Returns:
            Dict: 策略指标
        """
        today = timezone.localtime().date()
        # yesterday = today - timedelta(days=1)

        # 今日信号
        today_signals = Signal.objects.filter(
            strategy=strategy,
            trigger_time__date=today
        )

        # 今日订单
        today_orders = Order.objects.filter(
            strategy=strategy,
            send_time__date=today
        )

        # 当前持仓
        from panel.models import Position
        current_positions = Position.objects.filter(
            strategy=strategy,
            position__gt=0
        )

        # 最近7日收益
        week_ago = today - timedelta(days=7)
        week_profit = Trade.objects.filter(
            strategy=strategy,
            close_time__date__gte=week_ago,
            close_time__isnull=False
        ).aggregate(Sum('profit'))['profit__sum'] or 0

        return {
            'strategy_id': strategy.id,
            'strategy_name': strategy.name,
            'date': today.isoformat(),
            'today_signals': today_signals.count(),
            'today_processed': today_signals.filter(processed=True).count(),
            'today_orders': today_orders.count(),
            'current_positions': current_positions.count(),
            'position_value': sum(
                p.position * p.avg_open_price * p.instrument.volume_multiple
                for p in current_positions
            ) if current_positions.exists() else 0,
            'week_profit': float(week_profit),
        }

    def check_and_alert(self, status: SystemStatus) -> List[Dict]:
        """
        检查状态并触发告警

        Args:
            status: 系统状态

        Returns:
            List[Dict]: 触发的告警列表
        """
        alerts = []

        # CPU告警
        if status.cpu_percent >= self.CPU_CRITICAL:
            alerts.append({
                'type': 'cpu',
                'level': AlertLevel.CRITICAL,
                'message': f"CPU使用率过高: {status.cpu_percent:.1f}%",
                'value': status.cpu_percent,
            })
        elif status.cpu_percent >= self.CPU_WARNING:
            alerts.append({
                'type': 'cpu',
                'level': AlertLevel.WARNING,
                'message': f"CPU使用率告警: {status.cpu_percent:.1f}%",
                'value': status.cpu_percent,
            })

        # 内存告警
        if status.memory_percent >= self.MEMORY_CRITICAL:
            alerts.append({
                'type': 'memory',
                'level': AlertLevel.CRITICAL,
                'message': f"内存使用率过高: {status.memory_percent:.1f}%",
                'value': status.memory_percent,
            })
        elif status.memory_percent >= self.MEMORY_WARNING:
            alerts.append({
                'type': 'memory',
                'level': AlertLevel.WARNING,
                'message': f"内存使用率告警: {status.memory_percent:.1f}%",
                'value': status.memory_percent,
            })

        # 磁盘告警
        if status.disk_usage_percent >= self.DISK_CRITICAL:
            alerts.append({
                'type': 'disk',
                'level': AlertLevel.CRITICAL,
                'message': f"磁盘使用率过高: {status.disk_usage_percent:.1f}%",
                'value': status.disk_usage_percent,
            })
        elif status.disk_usage_percent >= self.DISK_WARNING:
            alerts.append({
                'type': 'disk',
                'level': AlertLevel.WARNING,
                'message': f"磁盘使用率告警: {status.disk_usage_percent:.1f}%",
                'value': status.disk_usage_percent,
            })

        # Redis连接告警
        if not status.redis_connected:
            alerts.append({
                'type': 'redis_connection',
                'level': AlertLevel.CRITICAL,
                'message': "Redis连接失败",
                'value': 0,
            })
        elif status.redis_latency and status.redis_latency >= self.LATENCY_CRITICAL:
            alerts.append({
                'type': 'redis_latency',
                'level': AlertLevel.CRITICAL,
                'message': f"Redis延迟过高: {status.redis_latency:.0f}ms",
                'value': status.redis_latency,
            })

        # MySQL连接告警
        if not status.mysql_connected:
            alerts.append({
                'type': 'mysql_connection',
                'level': AlertLevel.CRITICAL,
                'message': "MySQL连接失败",
                'value': 0,
            })

        # 执行回调
        for alert in alerts:
            for callback in self.alert_callbacks:
                try:
                    callback(alert)
                except Exception as e:
                    logger.error(f"告警回调失败: {repr(e)}")

        return alerts

    def add_alert_callback(self, callback: Callable[[Dict], None]):
        """
        添加告警回调

        Args:
            callback: 告警回调函数
        """
        self.alert_callbacks.append(callback)

    def _add_metric(self, name: str, value: float, type: MetricType, tags: Optional[Dict] = None):
        """添加指标"""
        metric = Metric(
            name=name,
            value=value,
            timestamp=timezone.now(),
            type=type,
            tags=tags or {}
        )
        self.metrics.append(metric)

        # 保持最近1000条指标
        if len(self.metrics) > 1000:
            self.metrics = self.metrics[-1000:]

    def get_metrics(self, name: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """
        获取指标

        Args:
            name: 指标名称 (None=全部)
            limit: 返回数量

        Returns:
            List[Dict]: 指标列表
        """
        if name:
            filtered = [m for m in self.metrics if m.name == name]
        else:
            filtered = self.metrics

        return [m.to_dict() for m in filtered[-limit:]]

    def save_to_database(self, status: SystemStatus):
        """
        保存状态到数据库

        Args:
            status: 系统状态
        """
        try:
            # 获取策略
            strategies = Strategy.objects.filter(broker=self.broker)

            for strategy in strategies:
                RiskMonitor.objects.create(
                    broker=self.broker,
                    strategy=strategy,
                    check_time=status.timestamp,
                    balance=status.total_profit + 1000000,  # 简化处理
                    available=1000000 - status.total_profit,  # 简化处理
                    margin=0,
                    risk_ratio=0.1,  # 简化处理
                    total_position_value=0,
                    total_profit=Decimal(str(status.total_profit)),
                    long_position_count=status.open_positions // 2,
                    short_position_count=status.open_positions - status.open_positions // 2,
                    risk_level='safe' if status.is_healthy else 'warning',
                    warning_message='' if status.is_healthy else '系统资源紧张',
                    alert_sent=False,
                    active_stop_orders=0,
                    triggered_stops_today=0,
                )
        except Exception as e:
            logger.error(f"保存监控状态失败: {repr(e)}")

    async def run_monitoring_loop(self):
        """运行监控循环"""
        while True:
            try:
                status = self.collect_system_status()
                alerts = self.check_and_alert(status)

                if alerts:
                    logger.warning(f"触发 {len(alerts)} 个告警")

                # 每小时保存一次到数据库
                if not self.last_check or (status.timestamp - self.last_check).seconds >= 3600:
                    self.save_to_database(status)

            except Exception as e:
                logger.error(f"监控循环错误: {repr(e)}", exc_info=True)

            await asyncio.sleep(self.check_interval)


def create_system_monitor(broker: Broker) -> SystemMonitor:
    """
    创建系统监控器的工厂函数

    Args:
        broker: 券商/账户对象

    Returns:
        SystemMonitor: 系统监控器实例
    """
    return SystemMonitor(broker)
