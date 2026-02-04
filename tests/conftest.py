# coding=utf-8
"""
Pytest configuration and shared fixtures for trade-trader tests.
"""
import os
import sys
import asyncio
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from decimal import Decimal

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure Django settings before importing any Django models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'panel.settings')
import django  # noqa: E402
from django.conf import settings  # noqa: E402
if not settings.configured:
    settings.configure(
        DEBUG=True,
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        },
        INSTALLED_APPS=[
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'panel',
        ],
        SECRET_KEY='test-secret-key',
        USE_TZ=True,
    )
django.setup()


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_redis():
    """Mock Redis client fixture."""
    mock = MagicMock()
    mock.get = MagicMock(return_value=None)
    mock.set = MagicMock()
    mock.publish = MagicMock()
    mock.delete = MagicMock()
    mock.ping = MagicMock(return_value=True)
    return mock


@pytest.fixture
def mock_aioredis():
    """Mock aioredis client fixture."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock()
    mock.publish = AsyncMock()
    mock.delete = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    # pubsub() returns a pubsub object that needs async methods
    pubsub_mock = MagicMock()
    pubsub_mock.psubscribe = AsyncMock()
    pubsub_mock.punsubscribe = AsyncMock()
    pubsub_mock.close = AsyncMock()
    pubsub_mock.listen = MagicMock(return_value=[])  # Returns empty iterator
    mock.pubsub = MagicMock(return_value=pubsub_mock)
    return mock


@pytest.fixture
def mock_config():
    """Mock configuration fixture."""
    config = {
        'REDIS': {
            'host': 'localhost',
            'port': 6379,
            'db': 0,
        },
        'MYSQL': {
            'host': 'localhost',
            'port': 3306,
            'user': 'test',
            'password': 'test',
            'database': 'test_db',
        },
        'LOG': {
            'level': 'DEBUG',
        },
        'TRADE': {
            'ignore_inst': '',
        },
    }
    return config


@pytest.fixture
def sample_instrument_data():
    """Sample instrument data for testing."""
    return {
        'code': 'cu2501',
        'product_code': 'cu',
        'exchange': 'SHFE',
        'name': '铜',
        'volume_multiple': 5,
        'price_tick': Decimal('10'),
        'main_code': 'cu2501',
        'last_main': None,
        'up_limit_ratio': Decimal('0.08'),
        'down_limit_ratio': Decimal('0.08'),
    }


@pytest.fixture
def sample_daily_bar_data():
    """Sample daily bar data for testing."""
    return {
        'code': 'cu2501',
        'exchange': 'SHFE',
        'time': '2024-01-15',
        'open': Decimal('68500'),
        'high': Decimal('69000'),
        'low': Decimal('68200'),
        'close': Decimal('68800'),
        'settlement': Decimal('68750'),
        'volume': 125430,
        'open_interest': 185630,
    }


@pytest.fixture
def sample_tick_data():
    """Sample tick data for testing."""
    return {
        'code': 'cu2501',
        'exchange': 'SHFE',
        'last_price': Decimal('68850'),
        'bid_price1': Decimal('68840'),
        'ask_price1': Decimal('68860'),
        'bid_volume1': 10,
        'ask_volume1': 15,
        'volume': 5000,
        'open_interest': 185630,
        'time': '2024-01-15 10:30:00',
    }


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp ClientSession for testing external API calls."""
    with patch('aiohttp.ClientSession') as mock:
        session = AsyncMock()
        mock.return_value.__aenter__.return_value = session
        mock.return_value.__aexit__.return_value = None
        yield session
