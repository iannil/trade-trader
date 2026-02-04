# coding=utf-8
#
# Copyright 2016 timercrack
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
from __future__ import annotations

from typing import Any, Callable
import redis
import redis.asyncio as aioredis
import ujson as json

import time
import datetime
import logging
from collections import defaultdict
from django.utils import timezone
from croniter import croniter
import asyncio
from abc import ABCMeta

from trade_trader.utils.func_container import CallbackFunctionContainer
from trade_trader.utils.read_config import config

logger = logging.getLogger('BaseModule')


class BaseModule(CallbackFunctionContainer, metaclass=ABCMeta):
    """Base module for trading strategies with Redis pub/sub and crontab support."""

    io_loop: asyncio.AbstractEventLoop
    redis_client: aioredis.Redis
    raw_redis: redis.Redis[bytes]
    sub_client: aioredis.Redis.pubsub
    initialized: bool
    sub_tasks: list[asyncio.Task[Any]]
    sub_channels: list[str]
    channel_router: dict[str, Callable[[str, dict[str, Any]], Any]]
    crontab_router: dict[str, dict[str, Any]]
    datetime: datetime.datetime | None
    time: float | None
    loop_time: float | None

    def __init__(self) -> None:
        super().__init__()
        self.io_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.io_loop)
        self.redis_client = aioredis.from_url(
            f"redis://{config.get('REDIS', 'host', fallback='localhost')}:"
            f"{config.getint('REDIS', 'port', fallback=6379)}/{config.getint('REDIS', 'db', fallback=0)}",
            decode_responses=True)
        self.raw_redis = redis.Redis(
            host=config.get('REDIS', 'host', fallback='localhost'),
            port=config.getint('REDIS', 'port', fallback=6379),
            db=config.getint('REDIS', 'db', fallback=0),
            decode_responses=True)
        self.sub_client = self.redis_client.pubsub()
        self.initialized = False
        self.sub_tasks: list[asyncio.Task[Any]] = []
        self.sub_channels: list[str] = []
        self.channel_router: dict[str, Callable[[str, dict[str, Any]], Any]] = {}
        self.crontab_router: dict[str, dict[str, Any]] = defaultdict(dict)
        self.datetime: datetime.datetime | None = None
        self.time: float | None = None
        self.loop_time: float | None = None

    def _register_callback(self) -> None:
        """Register callback functions for channels and crontabs."""
        self.datetime = timezone.localtime()
        self.time = time.time()
        self.loop_time = self.io_loop.time()
        for fun_name, args in self.callback_fun_args.items():
            if 'crontab' in args:
                key = args['crontab']
                self.crontab_router[key]['func'] = getattr(self, fun_name)
                self.crontab_router[key]['iter'] = croniter(args['crontab'], self.datetime)
                self.crontab_router[key]['handle'] = None
            elif 'channel' in args:
                self.channel_router[args['channel']] = getattr(self, fun_name)

    def _get_next(self, key: str) -> float:
        """Calculate next scheduled time for crontab job."""
        return self.loop_time + (self.crontab_router[key]['iter'].get_next() - self.time)

    def _call_next(self, key: str) -> None:
        """Schedule next execution of crontab job."""
        if self.crontab_router[key]['handle'] is not None:
            self.crontab_router[key]['handle'].cancel()
        self.crontab_router[key]['handle'] = self.io_loop.call_at(
            self._get_next(key), self._call_next, key)
        self.io_loop.create_task(self.crontab_router[key]['func']())

    async def install(self) -> None:
        """Install the module, subscribing to channels and scheduling crontabs."""
        try:
            self._register_callback()
            await self.sub_client.psubscribe(*self.channel_router.keys())
            asyncio.run_coroutine_threadsafe(self._msg_reader(), self.io_loop)
            for key, cron_dict in self.crontab_router.items():
                if cron_dict['handle'] is not None:
                    cron_dict['handle'].cancel()
                cron_dict['handle'] = self.io_loop.call_at(
                    self._get_next(key), self._call_next, key)
            self.initialized = True
            logger.debug('%s plugin installed', type(self).__name__)
        except Exception as e:
            logger.error('%s plugin install failed: %s', type(self).__name__, repr(e), exc_info=True)

    async def uninstall(self) -> None:
        """Uninstall the module, cleaning up subscriptions and scheduled tasks."""
        try:
            await self.sub_client.punsubscribe()
            self.sub_tasks.clear()
            await self.sub_client.close()
            for key, cron_dict in self.crontab_router.items():
                if cron_dict['handle'] is not None:
                    cron_dict['handle'].cancel()
                    cron_dict['handle'] = None
            self.initialized = False
            logger.debug('%s plugin uninstalled', type(self).__name__)
        except Exception as e:
            logger.error('%s plugin uninstall failed: %s', type(self).__name__, repr(e), exc_info=True)

    async def _msg_reader(self) -> None:
        """Read messages from Redis pub/sub and dispatch to handlers."""
        async for msg in self.sub_client.listen():
            if msg['type'] == 'pmessage':
                channel = msg['channel']
                pattern = msg['pattern']
                data = json.loads(msg['data'])
                self.io_loop.create_task(self.channel_router[pattern](channel, data))
            elif msg['type'] == 'punsubscribe':
                break
        logger.debug('%s quit _msg_reader!', type(self).__name__)

    async def start(self) -> None:
        """Start the module."""
        await self.install()

    async def stop(self) -> None:
        """Stop the module."""
        await self.uninstall()

    def run(self) -> None:
        """Run the event loop."""
        try:
            self.io_loop.create_task(self.start())
            self.io_loop.run_forever()
        except KeyboardInterrupt:
            self.io_loop.run_until_complete(self.stop())
        except Exception as ee:
            logger.error('发生错误: %s', repr(ee), exc_info=True)
            self.io_loop.run_until_complete(self.stop())
        finally:
            logger.debug('程序已退出')


