# coding=utf-8
"""
Unit tests for trade_trader.strategy.BaseModule class.
"""
import pytest
from unittest.mock import patch


@pytest.mark.unit
class TestBaseModule:
    """Tests for BaseModule abstract base class."""

    def test_basemodule_initialization(self):
        """Test BaseModule initializes correctly."""
        from trade_trader.strategy import BaseModule

        # BaseModule is abstract, so we need to create a concrete subclass
        class ConcreteModule(BaseModule):
            async def process_tick(self, channel, data):
                pass

        module = ConcreteModule()

        assert module.initialized is False
        assert len(module.sub_tasks) == 0
        assert len(module.sub_channels) == 0
        assert module.io_loop is not None

    def test_basemodule_registers_callbacks(self):
        """Test _register_callback sets up channel and crontab routers."""
        from trade_trader.strategy import BaseModule

        class ConcreteModule(BaseModule):
            async def process_tick(self, channel, data):
                pass

        module = ConcreteModule()
        module._register_callback()

        # After registration, datetime, time, and loop_time should be set
        assert module.datetime is not None
        assert module.time is not None
        assert module.loop_time is not None

    @pytest.mark.asyncio
    async def test_basemodule_install_uninstall(self, mock_aioredis):
        """Test BaseModule install and uninstall methods."""
        from trade_trader.strategy import BaseModule

        class ConcreteModule(BaseModule):
            async def process_tick(self, channel, data):
                pass

        # Patch the redis client creation
        with patch('redis.asyncio.from_url', return_value=mock_aioredis):
            with patch('redis.StrictRedis'):
                module = ConcreteModule()
                await module.install()
                assert module.initialized is True

                await module.uninstall()
                assert module.initialized is False

    def test_get_next_calculates_correct_time(self):
        """Test _get_next calculates the next scheduled time correctly."""
        from unittest.mock import MagicMock

        from trade_trader.strategy import BaseModule
        from datetime import datetime

        class ConcreteModule(BaseModule):
            async def process_tick(self, channel, data):
                pass

        module = ConcreteModule()
        module.datetime = datetime(2024, 1, 15, 10, 0, 0)
        module.time = 1705300800.0  # Mock timestamp
        module.loop_time = 100.0

        # Mock croniter
        mock_iter = MagicMock()
        mock_iter.get_next.return_value = 1705300860.0  # 60 seconds later
        module.crontab_router['test'] = {'iter': mock_iter, 'func': MagicMock(), 'handle': None}

        result = module._get_next('test')
        # result = loop_time + (next_cron - current_time)
        # result = 100.0 + (1705300860.0 - 1705300800.0)
        # result = 100.0 + 60.0 = 160.0
        assert result == 160.0


@pytest.mark.unit
class TestCallbackDecorator:
    """Tests for the callback decorator functionality."""

    def test_callback_decorator_registers_function(self):
        """Test that the @RegisterCallback decorator properly registers functions."""
        from trade_trader.utils.func_container import CallbackFunctionContainer, RegisterCallback

        class TestContainer(CallbackFunctionContainer):
            @RegisterCallback(channel='test:channel')
            async def test_handler(self, channel, data):
                return data

        container = TestContainer()

        assert 'test_handler' in container.callback_fun_args
        assert container.callback_fun_args['test_handler']['channel'] == 'test:channel'
        assert hasattr(container, 'test_handler')

    def test_crontab_decorator_registers_function(self):
        """Test that the @RegisterCallback decorator with crontab properly registers functions."""
        from trade_trader.utils.func_container import CallbackFunctionContainer, RegisterCallback

        class TestContainer(CallbackFunctionContainer):
            @RegisterCallback(crontab='*/5 * * * *')
            async def periodic_task(self):
                return "done"

        container = TestContainer()

        assert 'periodic_task' in container.callback_fun_args
        assert container.callback_fun_args['periodic_task']['crontab'] == '*/5 * * * *'
        assert hasattr(container, 'periodic_task')
