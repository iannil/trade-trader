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

import sys
import os
import logging
from typing import Final
import xml.etree.ElementTree as ET
import configparser
from appdirs import AppDirs

logger: Final[logging.Logger] = logging.getLogger(__name__)

config_example = """# trade-trader configuration file
[MSG_CHANNEL]
request_pattern = MSG:CTP:REQ:*
request_format = MSG:CTP:REQ:{}
trade_response_prefix = MSG:CTP:RSP:TRADE:
trade_response_format = MSG:CTP:RSP:TRADE:{}:{}
market_response_prefix = MSG:CTP:RSP:MARKET:
market_response_format = MSG:CTP:RSP:MARKET:{}:{}
weixin_log = MSG:LOG:WEIXIN

[TRADE]
command_timeout = 5
ignore_inst = WH,bb,JR,RI,RS,LR,PM,im

[REDIS]
host = 127.0.0.1
port = 6379
db = 0
encoding = utf-8

[MYSQL]
host = 127.0.0.1
port = 3306
db = QuantDB
user = quant
password = 123456

[DASHBOARD]
# Dashboard project path for Django ORM integration
# Use absolute path to the dashboard directory
# darwin (macOS): /Users/username/path/to/dashboard
# win32 (Windows): D:\\path\\to\\dashboard
# linux: /home/username/path/to/dashboard
path = /path/to/dashboard

[QuantDL]
api_key = 123456

[Tushare]
token = 123456

[RISK]
# 风控开关 (true/false)
enabled = true
# 最大持仓比例 (0.95 = 95%)
max_position_ratio = 0.95
# 单笔订单最大资金比例 (0.1 = 10%)
max_single_order_ratio = 0.1
# 每分钟最大订单数
max_order_per_minute = 30
# 涨跌停板缓冲比例 (0.001 = 0.1%)
price_limit_buffer = 0.001

[STOP]
# 默认止损百分比 (0.02 = 2%)
default_stop_loss_pct = 0.02
# 默认止盈百分比 (0.05 = 5%)
default_take_profit_pct = 0.05
# 止损检查间隔 (秒)
check_interval = 1

[LOG]
# Root logger level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
level = DEBUG
root_level = DEBUG
# File handler log level
file_level = DEBUG
# Console handler log level
console_level = DEBUG
# Redis/WeChat log level
flower_level = INFO
# Log message format
format = %(asctime)s %(name)s [%(levelname)s] %(message)s
# WeChat log message format (simplified)
weixin_format = [%(levelname)s] %(message)s
"""

app_dir: Final[AppDirs] = AppDirs('trade-trader')
config_file: Final[str] = os.path.join(app_dir.user_config_dir, 'config.ini')
if not os.path.exists(config_file):
    if not os.path.exists(app_dir.user_config_dir):
        os.makedirs(app_dir.user_config_dir)
    with open(config_file, 'wt') as f:
        f.write(config_example)
    logger.info('create config file: %s', config_file)

config: Final[configparser.ConfigParser] = configparser.ConfigParser(interpolation=None)
config.read(config_file)


def get_dashboard_path() -> str:
    """
    Get dashboard path from config, with fallback to platform-specific defaults.

    Note: The fallback paths are for backward compatibility only.
    Users should configure the dashboard path in config.ini under [DASHBOARD] section.

    Returns:
        The dashboard directory path.
    """
    if config.has_option('DASHBOARD', 'path'):
        configured_path = config.get('DASHBOARD', 'path')
        # Warn if still using placeholder path
        if configured_path == '/path/to/dashboard':
            logger.warning('Dashboard path is set to placeholder value. Please update config.ini with actual dashboard path.')
        return configured_path
    # Fallback to platform-specific defaults for backward compatibility
    # Deprecated: Users should configure this in config.ini
    if sys.platform == 'darwin':
        return '/Users/jeffchen/Documents/gitdir/dashboard'
    elif sys.platform == 'win32':
        return r'D:\github\dashboard'
    else:
        return '/root/gitee/dashboard'


def get_error_xml_path() -> str:
    """Get error.xml path relative to this file.

    Returns:
        The absolute path to the error.xml file.
    """
    return os.path.join(os.path.dirname(__file__), 'error.xml')


ctp_errors: dict[int, str] = {}
for error in ET.parse(get_error_xml_path()).getroot():
    ctp_errors[int(error.attrib['value'])] = error.attrib['prompt']
