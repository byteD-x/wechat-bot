# 使用手册

本文档负责承载详细的使用、配置、运行与排障说明。README 只保留仓库首页所需的高层信息，这份文档负责逐步操作。

## 目录

- [1. 环境要求](#1-环境要求)
- [2. 安装依赖](#2-安装依赖)
- [3. 首次配置](#3-首次配置)
- [4. 启动前检查](#4-启动前检查)
- [5. 启动方式](#5-启动方式)
- [6. 验证是否正常工作](#6-验证是否正常工作)
- [7. LangChain / RAG 配置](#7-langchain--rag-配置)
- [8. 配置说明](#8-配置说明)
- [9. 常见问题](#9-常见问题)
- [10. 开发与测试](#10-开发与测试)

## 1. 环境要求

运行前请确认：

- Windows 10 或 Windows 11
- 微信 PC `3.9.12.51`
- Python `3.9+`
- Node.js `16+`
- 微信客户端已登录

限制：

- 当前项目不支持微信 `4.x`
- 不支持 Linux / macOS 直接运行微信自动化
- 运行时需要保持微信客户端处于可访问状态

## 2. 安装依赖

### 2.1 克隆仓库

```bash
git clone https://github.com/byteD-x/wechat-bot.git
cd wechat-bot
```

### 2.2 安装 Python 依赖

```bash
pip install -r requirements.txt
```

这一阶段会安装：

- Quart / Hypercorn
- WCFerry 主链路依赖，以及 wxauto 遗留兼容依赖
- ChromaDB
- LangChain / LangGraph / LangSmith
- `watchdog`
- 测试依赖

可选依赖：

- 如需启用本地 `Cross-Encoder` 精排，额外安装 `sentence-transformers`

```bash
pip install sentence-transformers
```

说明：

- 该依赖不是默认必需项。
- 只有配置了本地模型目录时才会启用，不会自动联网下载模型。

### 2.3 安装桌面端依赖

```bash
npm install
```

这一阶段会安装 Electron 桌面端依赖。

## 3. 首次配置

推荐优先使用桌面界面配置。

### 3.1 打开桌面设置页

```bash
npm run dev
```

### 3.2 配置模型

在设置页里完成：

1. 选择一个模型预设
2. 填写 API Key
3. 选择模型名称
4. 点击测试连接
5. 保存配置

### 3.3 配置文件优先级

运行时主要读取以下配置来源：

1. `data/config_override.json`
2. `data/api_keys.py`
3. `prompt_overrides.py`
4. `backend/config.py`

建议：

- 默认配置放在 `backend/config.py`
- 真实密钥放在 `data/api_keys.py`
- 界面保存产生的覆盖写入 `data/config_override.json`

## 4. 启动前检查

运行环境自检：

```bash
python run.py check
```

建议至少确认：

- Python 依赖安装完成
- Node.js / Electron 依赖安装完成
- 微信版本为 `3.9.12.51`
- 配置文件可读

## 5. 启动方式

### 5.1 桌面模式

```bash
npm run dev
```

适合：

- 在 GUI 中配置参数
- 查看状态与日志
- 通过仪表盘观察健康监控和启动进度

### 5.2 无头机器人模式

```bash
python run.py start
```

适合：

- 已完成配置
- 只需要机器人主循环
- 不需要桌面控制台

### 5.3 Web API 模式

```bash
python run.py web
```

适合：

- 单独运行后端 API
- 调试接口
- 与 Electron 或外部控制端联动

## 6. 验证是否正常工作

建议按以下顺序验证：

1. 打开设置页，确认当前预设和 Key 已配置。
2. 访问仪表盘，确认启动状态、健康检查和系统指标正常。
3. 给允许回复的联系人发送一条简单文本。
4. 查看 `data/logs/bot.log`。
5. 检查 API `/api/status`、`/api/config` 和 `/api/metrics`。

如需快速观察运行状态，重点看：

- `/api/status.startup`
- `/api/status.diagnostics`
- `/api/status.health_checks`
- `/api/status.system_metrics`
- `/api/metrics`

如果没有回复，优先检查：

- 微信是否仍是 `3.9.12.51`
- 当前会话是否被白名单或过滤规则限制
- API Key 是否有效
- 激活预设是否可连通
- 传输后端是否已连接

## 7. LangChain / RAG 配置

### 7.1 LangChain Runtime

`agent` 分区用于控制当前主运行时。常用字段：

```python
"agent": {
    "enabled": True,
    "streaming_enabled": True,
    "graph_mode": "state_graph",
    "retriever_top_k": 3,
    "retriever_score_threshold": 1.0,
    "retriever_rerank_mode": "lightweight",
    "retriever_cross_encoder_model": "",
    "retriever_cross_encoder_device": "",
    "embedding_cache_ttl_sec": 300.0,
    "background_fact_extraction_enabled": True,
    "emotion_fast_path_enabled": True,
    "langsmith_enabled": False,
    "langsmith_project": "wechat-chat",
}
```

建议：

- 初次使用保持默认。
- 性能调优时优先调整 `retriever_top_k`、阈值、精排模式和缓存 TTL。
- 开启 LangSmith 前先确认你接受外部 tracing。

### 7.2 运行期向量记忆

相关开关位于 `bot`：

```python
"rag_enabled": True
```

作用：

- 对当前聊天中的历史消息做向量召回
- 适合补充近期语义上下文

### 7.3 运行期精排与本地 Cross-Encoder

运行期 RAG 现在有两层精排能力：

- `lightweight`: 默认模式，基于向量距离和关键词重合做轻量重排
- `auto`: 如果检测到本地 `Cross-Encoder` 模型且依赖可用，则启用精排；否则自动回退轻量重排
- `cross_encoder`: 优先尝试本地 `Cross-Encoder`，若初始化失败仍回退轻量重排

推荐配置示例：

```python
"agent": {
    "retriever_rerank_mode": "auto",
    "retriever_cross_encoder_model": "models/bge-reranker-base",
    "retriever_cross_encoder_device": "cpu",
}
```

注意：

- `retriever_cross_encoder_model` 必须是本地目录
- 项目不会自动联网下载模型
- `/api/status` 中的 `retriever_stats.rerank_backend` 可用于确认当前实际启用的是 `cross_encoder` 还是 `lightweight`

### 7.4 导出语料 RAG

相关字段：

```python
"export_rag_enabled": True,
"export_rag_dir": "data/chat_exports/聊天记录",
"export_rag_top_k": 3,
"export_rag_max_chunks_per_chat": 500,
```

作用：

- 从导出的真实聊天中召回你过去的表达风格
- 更偏“风格模仿”，不是事实数据库

使用方式：

1. 导出聊天记录
2. 放到 `data/chat_exports/聊天记录/...`
3. 启动机器人或等待自动增量导入

相关命令：

```bash
python -m tools.chat_exporter.cli
python -m tools.prompt_gen.generator
```

## 8. 配置说明

### 8.1 `api`

负责模型与提供方：

- `base_url`
- `api_key`
- `model`
- `embedding_model`
- `active_preset`
- `presets`
- `timeout_sec`
- `max_retries`

### 8.2 `bot`

负责机器人行为：

- 回复格式与引用
- 轮询与并发
- 记忆与上下文
- 群聊规则
- 控制命令
- 情绪识别
- RAG 开关
- 传输后端
- 配置热重载

与本轮更新相关的字段：

- `config_reload_mode`: `auto` / `polling` / `watchdog`
- `config_reload_debounce_ms`: 文件事件防抖窗口
- `transport_backend`: `hook_wcferry` / `compat_ui`
- `required_wechat_version`: 官方支持版本基线，当前应保持为 `3.9.12.51`
- `vector_memory_enabled`: 向量记忆 / RAG 总开关，关闭后不会写入或检索向量记忆
- `vector_memory_risk_acknowledged`: 首次开启向量记忆后记录用户已确认成本与隐私提示
- `vector_memory_embedding_model`: 给向量记忆单独指定 embedding 模型，优先级高于预设和全局配置

说明：
- `hook_wcferry` 是当前默认且唯一官方支持的传输后端。
- `compat_ui` 仅保留为遗留兼容链路，不能替代 `3.9.12.51` 这个项目基线版本要求。

### 8.3 `agent`

负责 LangChain/LangGraph 运行时：

- 主链路开关
- 流式输出
- Retriever 参数
- RAG 精排模式
- Embedding 缓存
- 后台事实提取
- LangSmith tracing

与精排相关的字段：

- `retriever_rerank_mode`
- `retriever_cross_encoder_model`
- `retriever_cross_encoder_device`

### 8.4 `logging`

负责日志：

- 日志级别
- 日志文件
- 轮转大小与数量
- 是否记录消息正文

### 8.5 运行状态与指标

当前可直接观察的接口：

- `/api/status`: 结构化运行状态
- `/api/metrics`: Prometheus 风格指标

`/api/status` 重点字段：

- `startup`
- `diagnostics`
- `health_checks`
- `system_metrics`
- `config_reload`

### 8.6 运行时文件位置

为避免根目录持续堆积运行产物，当前目录约定如下：

- 应用日志：`data/logs/`
- 第三方运行时产物：`data/runtime/`
- 测试缓存：`data/runtime/test/pytest_cache/`
- 覆盖率文件：`data/runtime/test/coverage/.coverage`

## 9. 常见问题

### 9.1 `pip` 或 `python` 不存在

处理：

1. 重新安装 Python
2. 勾选 `Add Python to PATH`
3. 重开终端

### 9.2 `npm install` 失败

处理：

1. 检查 Node.js 版本
2. 清理 `node_modules`
3. 重新执行 `npm install`

### 9.3 机器人不回复

优先排查：

- 微信是否是 `3.9.12.51`
- 微信是否保持登录
- 当前会话是否被过滤
- 是否开启白名单且遗漏会话
- 模型连接是否成功
- 传输后端是否已连接
- 日志中是否有请求错误

### 9.4 模型能连通但 RAG 没效果

优先排查：

- `vector_memory_enabled` 是否被关闭
- `rag_enabled` 或 `export_rag_enabled` 是否开启
- embedding 模型是否可用
- 导出目录是否存在有效语料
- `retriever_top_k` 是否过低
- `retriever_score_threshold` 是否过严
- 当前 `retriever_stats.rerank_backend` 是否符合预期

补充说明：

- embedding 解析优先级为 `bot.vector_memory_embedding_model` > 当前预设的 `embedding_model` > `api.embedding_model`
- 使用 `Ollama` 时可以在预设或“向量记忆 embedding 模型”里填写本地 embedding 模型，例如 `nomic-embed-text`
- 首次打开向量记忆总开关时，桌面端会提示本地索引存储、CPU/内存占用以及潜在云端调用成本

### 9.5 已配置 Cross-Encoder 但没有启用

优先排查：

- 是否额外安装了 `sentence-transformers`
- `retriever_cross_encoder_model` 是否指向本地存在的目录
- `retriever_rerank_mode` 是否为 `auto` 或 `cross_encoder`
- `/api/status.retriever_stats.rerank_backend` 是否仍显示 `lightweight`
- 日志中是否有 “Cross-Encoder 精排初始化失败” 或 “本地模型路径不存在”

### 9.6 LangSmith 不生效

优先排查：

- `agent.langsmith_enabled` 是否开启
- LangSmith API Key 是否已配置
- 网络是否允许访问 LangSmith 服务

### 9.7 `/api/metrics` 无法访问

优先排查：

- 是否以 `python run.py web` 或桌面端启动了后端
- 访问的端口是否正确
- 代理或网关是否拦截了纯文本响应
- `/api/status` 是否已经可访问

## 10. 开发与测试

### 10.1 常用命令

```bash
# 安装依赖
pip install -r requirements.txt
npm install

# 桌面开发模式
npm run dev

# 启动机器人
python run.py start

# 启动 Web API
python run.py web

# 环境检查
python run.py check
```

### 10.2 测试

```bash
python -m unittest discover -s tests
python -m pytest tests\test_runtime_observability.py -q
python -m py_compile backend\core\agent_runtime.py backend\bot.py backend\bot_manager.py backend\api.py
```

当前测试覆盖重点包括：

- API 路由
- Bot 生命周期
- Export RAG
- Agent Runtime
- 运行状态、健康检查与指标导出

### 10.3 敏感数据注意事项

不要提交以下内容：

- 真实 API Key
- `data/chat_exports/`
- `data/`
- `data/logs/`
- 解密后的微信数据库
