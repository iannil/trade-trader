# 系统架构文档

## 概述

Trader 是一个事件驱动的中国期货交易系统，采用 Redis 发布订阅模式进行实时消息传递，使用 Django ORM 进行数据持久化。

## 系统架构图

```mermaid
graph TB
    subgraph "入口层"
        A[main.py] --> B[初始化 Django]
        A --> C[配置三层日志]
        A --> D[启动 TradeStrategy]
    end

    subgraph "策略层"
        D --> E[BaseModule]
        E --> F[TradeStrategy]
    end

    subgraph "消息层"
        E --> G[Redis Pub/Sub]
        G --> H[CTP Request Channel]
        G --> I[CTP Response Channel]
        G --> J[Market Data Channel]
    end

    subgraph "执行层"
        H --> K[CTP Gateway]
        K --> L[交易所连接]
    end

    subgraph "数据层"
        F --> M[Django ORM]
        M --> N[MySQL Database]
    end

    subgraph "交易所"
        L --> O1[SHFE]
        L --> O2[DCE]
        L --> O3[CZCE]
        L --> O4[CFFEX]
        L --> O5[GFEX]
    end
```

## 启动流程

```mermaid
sequenceDiagram
    participant M as main.py
    participant D as Django
    participant L as Logger
    participant S as TradeStrategy
    participant B as BaseModule
    participant R as Redis

    M->>D: setup()
    M->>L: 初始化三层日志
    M->>L: 写入 PID 文件
    M->>S: TradeStrategy().run()
    S->>B: install()
    B->>B: _register_callback()
    B->>R: psubscribe(channel_router)
    B->>B: 启动 crontab 调度器
    B->>B: run_forever()
```

## Redis 消息通道

### 请求通道格式

```
MSG:CTP:REQ:{operation}
```

### 交易响应格式

```
MSG:CTP:RSP:TRADE:{broker_id}:{request_id}
```

### 行情响应格式

```
MSG:CTP:RSP:MARKET:{broker_id}:{request_id}
```

### 日志通道

```
MSG:LOG:WEIXIN
```

## 日志架构

```mermaid
graph LR
    A[Logger] --> B[FileHandler]
    A --> C[ConsoleHandler]
    A --> D[RedisHandler]
    B --> E[trader.log]
    C --> F[stdout]
    D --> G[Redis Pub/Sub]
```

## BaseModule 生命周期

```mermaid
stateDiagram-v2
    [*] --> Created: __init__()
    Created --> Installing: install()
    Installing --> Installed: psubscribe 成功
    Installed --> Running: run_forever()
    Running --> Running: 处理消息
    Running --> Uninstalling: stop()/KeyboardInterrupt
    Uninstalling --> [*]: uninstall()
```

## 回调注册机制

### 频道订阅

使用 `@RegisterCallback` 装饰器注册 Redis 频道回调：

```python
@RegisterCallback(channel='MSG:CTP:REQ:*')
async def on_request(self, channel, data):
    pass
```

### 定时任务

使用 `crontab` 参数注册定时任务：

```python
@RegisterCallback(crontab='*/5 * * * *')
async def periodic_task(self):
    pass
```

## 配置管理

配置文件位置：`~/.config/trade_trader/config.ini`

```mermaid
graph TD
    A[config.ini] --> B[MSG_CHANNEL]
    A --> C[TRADE]
    A --> D[REDIS]
    A --> E[MYSQL]
    A --> F[DASHBOARD]
    A --> G[LOG]
```

## 数据流向

```mermaid
flowchart LR
    A[交易所] --> B[CTP API]
    B --> C[Redis]
    C --> D[TradeStrategy]
    D --> E[信号生成]
    E --> F[订单执行]
    F --> G[Django ORM]
    G --> H[MySQL]
```

## 关键时序

1. **初始化**: Django setup → 日志配置 → PID 写入
2. **策略启动**: install() → 回调注册 → Redis 订阅
3. **消息处理**: Redis 消息 → 频道路由 → 回调函数
4. **关闭**: stop() → Redis 取消订阅 → 事件循环停止
