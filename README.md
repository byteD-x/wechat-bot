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

## 📋 目录

- [功能特性](#功能特性)
- [快速开始（小白教程）](#快速开始小白教程)
- [详细安装教程](#详细安装教程)
- [配置指南](#配置指南)
- [项目结构](#项目结构)
- [Web API](#web-api)
- [聊天记录导出](#聊天记录导出)
- [个性化 Prompt 生成](#个性化-prompt-生成)
- [常见问题排查](#常见问题排查)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## ✨ 功能特性

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

## 🚀 快速开始（小白教程）

> **零编程基础也能上手！跟着以下步骤一步步操作即可。**

### 方式一：直接下载安装包（最简单，推荐）

如果你不想折腾代码，直接下载现成的安装包：

1. **下载安装包**：从 [Releases](https://github.com/your-repo/releases) 页面下载最新版的 `微信AI助手 Setup x.x.x.exe`
2. **安装软件**：双击安装包，按提示完成安装
3. **准备微信**：确保微信 PC 版 (3.9.x) 已安装并登录
4. **启动程序**：双击桌面的 **"微信AI助手"** 图标
5. **配置 API**：在界面中添加你的 AI API 密钥（见下方配置指南）
6. **开始使用**：点击"启动机器人"按钮，即可自动回复消息

### 方式二：从源码运行（适合想自定义的用户）

#### 第 1 步：环境检查清单

在开始之前，请确认你的电脑满足以下条件：

- [ ] Windows 10 或 Windows 11 系统
- [ ] 微信 PC 版 3.9.x 已安装并登录（**重要：不支持 4.0+ 版本**）
- [ ] Python 3.9 或更高版本已安装
- [ ] 有至少一个 AI 平台的 API 密钥（如 DeepSeek、豆包等）

#### 第 2 步：一键安装依赖

1. 下载本项目代码（点击绿色的 "Code" 按钮 → "Download ZIP"，解压到任意文件夹）
2. 打开 PowerShell 或命令提示符（在文件夹空白处按住 `Shift` + 右键 → "在此处打开 PowerShell 窗口"）
3. 依次执行以下命令：

```powershell
# 安装 Python 依赖（只需要执行一次）
pip install -r requirements.txt

# 安装客户端依赖（如果需要桌面端，只需要执行一次）
npm install
```

#### 第 3 步：配置 API 密钥

1. 在 `data/` 文件夹中创建 `api_keys.py` 文件
2. 填入你的 API 密钥（如何获取密钥见 [配置指南](#配置指南)）：

```python
API_KEYS = {
    "default": "你的API密钥",
    "presets": {
        "DeepSeek": "sk-xxxxxxxxxxxxxxxx",
        "Doubao": "xxxxxxxxxxxxxxxx",
    },
}
```

#### 第 4 步：启动程序

```bash
# 方式 A：启动桌面客户端（推荐）
npm run dev

# 方式 B：仅启动后端（无界面，通过 Web 访问）
python run.py web
```

启动成功后，打开浏览器访问 `http://localhost:5000` 即可看到控制面板。

---

## 📚 详细安装教程

### 1. 安装 Python（如果还没有）

**检查是否已安装：**

按 `Win + R`，输入 `cmd` 回车，在弹出的窗口中输入：

```bash
python --version
```

如果显示类似 `Python 3.9.0` 的版本号，说明已安装，跳过此步骤。

**如果未安装，按以下步骤操作：**

1. 访问 [Python 官网](https://www.python.org/downloads/)
2. 下载 Python 3.9 或更高版本的安装包
3. **重要**：安装时务必勾选 **"Add Python to PATH"**（添加到环境变量）
4. 点击 "Install Now" 完成安装
5. 重新打开命令提示符，再次输入 `python --version` 确认安装成功

### 2. 安装微信 PC 版 3.9.x

**检查当前版本：**

打开微信 → 点击左下角三条横线 → 设置 → 关于微信，查看版本号。

**如果版本是 4.0+，需要降级到 3.9.x：**

1. **备份聊天记录**（重要！）：微信 → 设置 → 通用设置 → 聊天记录备份与迁移
2. 卸载当前微信版本
3. 下载 3.9.12 版本：[点击下载](https://github.com/tom-snow/wechat-windows-versions/releases/tag/v3.9.12.51)
4. 安装下载的版本并登录

**⚠️ 注意**：
- 微信窗口不能被最小化（可以缩小或被其他窗口遮挡）
- 必须保持登录状态
- 建议关闭微信的"退出时最小化到托盘"选项

### 3. 获取 AI API 密钥

本项目需要调用 AI 大模型 API 来生成回复。以下是几个推荐的免费/低成本选项：

#### 选项 A：DeepSeek（推荐，价格便宜）

1. 访问 [DeepSeek 开放平台](https://platform.deepseek.com/)
2. 注册账号并登录
3. 进入 "API Keys" 页面，点击 "创建 API Key"
4. 复制生成的密钥（格式如 `sk-xxxxxxxxxxxxxxxx`）
5. 新用户通常有免费额度

#### 选项 B：豆包（字节跳动，国内访问快）

1. 访问 [火山引擎](https://www.volcengine.com/)
2. 注册并实名认证
3. 进入 "大模型推理" 服务
4. 创建 API Key
5. 在模型广场选择适合的模型（如 `doubao-lite-4k`）

#### 选项 C：SiliconFlow（免费额度多）

1. 访问 [SiliconFlow](https://siliconflow.cn/)
2. 注册账号
3. 进入 "API 密钥" 页面创建密钥
4. 新用户有 2000 万 Tokens 免费额度

---

## ⚙️ 配置指南

### 配置文件位置

所有配置都在 `backend/config.py` 文件中。你可以用记事本或任何文本编辑器打开修改。

### 最小可运行配置

如果你只想快速跑起来，只需要修改以下几个地方：

#### 1. 配置 API 密钥（必须）

在 `data/` 文件夹中创建 `api_keys.py`：

```python
API_KEYS = {
    "default": "sk-your-api-key-here",  # 你的默认 API 密钥
    "presets": {
        "DeepSeek": "sk-your-deepseek-key",
        "Doubao": "your-doubao-key",
    },
}
```

#### 2. 修改 API 配置

打开 `backend/config.py`，找到 `CONFIG["api"]` 部分：

```python
CONFIG = {
    "api": {
        "presets": [
            {
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "${API_KEYS[presets][DeepSeek]}",  # 引用 api_keys.py 中的密钥
                "model": "deepseek-chat",
                "timeout_sec": 30,
                "max_retries": 2,
                "temperature": 0.7,
                "max_tokens": 2000,
            },
        ],
        "active_preset": "DeepSeek",  # 默认使用哪个预设
    },
    # ... 其他配置
}
```

#### 3. 配置机器人行为（可选）

```python
"bot": {
    # 系统提示词（定义 AI 的人设和回复风格）
    "system_prompt": "你是一个 helpful 的 AI 助手...",
    
    # 回复后缀（会在每条回复后添加）
    "reply_suffix": "(AI)",
    
    # 群聊设置
    "group_reply_only_when_at": True,  # 只有被 @ 时才回复群消息
    "self_name": ["AI助手", "机器人"],  # 群里的昵称
    
    # 白名单（只回复这些好友/群聊，为空则回复所有人）
    "whitelist_groups": [],
    "whitelist_contacts": [],
    
    # 黑名单（不回复这些）
    "ignored_chat_names": ["文件传输助手"],
}
```

### 配置热重载

修改 `config.py` 后**不需要重启程序**，配置会自动生效（约 5-10 秒延迟）。

---

## 📁 项目结构

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

## 🌐 Web API

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

## 💬 聊天记录导出

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

## 🎨 个性化 Prompt 生成

基于导出的聊天记录，分析用户风格并生成专属 Prompt。智能合并连续消息，提供更精准的上下文风格模仿。

```bash
python -m tools.prompt_gen.generator
```

生成结果位于 `chat_exports/top10_prompts_summary.json`，可直接填入 `config.py`。

---

## 🔧 常见问题排查

### 问题排查流程图

```
程序无法启动
    │
    ├─→ 报错 "Python 不是内部或外部命令"
    │   └─→ 解决：重新安装 Python，勾选 "Add to PATH"
    │
    ├─→ 报错 "No module named xxx"
    │   └─→ 解决：执行 pip install -r requirements.txt
    │
    └─→ 报错 "WeChat not running"
        └─→ 解决：检查微信是否已登录，版本是否为 3.9.x

机器人启动但不回复
    │
    ├─→ 检查日志 wxauto_logs/bot.log
    │   ├─→ 看到 "API error"
    │   │   └─→ 解决：检查 API 密钥和网络连接
    │   ├─→ 看到 "Filtered"
    │   │   └─→ 解决：检查 config.py 的黑白名单设置
    │   └─→ 看到 "Cooldown"
    │       └─→ 解决：等待冷却时间或调整 min_reply_interval_sec
    │
    └─→ 日志正常但没有新消息
        └─→ 解决：确保微信窗口没有被最小化

API 连接报错
    │
    ├─→ 超时错误
    │   └─→ 解决：检查网络是否能访问 API 地址
    │
    ├─→ 401/403 错误
    │   └─→ 解决：API 密钥错误或余额不足
    │
    └─→ 429 错误
        └─→ 解决：请求太频繁，稍后再试或更换模型
```

### 详细 Q&A

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

## 🛠️ 构建发行版

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

## 🤝 贡献指南

欢迎提交 Pull Request 或 Issue！在提交之前，请确保：

1. **代码风格**：保持与现有代码一致的风格（Python 使用 4 空格缩进）。
2. **测试**：如果修改了核心逻辑，请运行单元测试 `python -m unittest discover -s tests`。
3. **敏感信息**：提交代码时请务必检查是否包含了个人的 API 密钥或聊天记录。

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。
