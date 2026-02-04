Trade-Trader: 中国期货交易系统
================================

一个集成了五大中国期货交易所的专业期货交易系统，支持实时行情、策略执行、风险控制和数据分析。

.. image:: https://img.shields.io/badge/python-3.8+-blue.svg
.. image:: https://img.shields.io/badge/license-Apache%202.0-green.svg

功能特性
--------

* **多交易所支持**: 上期所(SHFE)、大商所(DCE)、郑商所(CZCE)、中金所(CFFEX)、广期所(GFEX)
* **实时行情**: Redis Pub/Sub 消息传递，毫秒级行情更新
* **策略执行**: 事件驱动架构，支持多策略并行运行
* **账户管理**: 实时资金查询、持仓跟踪、净值计算
* **风险控制**: 涨跌停检查、持仓限额、保证金验证
* **数据持久化**: Django ORM + MySQL，完整的历史数据存储
* **日志系统**: 文件/控制台/Redis 三层日志

快速开始
--------

安装依赖
~~~~~~~~

首先安装 TA-Lib C 库：

**macOS**:

.. code-block:: bash

    brew install ta-lib

**Linux**:

.. code-block:: bash

    wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
    tar -xzf ta-lib-0.4.0-src.tar.gz
    cd ta-lib/
    ./configure --prefix=/usr
    make
    sudo make install

**Windows**: 下载预编译的 whl 文件 from https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib

然后安装 Python 依赖：

.. code-block:: bash

    pip install -r requirements.txt

配置 MySQL
~~~~~~~~~

编辑 ``/etc/my.cnf.d/server.cnf`` 添加以下配置以避免超时：

.. code-block:: ini

    [mysqld]
    wait_timeout=31536000
    interactive_timeout=31536000

配置系统
~~~~~~~~

首次运行时，配置文件会自动生成于 ``~/.config/trade-trader/config.ini``。

编辑配置文件，必须配置以下节：

**[DASHBOARD]** - Dashboard 项目路径 (必需):

.. code-block:: ini

    [DASHBOARD]
    path = /absolute/path/to/your/dashboard

**[REDIS]** - Redis 连接设置:

.. code-block:: ini

    [REDIS]
    host = 127.0.0.1
    port = 6379
    db = 0

**[MYSQL]** - 数据库连接:

.. code-block:: ini

    [MYSQL]
    host = 127.0.0.1
    port = 3306
    db = QuantDB
    user = your_user
    password = your_password

**[LOG]** - 日志配置:

.. code-block:: ini

    [LOG]
    root_level = DEBUG
    file_level = DEBUG
    console_level = INFO
    flower_level = INFO

运行系统
~~~~~~~~

.. code-block:: bash

    python -m trade_trader.main

系统将初始化 Django、设置三层日志、写入 PID 文件，并启动交易策略。

项目结构
~~~~~~~~

.. code-block:: text

    trade-trader/
    ├── docs/                    # 详细文档
    │   ├── README.md           # 文档索引
    │   ├── ARCHITECTURE.md     # 系统架构
    │   ├── MODULES.md          # 模块详解
    │   ├── DATA_MODELS.md      # 数据模型
    │   ├── CODEBASE_MAP.md     # 代码映射
    │   └── CLEANUP_TODO.md     # 清理待办
    ├── panel/                   # Django 数据模型
    │   ├── models.py           # ORM 模型定义
    │   └── const.py            # 常量定义
    ├── tests/                   # 测试文件
    │   ├── unit/               # 单元测试
    │   └── integration/        # 集成测试
    ├── trade_trader/            # 主程序包
    │   ├── main.py             # 程序入口
    │   ├── strategy/           # 交易策略
    │   │   ├── __init__.py     # BaseModule 基类
    │   │   └── brother2.py     # 主策略实现
    │   └── utils/              # 工具模块
    │       ├── __init__.py     # 核心工具函数
    │       ├── fetch_data.py   # 数据获取脚本
    │       ├── read_config.py  # 配置管理
    │       └── my_logger.py    # 日志工具
    ├── requirements.txt         # Python 依赖
    ├── pytest.ini              # pytest 配置
    └── README.rst              # 本文件

运行测试
~~~~~~~~

.. code-block:: bash

    pytest

带覆盖率报告：

.. code-block:: bash

    pytest --cov=trade_trader --cov-report=html

详细文档
--------

更多详细信息请参阅 `docs/` 目录下的文档：

* `docs/ARCHITECTURE.md` - 系统架构设计（含 Mermaid 图）
* `docs/MODULES.md` - 各模块详细说明
* `docs/DATA_MODELS.md` - 数据模型完整说明
* `docs/CODEBASE_MAP.md` - 代码导航

技术规范
--------

* **事件驱动**: 使用 Redis Pub/Sub 进行模块间通信
* **异步处理**: 全面使用 async/await 模式
* **金融计算**: 所有价格、金额使用 Decimal 类型
* **精度处理**: 使用 ``price_round()`` 处理合约特定价格精度
* **JSON 解析**: 使用 ujson 获取更高性能

开发路线图
----------

Phase 0: 技术债务清理 ✅
  - 修复导入问题
  - 添加类型注解
  - 建立测试框架

Phase 1: 风控增强 (进行中)
  - 事前风控引擎
  - 止损止盈引擎
  - 风险监控看板

Phase 2: 回测系统
  - 回测框架
  - 绩效分析
  - 参数优化

Phase 3: 多策略框架
  - 策略管理器
  - 策略隔离
  - 策略组合

Phase 4: 监控告警
  - 系统监控
  - 告警系统
  - 性能指标

Phase 5: 数据分析增强
  - 技术指标库
  - 分钟K线
  - 报表生成

Phase 6: 高级交易功能
  - 条件单
  - 算法交易
  - 换月优化

许可证
-------

Apache License 2.0

贡献
----

欢迎提交 Issue 和 Pull Request。

参考平台
---------

* 文华财经 - 风控、条件单
* 易盛 - 算法交易、回测
* MultiCharts - 技术指标
* TradingView - 图表分析
* vn.py - 事件驱动架构
