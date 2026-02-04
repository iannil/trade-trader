# coding=utf-8
"""
钉钉通知模块 - DingTalk Notification Module

提供钉钉机器人通知功能：
- 文本消息
- Link消息
- Markdown消息
- ActionCard消息
"""
from typing import List, Optional, Dict
import logging
import hashlib
import hmac
import base64
import time
from urllib.parse import quote

import aiohttp
import requests

from trade_trader.notify import Alert, AlertLevel
from trade_trader.utils.read_config import config


logger = logging.getLogger('DingTalkNotifier')


class DingTalkNotifier:
    """
    钉钉通知器

    使用钉钉机器人发送通知消息

    文档: https://open.dingtalk.com/document/robots/custom-robot-access
    """

    # 消息类型
    MSG_TYPE_TEXT = "text"
    MSG_TYPE_LINK = "link"
    MSG_TYPE_MARKDOWN = "markdown"
    MSG_TYPE_ACTION_CARD = "actionCard"

    def __init__(self, webhook: Optional[str] = None, secret: Optional[str] = None):
        """
        初始化钉钉通知器

        Args:
            webhook: 钉钉机器人webhook地址
            secret: 钉钉机器人加签密钥
        """
        self.webhook = webhook or config.get('DINGTALK', 'webhook', fallback='')
        self.secret = secret or config.get('DINGTALK', 'secret', fallback='')

        # 是否启用
        self.enabled = bool(self.webhook)

        if not self.enabled:
            logger.info("钉钉通知未启用")

    def _get_sign_url(self) -> str:
        """
        获取带签名的URL

        如果配置了secret，使用加签方式
        """
        if not self.secret:
            return self.webhook

        timestamp = str(round(time.time() * 1000))
        secret_enc = self.secret.encode('utf-8')
        string_to_sign = f'{timestamp}\n{self.secret}'
        string_to_sign_enc = string_to_sign.encode('utf-8')

        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = quote(base64.b64encode(hmac_code))

        return f"{self.webhook}&timestamp={timestamp}&sign={sign}"

    def send_text(self, content: str, at_mobiles: Optional[List[str]] = None, at_all: bool = False) -> bool:
        """
        发送文本消息

        Args:
            content: 消息内容
            at_mobiles: @的手机号列表
            at_all: 是否@所有人

        Returns:
            bool: 是否成功发送
        """
        if not self.enabled:
            return False

        data = {
            "msgtype": self.MSG_TYPE_TEXT,
            "text": {
                "content": content
            }
        }

        if at_mobiles or at_all:
            data["at"] = {
                "atMobiles": at_mobiles or [],
                "isAtAll": at_all
            }

        return self._send(data)

    def send_link(self, text: str, title: str, url: str, pic_url: Optional[str] = None) -> bool:
        """
        发送Link消息

        Args:
            text: 消息内容
            title: 标题
            url: 跳转链接
            pic_url: 图片链接

        Returns:
            bool: 是否成功发送
        """
        if not self.enabled:
            return False

        data = {
            "msgtype": self.MSG_TYPE_LINK,
            "link": {
                "text": text,
                "title": title,
                "messageUrl": url
            }
        }

        if pic_url:
            data["link"]["picUrl"] = pic_url

        return self._send(data)

    def send_markdown(self, title: str, text: str) -> bool:
        """
        发送Markdown消息

        Args:
            title: 标题
            text: Markdown内容

        Returns:
            bool: 是否成功发送
        """
        if not self.enabled:
            return False

        data = {
            "msgtype": self.MSG_TYPE_MARKDOWN,
            "markdown": {
                "title": title,
                "text": text
            }
        }

        return self._send(data)

    def send_action_card(
        self,
        title: str,
        text: str,
        btn_orientation: str = "1",
        btns: Optional[List[Dict]] = None
    ) -> bool:
        """
        发送ActionCard消息

        Args:
            title: 标题
            text: 内容
            btn_orientation: 按钮排列方式 0-竖直 1-横向
            btns: 按钮列表 [{'title': '', 'actionURL': ''}]

        Returns:
            bool: 是否成功发送
        """
        if not self.enabled:
            return False

        data = {
            "msgtype": self.MSG_TYPE_ACTION_CARD,
            "actionCard": {
                "title": title,
                "text": text,
                "btnOrientation": btn_orientation
            }
        }

        if btns:
            data["actionCard"]["btns"] = btns

        return self._send(data)

    def send_alert(self, alert: Alert) -> bool:
        """
        发送告警消息

        Args:
            alert: 告警对象

        Returns:
            bool: 是否成功发送
        """
        if not self.enabled:
            return False

        # 根据告警级别决定是否发送
        if alert.level == AlertLevel.INFO:
            return False

        # 构建Markdown消息
        level_emoji = {
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🚨",
        }.get(alert.level, "ℹ️")

        title = f"{level_emoji} {alert.title}"
        text = f"""
## {alert.title}

**级别**: {alert.level.value}
**时间**: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
**来源**: {alert.source or '系统'}

### 详情

{alert.message}

---
*本消息由 Trade-Trader 自动发送*
"""

        return self.send_markdown(title, text)

    def _send(self, data: Dict) -> bool:
        """
        发送消息到钉钉

        Args:
            data: 消息数据

        Returns:
            bool: 是否成功发送
        """
        url = self._get_sign_url()

        try:
            response = requests.post(
                url,
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            result = response.json()

            if result.get('errcode') == 0:
                logger.info("钉钉消息发送成功")
                return True
            else:
                logger.error(f"钉钉消息发送失败: {result}")
                return False

        except Exception as e:
            logger.error(f"钉钉消息发送异常: {repr(e)}", exc_info=True)
            return False


class AsyncDingTalkNotifier:
    """
    异步钉钉通知器

    使用aiohttp发送消息，适合异步环境
    """

    def __init__(self, webhook: Optional[str] = None, secret: Optional[str] = None):
        """初始化异步钉钉通知器"""
        self.webhook = webhook or config.get('DINGTALK', 'webhook', fallback='')
        self.secret = secret or config.get('DINGTALK', 'secret', fallback='')
        self.enabled = bool(self.webhook)

    async def send_text_async(
        self,
        content: str,
        at_mobiles: Optional[List[str]] = None,
        at_all: bool = False
    ) -> bool:
        """异步发送文本消息"""
        if not self.enabled:
            return False

        data = {
            "msgtype": DingTalkNotifier.MSG_TYPE_TEXT,
            "text": {"content": content}
        }

        if at_mobiles or at_all:
            data["at"] = {
                "atMobiles": at_mobiles or [],
                "isAtAll": at_all
            }

        return await self._send_async(data)

    async def send_alert_async(self, alert: Alert) -> bool:
        """异步发送告警消息"""
        if not self.enabled:
            return False

        if alert.level == AlertLevel.INFO:
            return False

        level_emoji = {
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🚨",
        }.get(alert.level, "ℹ️")

        title = f"{level_emoji} {alert.title}"
        text = f"## {alert.title}\n\n**级别**: {alert.level.value}\n**时间**: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n{alert.message}"

        return await self.send_markdown_async(title, text)

    async def send_markdown_async(self, title: str, text: str) -> bool:
        """异步发送Markdown消息"""
        if not self.enabled:
            return False

        data = {
            "msgtype": DingTalkNotifier.MSG_TYPE_MARKDOWN,
            "markdown": {
                "title": title,
                "text": text
            }
        }

        return await self._send_async(data)

    async def _send_async(self, data: Dict) -> bool:
        """异步发送消息"""
        url = self._get_sign_url()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=data,
                    headers={'Content-Type': 'application/json'},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    result = await response.json()

                    if result.get('errcode') == 0:
                        return True
                    else:
                        logger.error(f"钉钉消息发送失败: {result}")
                        return False

        except Exception as e:
            logger.error(f"钉钉消息发送异常: {repr(e)}", exc_info=True)
            return False

    def _get_sign_url(self) -> str:
        """获取带签名的URL"""
        if not self.secret:
            return self.webhook

        import base64
        from urllib.parse import quote

        timestamp = str(round(time.time() * 1000))
        secret_enc = self.secret.encode('utf-8')
        string_to_sign = f'{timestamp}\n{self.secret}'
        string_to_sign_enc = string_to_sign.encode('utf-8')

        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = quote(base64.b64encode(hmac_code))

        return f"{self.webhook}&timestamp={timestamp}&sign={sign}"


def create_dingtalk_notifier(
    webhook: Optional[str] = None,
    secret: Optional[str] = None
) -> DingTalkNotifier:
    """创建钉钉通知器"""
    return DingTalkNotifier(webhook, secret)


def create_async_dingtalk_notifier(
    webhook: Optional[str] = None,
    secret: Optional[str] = None
) -> AsyncDingTalkNotifier:
    """创建异步钉钉通知器"""
    return AsyncDingTalkNotifier(webhook, secret)
