import sys
import os
import datetime
import asyncio
import pytz

from tqdm import tqdm
import django

from trade_trader.utils.read_config import get_dashboard_path

sys.path.append(get_dashboard_path())
os.environ["DJANGO_SETTINGS_MODULE"] = "dashboard.settings"
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django.setup()
from trade_trader.utils import is_trading_day, update_from_shfe, update_from_dce, update_from_czce, update_from_cffex, \
    create_main_all, check_trading_day
from django.utils import timezone


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
                asyncio.ensure_future(update_from_shfe(day)),
                asyncio.ensure_future(update_from_dce(day)),
                asyncio.ensure_future(update_from_czce(day)),
                asyncio.ensure_future(update_from_cffex(day)),
            ]
    print('task len=', len(tasks))
    for f in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
        await f


# Initialize main contract data
create_main_all()
# Uncomment to fetch historical data:
# asyncio.get_event_loop().run_until_complete(fetch_bar())
