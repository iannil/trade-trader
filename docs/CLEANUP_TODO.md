# 代码清理待办清单

## 已完成

- [x] 移除 `test/` 目录
- [x] 在 `config.ini` 模板中添加 `[DASHBOARD]` 节
- [x] 创建 `get_dashboard_path()` 辅助函数
- [x] 更新 `trade_trader/main.py` 使用配置化路径
- [x] 更新 `trade_trader/utils/fetch_data.py` 使用配置化路径
- [x] 移除 `fetch_data.py` 中的 `fetch_bar2()` 冗余函数
- [x] 清理 `fetch_data.py` 中注释掉的代码
- [x] 修复 `read_config.py` 中 `error.xml` 硬编码路径问题

## 待处理

### 高优先级

1. **完善 `fetch_data.py` 中的导入问题**
   - 文件引用了 `create_main_all` 等函数，但未定义
   - 需要从 `trader.utils.__init__` 导入

2. **添加 DCE_NAME_CODE 导入**
   - `update_from_dce()` 使用 `DCE_NAME_CODE` 但未导入
   - 位置: `trade_trader/utils/__init__.py`
   - 定义: `panel/const.py:112-136`

### 中优先级

3. **统一平台检测逻辑**
   - 当前多处使用 `sys.platform` 判断
   - 建议封装到 `read_config.py` 中

4. **完善 README.rst**
   - 当前为空文件
   - 添加项目描述、安装说明、使用方法

5. **添加类型注解**
   - `BaseModule` 类方法缺少类型注解
   - 回调函数签名不明确

6. **错误处理增强**
   - Redis 连接失败处理
   - Django 加载失败处理

### 低优先级

7. **日志级别配置统一**
   - `main.py` 中硬编码 `DEBUG`
   - 应从配置文件读取

8. **代码注释中文化**
   - 部分注释使用中文
   - 建议统一或添加英文文档

9. **单元测试**
   - 当前无有效测试
   - 建议添加 pytest 测试

## 技术债务

### 硬编码问题

| 位置 | 问题 | 建议 |
|------|------|------|
| `main.py:57` | `console_handler.setLevel('DEBUG')` | 从配置读取 |
| `read_config.py:88-93` | fallback 路径 | 考虑环境变量 |

### 弃用模式

| 模式 | 位置 | 替代方案 |
|------|------|---------|
| `asyncio.ensure_future` | `fetch_data.py` | `asyncio.create_task` (Python 3.7+) |

### 兼容性

- **Python 版本**: 未明确指定最低版本
- **Django 版本**: 依赖外部 dashboard 项目
- **依赖**: 使用 `aioredis` (Python 3.7+ 可用内置 redis)

## 代码质量指标

| 指标 | 当前 | 目标 |
|------|------|------|
| 测试覆盖率 | 0% | >80% |
| 类型注解覆盖率 | <10% | >60% |
| 文档覆盖率 | ~30% | >80% |
| 硬编码路径 | 4 处 → 0 处 | 0 |