class MultiStrategyManager:
    """
    多策略管理器

    管理多个策略实例的并行运行、资源隔离和通信。
    """

    def __init__(self) -> None:
        self.strategies: dict[str, BaseModule] = {}
        self.strategy_status: dict[str, bool] = {}
        self.shared_context: dict[str, Any] = {}

    def register_strategy(self, name: str, strategy: BaseModule) -> None:
        """
        注册策略实例

        Args:
            name: 策略名称
            strategy: 策略实例
        """
        self.strategies[name] = strategy
        self.strategy_status[name] = False
        logger.info("注册策略: %s", name)

    def start_strategy(self, name: str) -> bool:
        """
        启动指定策略

        Args:
            name: 策略名称

        Returns:
            bool: 是否成功启动
        """
        if name not in self.strategies:
            logger.error("策略不存在: %s", name)
            return False

        if self.strategy_status.get(name, False):
            logger.warning("策略已在运行: %s", name)
            return False

        try:
            asyncio.create_task(self.strategies[name].start())
            self.strategy_status[name] = True
            logger.info("启动策略: %s", name)
            return True
        except Exception as e:
            logger.error("启动策略失败 %s: %s", name, repr(e), exc_info=True)
            return False

    def stop_strategy(self, name: str) -> bool:
        """
        停止指定策略

        Args:
            name: 策略名称

        Returns:
            bool: 是否成功停止
        """
        if name not in self.strategies:
            return False

        if not self.strategy_status.get(name, False):
            return True

        try:
            asyncio.create_task(self.strategies[name].stop())
            self.strategy_status[name] = False
            logger.info("停止策略: %s", name)
            return True
        except Exception as e:
            logger.error("停止策略失败 %s: %s", name, repr(e), exc_info=True)
            return False

    def start_all(self) -> None:
        """启动所有策略"""
        for name in self.strategies.keys():
            self.start_strategy(name)

    def stop_all(self) -> None:
        """停止所有策略"""
        for name in list(self.strategies.keys()):
            self.stop_strategy(name)

    def get_status(self, name: str | None = None) -> dict[str, bool]:
        """
        获取策略状态

        Args:
            name: 策略名称 (None=获取所有)

        Returns:
            dict[str, bool]: 策略状态
        """
        if name:
            return {name: self.strategy_status.get(name, False)}
        return self.strategy_status.copy()

    def set_shared_context(self, key: str, value: Any) -> None:
        """
        设置共享上下文

        Args:
            key: 键
            value: 值
        """
        self.shared_context[key] = value

    def get_shared_context(self, key: str, default: Any = None) -> Any:
        """
        获取共享上下文

        Args:
            key: 键
            default: 默认值

        Returns:
            Any: 值
        """
        return self.shared_context.get(key, default)
