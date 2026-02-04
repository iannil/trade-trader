# coding=utf-8
"""
告警管理器模块 - Alert Manager Module

提供统一的告警管理功能：
- 告警级别管理
- 告警去重
- 告警聚合
- 多渠道通知
"""
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
import logging

from django.utils import timezone

from panel.models import RiskAlert, RiskMonitor


logger = logging.getLogger('AlertManager')


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(Enum):
    """告警类型"""
    SYSTEM = "system"           # 系统异常
    CPU = "cpu"                # CPU告警
    MEMORY = "memory"           # 内存告警
    DISK = "disk"              # 磁盘告警
    NETWORK = "network"         # 网络告警
    REDIS_CONNECTION = "redis_connection"  # Redis连接
    MYSQL_CONNECTION = "mysql_connection"  # MySQL连接
    CTP_CONNECTION = "ctp_connection"      # CTP连接
    LATENCY = "latency"         # 延迟告警
    ORDER_REJECTED = "order_rejected"     # 订单被拒
    RISK_RATIO = "risk_ratio"   # 风险度告警
    POSITION_LIMIT = "position_limit"     # 持仓限额
    STOP_LOSS = "stop_loss"     # 止损触发
    STRATEGY_ERROR = "strategy_error"     # 策略错误


@dataclass
class Alert:
    """告警"""
    type: AlertType
    level: AlertLevel
    title: str
    message: str
    timestamp: datetime = None
    source: str = ""
    metadata: Dict[str, Any] = None
    sent: bool = False
    sent_methods: List[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = timezone.now()
        if self.metadata is None:
            self.metadata = {}
        if self.sent_methods is None:
            self.sent_methods = []

    def to_dict(self) -> Dict:
        return {
            'type': self.type.value,
            'level': self.level.value,
            'title': self.title,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'source': self.source,
            'metadata': self.metadata,
            'sent': self.sent,
        }

    def __str__(self) -> str:
        return f"[{self.level.value.upper()}] {self.title}: {self.message}"


class AlertManager:
    """
    告警管理器

    功能：
    1. 告警级别管理
    2. 告警去重
    3. 告警聚合
    4. 多渠道通知
    """

    def __init__(self):
        """初始化告警管理器"""
        self.alerts: List[Alert] = []
        self.alert_history: List[Alert] = []
        self.notifiers: Dict[str, Callable] = {}
        self.alert_rules: Dict[AlertType, Callable] = {}

        # 告警去重窗口 (时间窗口内相同类型告警只发送一次)
        self.dedup_window = timedelta(minutes=5)
        self.last_alert_time: Dict[AlertType, datetime] = {}

        # 告警聚合 (同一类型告警聚合后发送)
        self.aggregation_window = timedelta(minutes=1)
        self.pending_alerts: Dict[AlertType, List[Alert]] = defaultdict(list)

        # 统计
        self.alert_counts: Dict[str, Dict[AlertLevel, int]] = defaultdict(lambda: defaultdict(int))

    def register_notifier(self, name: str, notifier: Callable[[Alert], bool]):
        """
        注册通知渠道

        Args:
            name: 通知渠道名称
            notifier: 通知函数 (alert) -> bool
        """
        self.notifiers[name] = notifier
        logger.info(f"注册通知渠道: {name}")

    def unregister_notifier(self, name: str):
        """
        注销通知渠道

        Args:
            name: 通知渠道名称
        """
        if name in self.notifiers:
            del self.notifiers[name]
            logger.info(f"注销通知渠道: {name}")

    def register_rule(self, alert_type: AlertType, rule: Callable[[Alert], bool]):
        """
        注册告警规则

        Args:
            alert_type: 告警类型
            rule: 规则函数 (alert) -> bool (是否发送告警)
        """
        self.alert_rules[alert_type] = rule

    def send_alert(self, alert: Alert) -> bool:
        """
        发送告警

        Args:
            alert: 告警对象

        Returns:
            bool: 是否成功发送
        """
        # 检查告警规则
        if alert.type in self.alert_rules:
            if not self.alert_rules[alert.type](alert):
                return False

        # 去重检查
        now = timezone.now()
        if alert.type in self.last_alert_time:
            if now - self.last_alert_time[alert.type] < self.dedup_window:
                logger.debug(f"告警去重: {alert.type.value}")
                return False

        self.last_alert_time[alert.type] = now

        # 记录告警
        self.alerts.append(alert)
        self.alert_history.append(alert)
        self.alert_counts[alert.type.value][alert.level] += 1

        # 发送到各通知渠道
        success = False
        for name, notifier in self.notifiers.items():
            try:
                if notifier(alert):
                    alert.sent_methods.append(name)
                    success = True
                    logger.info(f"告警已通过 {name} 发送: {alert}")
            except Exception as e:
                logger.error(f"发送告警失败 ({name}): {repr(e)}")

        alert.sent = success

        # 保存到数据库
        self._save_to_database(alert)

        return success

    def send_alert_batch(self, alerts: List[Alert]) -> int:
        """
        批量发送告警

        Args:
            alerts: 告警列表

        Returns:
            int: 成功发送的数量
        """
        count = 0
        for alert in alerts:
            if self.send_alert(alert):
                count += 1
        return count

    def create_alert(
        self,
        alert_type: AlertType,
        level: AlertLevel,
        title: str,
        message: str,
        **kwargs
    ) -> Alert:
        """
        创建告警

        Args:
            alert_type: 告警类型
            level: 告警级别
            title: 标题
            message: 消息
            **kwargs: 其他元数据

        Returns:
            Alert: 告警对象
        """
        alert = Alert(
            type=alert_type,
            level=level,
            title=title,
            message=message,
            metadata=kwargs
        )
        return alert

    def quick_alert(
        self,
        alert_type: AlertType,
        level: AlertLevel,
        message: str
    ) -> bool:
        """
        快速发送告警

        Args:
            alert_type: 告警类型
            level: 告警级别
            message: 消息

        Returns:
            bool: 是否成功发送
        """
        alert = self.create_alert(
            alert_type=alert_type,
            level=level,
            title=f"{alert_type.value}告警",
            message=message
        )
        return self.send_alert(alert)

    def aggregate_alerts(self, alert_type: AlertType) -> Optional[Alert]:
        """
        聚合同类型告警

        Args:
            alert_type: 告警类型

        Returns:
            Optional[Alert]: 聚合后的告警
        """
        if alert_type not in self.pending_alerts:
            return None

        alerts = self.pending_alerts[alert_type]
        if not alerts:
            return None

        # 聚合规则: 使用最高级别
        max_level = max(a.level for a in alerts)
        count = len(alerts)

        # 获取最新告警的消息
        latest = max(alerts, key=lambda a: a.timestamp)

        aggregated = Alert(
            type=alert_type,
            level=max_level,
            title=f"{alert_type.value}告警聚合",
            message=f"{alert_type.value}告警在最近{self.aggregation_window.seconds}秒内触发{count}次。最新: {latest.message}",
            metadata={
                'count': count,
                'aggregated': True,
                'alert_ids': [a.metadata.get('id') for a in alerts if 'id' in a.metadata]
            }
        )

        # 清空待聚合告警
        self.pending_alerts[alert_type].clear()

        return aggregated

    def get_alert_history(
        self,
        alert_type: Optional[AlertType] = None,
        level: Optional[AlertLevel] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Alert]:
        """
        获取告警历史

        Args:
            alert_type: 告警类型过滤
            level: 级别过滤
            start_time: 开始时间
            end_time: 结束时间
            limit: 返回数量

        Returns:
            List[Alert]: 告警列表
        """
        filtered = self.alert_history

        if alert_type:
            filtered = [a for a in filtered if a.type == alert_type]
        if level:
            filtered = [a for a in filtered if a.level == level]
        if start_time:
            filtered = [a for a in filtered if a.timestamp >= start_time]
        if end_time:
            filtered = [a for a in filtered if a.timestamp <= end_time]

        # 按时间倒序
        filtered = sorted(filtered, key=lambda a: a.timestamp, reverse=True)

        return filtered[:limit]

    def get_alert_stats(self) -> Dict[str, Any]:
        """
        获取告警统计

        Returns:
            Dict: 告警统计信息
        """
        total = len(self.alert_history)
        by_level = defaultdict(int)
        by_type = defaultdict(int)

        for alert in self.alert_history:
            by_level[alert.level.value] += 1
            by_type[alert.type.value] += 1

        return {
            'total_alerts': total,
            'by_level': dict(by_level),
            'by_type': dict(by_type),
            'last_24h': len([a for a in self.alert_history if a.timestamp >= timezone.now() - timedelta(hours=24)]),
            'last_1h': len([a for a in self.alert_history if a.timestamp >= timezone.now() - timedelta(hours=1)]),
        }

    def _save_to_database(self, alert: Alert):
        """保存告警到数据库"""
        try:
            # 查找或创建RiskMonitor记录
            monitor = RiskMonitor.objects.filter(
                check_time=alert.timestamp
            ).first()

            if not monitor:
                # 创建一个临时监控记录
                from panel.models import Broker
                broker = Broker.objects.first()
                if broker:
                    monitor = RiskMonitor.objects.create(
                        broker=broker,
                        check_time=alert.timestamp,
                        balance=0,
                        available=0,
                        margin=0,
                        risk_ratio=0,
                        total_position_value=0,
                        total_profit=0,
                        long_position_count=0,
                        short_position_count=0,
                        risk_level='critical' if alert.level == AlertLevel.CRITICAL else 'warning',
                        warning_message=alert.message,
                        alert_sent=alert.sent,
                    )

            if monitor:
                RiskAlert.objects.create(
                    risk_monitor=monitor,
                    alert_time=alert.timestamp,
                    alert_type=alert.type.value,
                    alert_level=alert.level.value,
                    message=f"{alert.title}\n{alert.message}",
                    is_sent=alert.sent,
                    sent_method=','.join(alert.sent_methods) if alert.sent_methods else ''
                )
        except Exception as e:
            logger.error(f"保存告警到数据库失败: {repr(e)}")

    def clear_old_alerts(self, days: int = 7):
        """
        清理旧告警

        Args:
            days: 保留天数
        """
        cutoff = timezone.now() - timedelta(days=days)
        self.alert_history = [a for a in self.alert_history if a.timestamp >= cutoff]
        logger.info(f"清理了{days}天前的告警记录")


# 全局告警管理器实例
_global_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """获取全局告警管理器"""
    global _global_alert_manager
    if _global_alert_manager is None:
        _global_alert_manager = AlertManager()
    return _global_alert_manager


def create_alert_manager() -> AlertManager:
    """创建新的告警管理器"""
    return AlertManager()
