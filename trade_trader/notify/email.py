# coding=utf-8
"""
邮件通知模块 - Email Notification Module

提供邮件通知功能：
- SMTP邮件发送
- 告警邮件模板
- 邮件发送队列
"""
from typing import List, Optional
from datetime import datetime
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import smtplib
from jinja2 import Template

from trade_trader.notify import Alert, AlertLevel
from trade_trader.utils.read_config import config


logger = logging.getLogger('EmailNotifier')


class EmailNotifier:
    """
    邮件通知器

    功能：
    1. 发送告警邮件
    2. 发送日报/周报
    3. 邮件模板渲染
    """

    # 邮件模板
    ALERT_TEMPLATE = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; }
            .alert { padding: 15px; margin: 10px 0; border-radius: 5px; }
            .alert-critical { background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }
            .alert-error { background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }
            .alert-warning { background-color: #fff3cd; border: 1px solid #ffeeba; color: #856404; }
            .alert-info { background-color: #d1ecf1; border: 1px solid #bee5eb; color: #0c5460; }
            .timestamp { color: #6c757d; font-size: 0.9em; }
        </style>
    </head>
    <body>
        <div class="alert alert-{{ level }}">
            <h2>{{ title }}</h2>
            <p>{{ message }}</p>
            <p class="timestamp">时间: {{ timestamp }}</p>
            {% if source %}
            <p>来源: {{ source }}</p>
            {% endif %}
            {% if metadata %}
            <details>
                <summary>详细信息</summary>
                <pre>{{ metadata }}</pre>
            </details>
            {% endif %}
        </div>
    </body>
    </html>
    """

    DAILY_REPORT_TEMPLATE = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
            .positive { color: green; }
            .negative { color: red; }
        </style>
    </head>
    <body>
        <h1>{{ date }} 交易日报</h1>

        <h2>账户概览</h2>
        <table>
            <tr><th>项目</th><th>值</th></tr>
            <tr><td>静态权益</td><td>{{ balance:,.2f }}</td></tr>
            <tr><td>可用资金</td><td>{{ available:,.2f }}</td></tr>
            <tr><td>占用保证金</td><td>{{ margin:,.2f }}</td></tr>
            <tr><td>持仓盈亏</td><td class="{{ 'positive' if position_profit >= 0 else 'negative' }}">{{ position_profit:,.2f }}</td></tr>
        </table>

        <h2>今日交易</h2>
        <table>
            <tr><th>合约</th><th>方向</th><th>开仓价</th><th>平仓价</th><th>手数</th><th>盈亏</th></tr>
            {% for trade in trades %}
            <tr>
                <td>{{ trade.code }}</td>
                <td>{{ trade.direction }}</td>
                <td>{{ trade.entry_price }}</td>
                <td>{{ trade.exit_price or '-' }}</td>
                <td>{{ trade.volume }}</td>
                <td class="{{ 'positive' if trade.profit >= 0 else 'negative' }}">{{ trade.profit or '-' }}</td>
            </tr>
            {% endfor %}
        </table>

        <h2>当前持仓</h2>
        <table>
            <tr><th>合约</th><th>方向</th><th>持仓</th><th>均价</th><th>浮动盈亏</th></tr>
            {% for pos in positions %}
            <tr>
                <td>{{ pos.code }}</td>
                <td>{{ pos.direction }}</td>
                <td>{{ pos.position }}</td>
                <td>{{ pos.avg_price }}</td>
                <td class="{{ 'positive' if pos.profit >= 0 else 'negative' }}">{{ pos.profit }}</td>
            </tr>
            {% endfor %}
        </table>
    </body>
    </html>
    """

    def __init__(self):
        """初始化邮件通知器"""
        # 从配置读取SMTP设置
        self.smtp_host = config.get('EMAIL', 'smtp_host', fallback='smtp.gmail.com')
        self.smtp_port = config.getint('EMAIL', 'smtp_port', fallback=587)
        self.smtp_user = config.get('EMAIL', 'smtp_user', fallback='')
        self.smtp_password = config.get('EMAIL', 'smtp_password', fallback='')
        self.smtp_from = config.get('EMAIL', 'from', fallback='noreply@trader.local')
        self.smtp_use_tls = config.getboolean('EMAIL', 'use_tls', fallback=True)

        # 默认收件人
        self.default_recipients = config.get('EMAIL', 'recipients', fallback='').split(',')

        # 邮件发送队列
        self.queue: List[dict] = []

        # 是否启用
        self.enabled = config.getboolean('EMAIL', 'enabled', fallback=False)

        if not self.enabled:
            logger.info("邮件通知未启用")
        elif not self.smtp_user:
            logger.warning("邮件通知已启用但未配置SMTP用户")
            self.enabled = False

    def send_alert(self, alert: Alert) -> bool:
        """
        发送告警邮件

        Args:
            alert: 告警对象

        Returns:
            bool: 是否成功发送
        """
        if not self.enabled:
            return False

        # 根据告警级别决定是否发送
        if alert.level == AlertLevel.INFO:
            # INFO级别不发送邮件，避免骚扰
            return False

        # 渲染邮件内容
        template = Template(self.ALERT_TEMPLATE)
        content = template.render(
            level=alert.level.value,
            title=alert.title,
            message=alert.message,
            timestamp=alert.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            source=alert.source,
            metadata=alert.metadata
        )

        subject = f"[{alert.level.value.upper()}] {alert.title}"

        return self._send_email(
            to=self.default_recipients,
            subject=subject,
            html_content=content
        )

    def send_daily_report(
        self,
        date: datetime.date,
        balance: float,
        available: float,
        margin: float,
        position_profit: float,
        trades: List[dict],
        positions: List[dict]
    ) -> bool:
        """
        发送日报邮件

        Args:
            date: 日期
            balance: 静态权益
            available: 可用资金
            margin: 占用保证金
            position_profit: 持仓盈亏
            trades: 今日交易
            positions: 当前持仓

        Returns:
            bool: 是否成功发送
        """
        if not self.enabled:
            return False

        template = Template(self.DAILY_REPORT_TEMPLATE)
        content = template.render(
            date=date.strftime('%Y-%m-%d'),
            balance=balance,
            available=available,
            margin=margin,
            position_profit=position_profit,
            trades=trades,
            positions=positions
        )

        subject = f"交易日报 {date.strftime('%Y-%m-%d')}"

        return self._send_email(
            to=self.default_recipients,
            subject=subject,
            html_content=content
        )

    def _send_email(
        self,
        to: List[str],
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """
        发送邮件

        Args:
            to: 收件人列表
            subject: 邮件主题
            html_content: HTML内容
            text_content: 纯文本内容

        Returns:
            bool: 是否成功发送
        """
        if not to:
            logger.warning("没有指定邮件收件人")
            return False

        try:
            # 创建邮件
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = formataddr(('Trade-Trader', self.smtp_from))
            msg['To'] = ', '.join(to)

            # 添加纯文本部分
            if text_content:
                msg.attach(MIMEText(text_content, 'plain', 'utf-8'))

            # 添加HTML部分
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))

            # 连接SMTP服务器
            if self.smtp_use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)

            # 登录
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)

            # 发送
            server.sendmail(self.smtp_from, to, msg.as_string())
            server.quit()

            logger.info(f"邮件发送成功: {subject}")
            return True

        except Exception as e:
            logger.error(f"邮件发送失败: {repr(e)}", exc_info=True)
            return False

    def send_text(
        self,
        to: List[str],
        subject: str,
        message: str
    ) -> bool:
        """
        发送纯文本邮件

        Args:
            to: 收件人列表
            subject: 邮件主题
            message: 邮件内容

        Returns:
            bool: 是否成功发送
        """
        return self._send_email(to, subject, '', text_content=message)

    def queue_email(self, email_data: dict):
        """
        将邮件加入发送队列

        Args:
            email_data: 邮件数据
        """
        self.queue.append(email_data)

    def process_queue(self) -> int:
        """
        处理邮件队列

        Returns:
            int: 成功发送的数量
        """
        count = 0
        while self.queue:
            email_data = self.queue.pop(0)
            if self._send_email(**email_data):
                count += 1
        return count


def create_email_notifier() -> EmailNotifier:
    """创建邮件通知器"""
    return EmailNotifier()
