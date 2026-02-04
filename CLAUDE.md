# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此代码库中工作时提供指导。

## 项目概述

这是一个中国期货交易系统（操盘大哥的交易组件），集成了五大中国期货交易所：SHFE（上期所）、DCE（大商所）、CZCE（郑商所）、CFFEX（中金所）和 GFEX（广期所）。系统采用事件驱动架构，使用 Redis 发布订阅进行实时消息传递，Django ORM 进行数据持久化。

## 详细文档

详细的技术文档位于 `docs/` 目录：

- [docs/README.md](docs/README.md) - 文档索引
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - 系统架构（含 Mermaid 图）
- [docs/MODULES.md](docs/MODULES.md) - 模块详解
- [docs/DATA_MODELS.md](docs/DATA_MODELS.md) - 数据模型说明
- [docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md) - 代码库映射
- [docs/CLEANUP_TODO.md](docs/CLEANUP_TODO.md) - 清理待办清单

## 安装和设置

1. 先安装 TA-Lib C 库，再安装 Python 依赖：

   ```bash
   pip install -r requirements.txt
   ```

2. 配置 MySQL 超时设置，在 `/etc/my.cnf.d/server.cnf` 中添加：

   ```ini
   [mysqld]
   wait_timeout=31536000
   interactive_timeout=31536000
   ```

3. 首次运行时，`config.ini` 会在 `~/.config/trade-trader/config.ini` 自动生成。编辑该文件配置：

   - `[DASHBOARD]` 节：Dashboard 项目路径（必需）
   - `[REDIS]` 节：Redis 连接设置
   - `[MYSQL]` 节：MySQL 数据库连接
   - `[MSG_CHANNEL]` 节：Redis 发布订阅频道模式
   - `[TRADE]` 节：交易参数
   - `[LOG]` 节：日志配置

## 运行应用

启动交易系统：

```bash
python -m trade_trader.main
```

入口点会初始化 Django、设置日志（文件、控制台和 Redis pub/sub）、写入 PID 文件，并运行 `trade_trader/strategy/brother2.py` 中的 `TradeStrategy`。

## 配置

配置文件位置：`~/.config/trade-trader/config.ini`

配置节说明：

- `[REDIS]`：Redis 连接设置
- `[MYSQL]`：数据库连接
- `[MSG_CHANNEL]`：Redis pub/sub 频道模式
- `[DASHBOARD]`：Django Dashboard 项目路径
- `[TRADE]`：命令超时和忽略的合约
- `[LOG]`：日志级别和格式
- `[QuantDL]`、`[Tushare]`：第三方 API 密钥

## 代码规范

- 大量中文注释和日志消息
- 使用 `ujson` 进行 JSON 解析（比标准 `json` 更快）
- 所有金融计算使用 `Decimal`
- 使用 `price_round()` 函数处理合约特定的价格精度
- 全面使用 async/await 模式配合 `asyncio`
- 错误码从 XML 加载的 `ctp_errors` 字典获取

## Dashboard 路径配置

Dashboard 项目路径通过 `config.ini` 的 `[DASHBOARD]` 节配置，或使用平台特定默认值。相关函数位于 `trade_trader/utils/read_config.py:83-93`。

## 快速参考

| 组件 | 文件 | 说明 |
|------|------|------|
| 入口点 | `trade_trader/main.py` | 系统启动 |
| 策略基类 | `trade_trader/strategy/__init__.py` | BaseModule |
| 主策略 | `trade_trader/strategy/brother2.py` | TradeStrategy |
| 配置 | `trade_trader/utils/read_config.py` | 配置管理 |
| 工具 | `trade_trader/utils/__init__.py` | 交易所数据 |
| 模型 | `panel/models.py` | Django ORM |
