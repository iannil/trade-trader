import sys
import os
import datetime
import asyncio
import logging

from tqdm import tqdm
import django

logger = logging.getLogger(__name__)

from trade_trader.utils.read_config import get_dashboard_path  # noqa: E402

sys.path.append(get_dashboard_path())
os.environ["DJANGO_SETTINGS_MODULE"] = "dashboard.settings"
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django.setup()
from trade_trader.utils import (  # noqa: E402
    update_from_shfe, update_from_dce, update_from_czce, update_from_cffex,
    update_from_gfex, create_main_all, check_trading_day
)
from django.utils import timezone  # noqa: E402


async def fetch_bar(days=365):
    """
    Fetch historical bar data from all exchanges.

    Args:
        days: Number of days to look back from today (default: 365)
    """
    day_end = timezone.localtime()
    day_start = day_end - datetime.timedelta(days=days)
    tasks = []
    while day_start <= day_end:
        tasks.append(check_trading_day(day_start))
        day_start += datetime.timedelta(days=1)
    trading_days = []
    for f in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
        rst = await f
        trading_days.append(rst)
    tasks.clear()
    for day, trading in trading_days:
        if trading:
            tasks += [
                asyncio.create_task(update_from_shfe(day)),
                asyncio.create_task(update_from_dce(day)),
                asyncio.create_task(update_from_czce(day)),
                asyncio.create_task(update_from_cffex(day)),
                asyncio.create_task(update_from_gfex(day)),
            ]
    logger.info('task count: %d', len(tasks))
    for f in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
        await f


# Initialize main contract data
create_main_all()
# Uncomment to fetch historical data:
# asyncio.get_event_loop().run_until_complete(fetch_bar())
