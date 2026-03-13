# 微信 AI 自动回复机器人

<div align="center">

<img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License">
<img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python">
<img src="https://img.shields.io/badge/platform-Windows-lightgrey.svg" alt="Platform">
<img src="https://img.shields.io/badge/WeChat-PC%203.9.x-green.svg" alt="WeChat">

基于 `wxauto` 驱动已登录的微信 PC 客户端，自动轮询消息并调用 OpenAI 兼容 `/chat/completions` 接口生成回复。

包含一个基于 Electron 的桌面客户端，提供可视化的配置和监控界面。

</div>

---

<div align="center">

<img src="https://img.shields.io/badge/⚠️-免责声明-red.svg" alt="免责声明">

</div>

> **本项目仅供技术研究和学习交流使用**
> 
> **风险提示**：使用非官方 API 或自动化工具可能违反微信服务条款，导致账号被限制或封禁。  
> **责任声明**：开发者不对使用本工具导致的任何账号损失、数据丢失或法律风险承担责任。  
> **合规使用**：请勿将本工具用于发送垃圾信息、骚扰他人或任何非法用途。

---

## 目录

- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [Web API](#web-api)
- [聊天记录导出](#聊天记录导出)
- [个性化 Prompt 生成](#个性化-prompt-生成)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 功能特性

### 核心功能

| 功能 | 说明 |
|------|------|
| **多预设 API** | 支持 OpenAI、DeepSeek、豆包、Kimi (Moonshot)、智谱 (Zhipu) 等多家服务，自动探测可用模型 |
| **文本自动回复** | 消息规范化、群聊 @ 识别、可选发送者前缀 |
| **语音转文字** | 调用微信内置转写（可开关，失败可回退回复） |
| **回复策略** | 流式输出、分段发送、随机延迟、最小回复间隔 |
| **消息合并** | 短时间内连发消息自动合并，避免多次触发模型 |

### 记忆与上下文

- **AI 内存**：按轮数/估算 token 裁剪，支持 SQLite 持久化
- **个性化记忆**：用户画像管理（昵称、关系、性格特征）
- **事实记忆**：AI 自动提取重要信息（生日、偏好、计划等）

### 情感识别与人性化

- **情感检测**：支持关键词模式（快速）和 AI 模式（精准）
- **时间感知**：根据时间段调整回复语气
- **对话风格适应**：学习并适应用户的沟通风格
- **关系演进**：基于互动次数自动调整关系亲密度

### 管理与过滤

- **可视化管理**：提供 Electron 桌面客户端和 Web 控制台
- **白名单/黑名单**：过滤公众号、服务号、关键词、特定会话
- **热重载**：配置修改实时生效，支持掉线自动重连
- **高性能**：基于 Quart (AsyncIO) 的异步后端
- **设置与预设管理**：新增设置页，支持添加/编辑/删除预设与一键激活
- **连接测试与日志**：支持预设连接测试，以及查看/清空运行日志

---

## 快速开始

### 环境准备

- [x] Windows 10/11
- [x] 微信 PC 版 3.9.x（已登录并保持运行，推荐 3.9.12：https://github.com/tom-snow/wechat-windows-versions/releases/tag/v3.9.12.51）
- [x] Python 3.9+
- [x] Node.js 16+ (仅开发客户端需要)
- [x] 可访问 OpenAI 兼容 API

### 安装依赖

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 安装客户端依赖 (如果需要运行桌面端源码)
npm install
```

### 配置密钥

建议创建 `api_keys.py`（已在 `.gitignore` 中）以安全管理密钥：

```python
API_KEYS = {
    "default": "YOUR_DEFAULT_KEY",
    "presets": {
        "OpenAI": "YOUR_OPENAI_KEY",
        "Doubao": "YOUR_DOUBAO_KEY",
        "DeepSeek": "YOUR_DEEPSEEK_KEY",
        "SiliconFlow": "YOUR_SILICONFLOW_KEY",
    },
}
```

### 启动方式

#### 方式一：直接运行安装包（推荐普通用户）

下载并安装最新版的 `.exe` 文件后，直接双击桌面的 **"微信AI助手"** 图标即可启动。
- 程序会自动启动后端服务和图形化界面。
- 请确保微信 PC 版 (3.9.x) 已在运行并登录。

#### 方式二：桌面客户端源码运行（推荐开发调试）

```bash
npm run dev
```

启动后将自动拉起 Python 后端服务，并显示悬浮窗或系统托盘图标。

#### 方式三：仅启动后端（API 模式）

如果你不需要桌面 GUI，或者部署在服务器上：

```bash
# 启动机器人核心
python run.py start

# 或者启动 Web API 服务 (默认端口 5000)
python run.py web
```

常用命令：
- `python run.py setup`：运行交互式配置向导
- `python run.py check`：运行环境自检

---

## 构建发行版

如果你想将项目打包为 `.exe` 可执行文件（方便分发或在无 Python 环境的机器上运行），请执行以下步骤：

### 1. 准备环境

确保已安装 Python 3.9+ 和 Node.js 16+。

### 2. 执行构建脚本

在项目根目录下运行：

```powershell
.\build.bat
```

该脚本会自动：
1. 安装/检查 Python 和 Node.js 依赖。
2. 使用 `PyInstaller` 将 Python 后端打包为独立可执行文件。
3. 使用 `electron-builder` 将前端和后端打包为最终的 Windows 安装包。

构建完成后，安装包位于 `dist/` 目录下（如 `微信AI助手 Setup 1.0.0.exe`）。

---

## 项目结构

```
wechat-chat/
├── run.py               # 统一入口 (start/web/check/setup)
├── requirements.txt     # Python 依赖清单
├── package.json         # Electron 依赖清单
├── backend/             # 核心后端代码 (Python)
│   ├── bot.py           # 机器人主类
│   ├── config.py        # 运行时配置
│   ├── api.py           # Quart Web API
│   ├── main.py          # 异步启动逻辑
│   ├── core/            # 核心组件 (AI, Memory, Emotion, etc.)
│   ├── handlers/        # 消息处理 (Filter, Sender, Converters)
│   └── utils/           # 通用工具
│
├── src/                 # Electron 前端源码
│   ├── main/            # 主进程
│   ├── renderer/        # 渲染进程 (Web 界面)
│   └── preload/         # 预加载脚本
│
├── tools/               # 实用工具箱
│   ├── chat_exporter/   # 聊天记录导出工具
│   ├── prompt_gen/      # 个性化 Prompt 生成器
│   └── wx_db/           # 微信本地数据库解密/读取 (核心底层)
│
├── data/                # 数据持久化 (gitignored)
│   ├── api_keys.py      # API 密钥配置
│   ├── chat.db          # 记忆数据库文件
│   └── config_override.json # API 修改的配置覆写
│
├── scripts/             # 运维脚本
└── wxauto_logs/         # 运行日志
```

---

## 配置说明

配置文件位于 `backend/config.py`。支持热重载，修改后无需重启。

### API 配置 (`CONFIG["api"]`)

支持多预设（Presets）自动轮询探测。

| 参数 | 说明 |
|------|------|
| `base_url` | 接口地址 |
| `api_key` | 密钥（支持占位符与空密钥策略） |
| `model` | 模型名称 |
| `timeout_sec` | 超时时间 |
| `max_retries` | 最大重试次数 |
| `temperature` | 采样温度 |
| `max_tokens` | 请求最大 tokens |
| `max_completion_tokens` | 回复最大 tokens（兼容部分平台） |
| `reasoning_effort` | 推理力度（兼容支持该参数的平台） |
| `allow_empty_key` | 是否允许空密钥用于探测 |
| `active_preset` | 当前激活的预设名 |
| `presets[]` | 预设数组（包含以上字段的子项） |

### 机器人配置 (`CONFIG["bot"]`)

- **system_prompt**: 定义人设、回复规则、上下文注入格式。
- **system_prompt_overrides**: 针对特定联系人/群聊的 Prompt 覆盖。
- **reply_suffix**: 回复后缀（如 `(AI)`）。
- **emoji_policy**: 表情处理策略 (`mixed`/`strip`/`keep`)。
- **memory_***: 记忆相关配置 (SQLite 路径, TTL, 上下文轮数)。

---

## Web API

启动 `python run.py web` 后，可通过 HTTP 接口控制机器人：

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/status` | GET | 获取运行状态 |
| `/api/start` | POST | 启动机器人 |
| `/api/stop` | POST | 停止机器人 |
| `/api/pause` | POST | 暂停机器人 |
| `/api/resume` | POST | 恢复机器人 |
| `/api/messages` | GET | 获取最近消息记录 |
| `/api/send` | POST | 发送消息 |
| `/api/config` | GET/POST | 获取/修改配置 |
| `/api/test_connection` | POST | 测试当前或指定预设的连通性 |
| `/api/logs` | GET | 获取运行日志（尾部 N 行） |
| `/api/logs/clear` | POST | 清空当前日志文件 |
| `/api/usage` | GET | 获取用量统计（回复次数、tokens 等） |

---

## 聊天记录导出

工具位于 `tools/chat_exporter`，支持从解密后的微信数据库直接导出 CSV。采用流式逐行写入技术，支持导出数百万条记录而无内存溢出风险。

```bash
# 示例：导出指定联系人的聊天记录
python -m tools.chat_exporter.cli --db-dir "E:\wxid_xxx\Msg" --contact "张三"
```

参数说明：
- `--db-dir`: 解密后的微信数据库目录
- `--contact`: 联系人昵称/备注/wxid
- `--include-chatrooms`: 是否包含群聊

---

## 个性化 Prompt 生成

基于导出的聊天记录，分析用户风格并生成专属 Prompt。智能合并连续消息，提供更精准的上下文风格模仿。

```bash
python -m tools.prompt_gen.generator
```

生成结果位于 `chat_exports/top10_prompts_summary.json`，可直接填入 `config.py`。

---

## 常见问题

<details>
<summary><b>Q1: 运行报错 "WeChat not running" 或无法获取消息？</b></summary>

**检查微信运行状态**：确保微信 PC 版已登录并在运行中。  
**检查微信版本**：必须使用 **3.9.x** 版本（推荐 3.9.11）。**暂不支持 4.0 及以上版本**，因为底层 hook 机制已变更。  
**窗口状态**：请勿将微信窗口最小化到任务栏，建议保持窗口打开状态（可以被其他窗口遮挡，但不能最小化）。
</details>

<details>
<summary><b>Q2: 机器人已启动但不回复消息？</b></summary>

**检查日志**：查看 `wxauto_logs/bot.log` 或控制台输出，是否有报错信息。  
**过滤器设置**：检查 `config.py` 中的 `filter` 设置，是否将目标好友/群聊加入了黑名单，或未在白名单中。  
**消息类型**：目前仅支持文本消息，图片/表情包/文件等会被自动忽略。  
**回复冷却**：检查 `bot.min_reply_interval_sec` 设置，是否因为冷却时间未过而跳过回复。
</details>

<details>
<summary><b>Q3: API 连接超时或报错？</b></summary>

**检查网络**：确认你的网络环境可以访问对应的 API `base_url`（如 OpenAI 需科学上网）。  
**检查密钥**：确认 `api_keys.py` 或 `config.py` 中的 API Key 正确且有余额。  
**尝试其他模型**：部分免费模型可能不稳定，尝试切换预设（如 Doubao 或 DeepSeek）。
</details>

<details>
<summary><b>Q4: Windows 控制台中文乱码？</b></summary>

**设置编码**：在运行前执行 `chcp 65001`。  
**使用新版终端**：推荐使用 Windows Terminal (PowerShell Core) 而不是旧版 CMD。
</details>

<details>
<summary><b>Q5: Electron 客户端启动白屏或报错？</b></summary>

**检查 Node 版本**：确保 Node.js 版本 >= 16。  
**重新安装依赖**：尝试删除 `node_modules` 后重新运行 `npm install`。  
**开发模式**：使用 `npm run dev` 查看详细报错信息。
</details>

---

## 贡献指南

欢迎提交 Pull Request 或 Issue！在提交之前，请确保：

1. **代码风格**：保持与现有代码一致的风格（Python 使用 4 空格缩进）。
2. **测试**：如果修改了核心逻辑，请运行单元测试 `python -m unittest discover -s tests`。
3. **敏感信息**：提交代码时请务必检查是否包含了个人的 API 密钥或聊天记录。

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
