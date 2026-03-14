# 微信 AI 自动回复机器人

<div align="center">

<img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License">
<img src="https://img.shields.io/badge/python-3.9%2B-blue.svg" alt="Python">
<img src="https://img.shields.io/badge/platform-Windows-lightgrey.svg" alt="Platform">
<img src="https://img.shields.io/badge/WeChat-PC%203.9.x-green.svg" alt="WeChat">

基于 `wxauto` 驱动已登录微信 PC 客户端，自动读取新消息并调用大模型生成回复。  
支持桌面界面、Web 控制台、聊天记录导出、Prompt 生成、导出语料 RAG 增强。

</div>

---

## 先看结论

如果你是第一次接触这类项目，可以把它理解成：

1. 先让微信机器人能正常回复。
2. 再让它更像“真人聊天”。
3. 最后再用历史聊天记录，让它更像“你本人聊天”。

这个项目最适合这样的用户：

- 想在 Windows 上做微信自动回复
- 想接 DeepSeek、豆包、OpenAI、Qwen、Ollama 等模型
- 想要可视化界面，而不是全程改代码
- 想在已有聊天记录基础上做风格增强

---

## 风险与边界

> 本项目仅供学习、研究和个人技术探索使用。

你必须知道这些风险：

1. 使用自动化工具可能违反微信服务条款。
2. 使用非官方方案存在账号受限风险。
3. 聊天记录、已解密数据库、导出的 CSV 都是高敏感隐私数据。

你至少应该做到：

1. 只处理你自己的数据。
2. 不要把解密后的数据库上传到网盘公开分享。
3. 不要把 `chat_exports/`、`data/`、`wxauto_logs/` 提交到 Git。
4. 不要用于营销骚扰、群发骚扰、灰产或违法用途。

---

## 目录

- [1. 你需要准备什么](#1-你需要准备什么)
- [2. GitHub Release 直接体验](#2-github-release-直接体验)
- [3. 完全小白版：从零到跑起来](#3-完全小白版从零到跑起来)
- [4. 第一次启动后怎么确认它真的正常](#4-第一次启动后怎么确认它真的正常)
- [5. 你到底应该改哪里：界面、配置文件、密钥文件](#5-你到底应该改哪里界面配置文件密钥文件)
- [6. 配置总说明：每类配置在哪、有什么用、怎么改](#6-配置总说明每类配置在哪有什么用怎么改)
- [7. 推荐体验路线：先基础，再拟人，再像本人](#7-推荐体验路线先基础再拟人再像本人)
- [8. 聊天记录解密、导出、Prompt 生成与 RAG 增强](#8-聊天记录解密导出prompt-生成与-rag-增强)
- [9. 常用命令速查](#9-常用命令速查)
- [10. 常见问题排查](#10-常见问题排查)
- [11. 项目结构与文件作用](#11-项目结构与文件作用)
- [12. 构建发行版](#12-构建发行版)

---

## 1. 你需要准备什么

开始之前，请先逐项确认：

1. 电脑系统是 Windows 10 或 Windows 11。
2. 微信 PC 版是 3.9.x，已经登录。
3. 微信窗口保持打开，不要最小化到任务栏。
4. 已安装 Python 3.9 或更高版本。
5. 如果要用桌面界面，已安装 Node.js 16 或更高版本。
6. 至少有一个可用的大模型 API Key，或者本机已装 Ollama。

### 为什么必须是微信 3.9.x

因为这个项目依赖的是当前仓库适配过的 PC 版微信行为。  
4.x 版本底层结构变化较大，不能直接按现在的方式使用。

### 如果你不确定自己准备好了没有

后面安装完依赖后，直接运行：

```bash
python run.py check
```

它会帮你做基础环境自检。

---

## 2. GitHub Release 直接体验

如果你已经在 GitHub 发布了 Release，那么对完全小白来说，最推荐先走 Release 版本，而不是先拉源码。

Release 页面通常在：

- <https://github.com/byteD-x/wechat-bot/releases>

### 适合谁

适合这些用户：

- 只想先体验功能
- 不想先安装 Python 和 Node.js
- 不想折腾命令行
- 想先确认项目适不适合自己

### 一般怎么用

1. 打开 Release 页面
2. 下载最新版本的安装包或便携版
3. 安装后启动程序
4. 在设置页里填写 API Key
5. 连接测试成功后启动机器人

### Release 和源码版有什么区别

- Release 版：
  适合先体验
  上手快
  不需要自己构建

- 源码版：
  适合想改代码、调试、导出聊天记录、做二次开发的人
  灵活度更高

### README 里为什么仍然保留源码教程

因为这个项目除了“基础自动回复”之外，还有很多进阶能力：

- 聊天记录解密与导出
- Prompt 生成
- 导出语料 RAG 增强
- 自定义高级配置

这些功能更适合在源码环境里操作和排查。

如果你只是想先体验：

> 先下载 Release 跑起来，再决定要不要切源码版，是最省时间的路线。

---

## 3. 完全小白版：从零到跑起来

这一节的目标不是“学懂整个项目”，而是“先能跑通”。

### 第 1 步：下载项目

如果你是从 GitHub 下载：

1. 点击 `Code`
2. 点击 `Download ZIP`
3. 解压到一个你容易找到的位置，比如：

```text
D:\wechat-chat
```

如果你会用 Git：

```bash
git clone https://github.com/byteD-x/wechat-bot.git
cd wechat-bot
```

### 第 2 步：打开终端

在项目根目录打开 PowerShell 或命令提示符。

最简单的方法：

1. 打开项目文件夹
2. 在空白处按住 `Shift`
3. 点击右键
4. 选择“在此处打开 PowerShell 窗口”或“在终端中打开”

### 第 3 步：安装 Python 依赖

执行：

```bash
pip install -r requirements.txt
```

如果报 `pip` 不存在，通常说明 Python 没有正确装好或没有加入 PATH。

### 第 4 步：安装桌面端依赖

执行：

```bash
npm install
```

这一步的作用是安装 Electron 桌面客户端需要的依赖。  
即使你暂时只想跑后端，也建议装一下，后面更方便切到界面模式。

### 第 5 步：做环境自检

执行：

```bash
python run.py check
```

如果这里出现红色错误，先不要急着继续。  
直接跳到本文档的“常见问题排查”部分逐项处理。

### 第 6 步：配置模型

你有两种方式配置模型。

#### 方式 A：最适合小白

直接启动桌面端，在设置页里填。

命令：

```bash
npm run dev
```

启动后：

1. 打开设置页
2. 找到 `API 预设`
3. 选择一个模型服务商
4. 填入 API Key
5. 点击“测试连接”

#### 方式 B：先写密钥文件

在项目根目录的 `data` 文件夹里创建 `api_keys.py`：

```python
API_KEYS = {
    "default": "你的默认 API Key",
    "presets": {
        "DeepSeek": "你的 DeepSeek Key",
        "Doubao": "你的 Doubao Key",
        "Qwen": "你的 Qwen Key",
    },
}
```

这个文件的作用是：

- 把真实密钥从 `backend/config.py` 里分离出来
- 避免你直接改默认配置里的占位符

### 第 6.5 步：第一次启动前，先改两个最基础的设置

很多人第一次跑起来以后，会觉得：

- 回复不像自己
- 群聊里识别不准
- 整体人设很奇怪

最常见原因就是这两个字段没改：

1. `self_name`
2. `system_prompt`

这两个要么在界面改，要么在 `backend/config.py` 里改。

#### 必改项 1：`self_name`

它在哪：

- 设置页 -> `机器人设置`
- 或 `backend/config.py` -> `CONFIG["bot"]["self_name"]`

它的作用：

- 告诉程序“你自己在微信里叫什么”
- 群聊里识别自己、引用、风格匹配、导出语料匹配时都可能用到它

如果你不改会怎样：

- 默认值是 `知有`
- 如果你的微信昵称不是这个，群聊和个性化效果可能不准

怎么改：

- 改成你微信里最常见、最稳定的昵称

示例：

```python
"self_name": "小王"
```

或者在界面里直接填：

```text
小王
```

#### 必改项 2：`system_prompt`

它在哪：

- 设置页 -> `系统提示`
- 或 `backend/config.py` -> `CONFIG["bot"]["system_prompt"]`

它的作用：

- 定义机器人“像谁、怎么说话、回复风格是什么”
- 它决定了回复是不是像微信聊天，而不是像客服或像通用 AI

如果你不改会怎样：

- 程序会用默认的人设模板
- 能跑，但不一定像你

新手最简单的改法：

- 不要一上来写很复杂
- 先写成 3 句话就够

示例 1：日常朋友聊天风格

```text
你就是我本人在微信里回复消息。
回复要像日常聊天，简短、自然、口语化，不要像客服。
不暴露 AI 身份，不要长篇大论。
```

示例 2：更温柔一点

```text
你就是我本人在微信里回复消息。
语气自然温和，像熟人聊天，少解释，少套话。
不暴露 AI 身份，不要使用客服式表达。
```

示例 3：更冷淡一点

```text
你就是我本人在微信里回复消息。
回复简短一点，像平时微信说话，不要太热情，不要像机器人。
不暴露 AI 身份，不要写成正式文章。
```

### 第 7 步：启动项目

你有两种启动方式。

#### 方式 A：桌面端，推荐

```bash
npm run dev
```

适合人群：

- 完全小白
- 喜欢点界面配置
- 不想手改配置文件

#### 方式 B：只启动 Web 控制台

```bash
python run.py web
```

启动后打开浏览器访问：

```text
http://127.0.0.1:5000
```

### 第 8 步：启动机器人

进入界面后，按这个顺序操作：

1. 打开“设置”
2. 配好一个可用预设
3. 把 `self_name` 改成你自己的微信昵称
4. 把 `system_prompt` 改成你想要的聊天风格
5. 测试连接成功
6. 点击“启动机器人”

做到这一步，就已经不是“装好了”，而是“真的跑起来了”。

---

## 4. 第一次启动后怎么确认它真的正常

很多人启动完以后会问一句：  
“它到底是真的在工作，还是只是界面显示正常？”

你按下面顺序验证最稳：

### 验证 1：状态页

看这些信息：

1. `running` 或界面状态是不是运行中
2. 当前模型预设是不是你刚选的
3. API Key 状态是不是已配置

### 验证 2：测试连接

在设置页里点击“测试连接”。

如果失败，说明问题还在模型配置，不在微信。

### 验证 3：真实发一条微信消息

找一个不会误伤的重要联系人，最好是你自己的小号或非常熟悉的人。  
给当前微信发一条纯文本消息，然后观察：

1. 是否识别到新消息
2. 是否成功回了一条
3. 回复内容是否来自模型，而不是固定模板

### 验证 4：查看日志

日志默认在：

- `wxauto_logs/bot.log`

如果界面正常但不回复，日志通常最先能告诉你问题在哪。

---

## 5. 你到底应该改哪里：界面、配置文件、密钥文件

很多小白一上来最容易混乱的就是：

- 我到底该改哪个文件？
- 什么时候用界面改？
- 什么时候要手动改代码？

可以这样理解。

### 入口 1：桌面设置页

这是最推荐的入口。  
绝大多数用户只用它就够了。

你可以在这里改：

- 模型预设
- API Key
- 系统提示词
- 白名单和过滤
- 记忆参数
- 情绪识别
- 导出聊天记录 RAG

适合：

- 新手
- 不熟悉 Python
- 想边试边改

### 入口 2：`backend/config.py`

文件路径：

- `backend/config.py`

它是什么：

- 项目的默认配置文件
- 所有配置项的“源头定义”

适合：

- 想看所有可调参数
- 想做更细粒度配置
- 会看注释和字典结构

### 入口 3：`data/api_keys.py`

文件路径：

- `data/api_keys.py`

它是什么：

- 专门放真实 API Key 的地方

为什么推荐放这里：

- 不容易误提交到公共仓库
- 方便切换不同服务商的 Key

### 入口 4：`data/config_override.json`

文件路径：

- `data/config_override.json`

它是什么：

- 你在界面里保存设置后，程序写入的配置覆写文件

建议：

- 不建议新手直接手改
- 它更像“界面保存后的结果”

### 一个简单的选择规则

如果你不知道该改哪里，就按这个原则：

1. 能在界面改的，优先在界面改。
2. 界面里没有暴露的高级项，再去改 `backend/config.py`。
3. 真实密钥尽量放 `data/api_keys.py`。

---

## 6. 配置总说明：每类配置在哪、有什么用、怎么改

这一节会把最常用配置按“新手能听懂”的方式解释。

### 5.1 API 预设

界面位置：

- 设置页 -> `API 预设`

配置文件位置：

- `backend/config.py` 的 `CONFIG["api"]`

它的作用：

- 告诉程序用哪个模型服务商
- 用哪个模型
- API 地址是什么
- Key 是什么
- 超时和重试怎么设置

最常见的字段：

- `active_preset`
  作用：当前实际使用哪个预设
  怎么改：在界面里切换，或改配置文件
  常见值：`DeepSeek`、`Doubao`、`OpenAI`、`Ollama`

- `base_url`
  作用：模型接口地址
  怎么改：通常跟服务商绑定，不建议乱改
  常见值：
  `https://api.deepseek.com/v1`
  `https://api.openai.com/v1`
  `http://127.0.0.1:11434/v1`

- `model`
  作用：具体用哪个模型
  怎么改：界面里选或手填
  常见值：
  `deepseek-chat`
  `gpt-5-mini`
  `qwen3.5-plus`

- `embedding_model`
  作用：给 RAG 和向量检索用的 embedding 模型
  什么时候必须配：你想用导出聊天记录 RAG 时
  不配会怎样：普通聊天还能用，但导出语料 RAG 可能不会工作

- `timeout_sec`
  作用：请求最多等多久
  建议：
  网络一般时可设大一点，如 `10`
  想更快失败重试时可设小一点，如 `5`

- `max_retries`
  作用：失败重试次数
  建议：
  新手默认即可，不要一上来调太大

### 5.2 机器人设置

界面位置：

- 设置页 -> `机器人设置`

最常见字段：

- `self_name`
  作用：机器人在群聊里识别“你自己是谁”
  什么时候要改：第一次启动前就建议改；群聊场景、@识别、导出语料匹配时尤其重要
  默认值：`知有`
  怎么改：改成你微信里最常见、最稳定的昵称
  推荐改法：
  如果你微信名是 `阿杰`，就填 `阿杰`
  如果你常改昵称，尽量填最近最常用的那个
  不建议乱填英文代号或程序内部名字
  示例：
  `阿杰`
  `小李`
  `王老师`

- `reply_suffix`
  作用：每条回复尾部自动加的内容
  默认效果：会加一个 AI 代答提示
  如果你想更自然：可以改短，或者直接清空
  示例：
  `""`
  `"\n(晚点细聊)"`

### 5.3 系统提示词

界面位置：

- 设置页 -> `系统提示`

配置文件位置：

- `bot.system_prompt`
- `bot.system_prompt_overrides`

它的作用：

- 决定机器人整体人设、语气、回复原则
- 它是影响“像不像你”“像不像微信真人聊天”的第一关键项

第一次使用时，强烈建议你一定手动改一次，而不是直接使用默认值。

最简单的写法建议：

1. 第一行：说明“你就是我本人在微信里回复”
2. 第二行：说明想要什么语气
3. 第三行：说明不要暴露 AI 身份

一个最通用的新手模板：

```text
你就是我本人在微信里回复消息。
回复要像日常微信聊天，简短、自然、口语化，不要像客服。
不要暴露 AI 身份，不要长篇大论，不要使用列表和标题。
```

如果你只想简单改风格，可以这样改：

- 想更冷淡：写“回复简短一点，少感叹号，像日常微信，不要像客服”
- 想更温柔：写“语气自然温和，适度关心，不要过度正式”
- 想更像朋友：写“口语化、短句、少解释、必要时反问一句”
- 想更像你本人：把你平时常说的话、语气词、句子长度偏好写进去

#### 新手不建议这样写

- 写成“你是一个强大的 AI 助手”
- 写成长篇规则手册但自己都看不懂
- 同时要求“像客服、像秘书、像朋友、像恋人、像专业顾问”

原因：

- 越混乱，模型越不知道该怎么回
- 越像说明书，越不像真人微信聊天

#### `system_prompt_overrides` 是什么

作用：

- 对某个特定联系人单独覆盖系统提示词

适合：

- 某个好友要更随意
- 某个客户要更正式
- 某个亲密关系对象要更有个人风格

### 5.4 引用设置

界面位置：

- 设置页 -> `引用设置`

最常见字段：

- `reply_quote_mode`
  作用：回复时是否带引用
  可选值：
  `wechat`：优先用微信原生引用
  `text`：用文本形式引用
  `none`：不引用

- `reply_quote_template`
  作用：文本引用时长什么样
  示例：
  `"引用：{content}\n"`

如果你觉得回复看起来太机械，最简单的做法是：

- 直接把 `reply_quote_mode` 改成 `none`

### 5.5 表情与语音

界面位置：

- 设置页 -> `表情与语音`

重点字段：

- `emoji_policy`
  作用：怎么处理表情
  可选值：
  `wechat`、`strip`、`keep`、`mixed`
  新手建议：先保持默认 `mixed`

- `voice_to_text`
  作用：是否尝试把语音转成文字再回复
  如果你只想先稳定跑文本：可以先关掉

- `voice_to_text_fail_reply`
  作用：语音转写失败时要不要回一句固定话

### 5.6 记忆与上下文

界面位置：

- 设置页 -> `记忆与上下文`

配置文件位置：

- `memory_db_path`
- `memory_context_limit`
- `memory_ttl_sec`
- `context_rounds`
- `context_max_tokens`

它们的含义：

- `memory_db_path`
  作用：记忆数据库文件放哪里
  默认值：`chat_history.db`
  一般不用改，除非你想换存储位置

- `memory_context_limit`
  作用：每次给模型注入多少条近期对话
  数值越大：上下文越完整，但也更耗 token
  新手建议：默认即可

- `context_rounds`
  作用：最多保留多少轮聊天
  如果你觉得 AI 老忘事：可以适当调大

- `context_max_tokens`
  作用：上下文 token 上限
  太小：容易忘前文
  太大：响应更慢、成本更高

### 5.7 轮询与延迟

界面位置：

- 设置页 -> `轮询与延迟`

这类配置的作用：

- 多久检查一次新消息
- 回复前等待多久
- 看起来更像人，还是更像秒回机器人

最常见字段：

- `poll_interval_min_sec`
  越小越快

- `min_reply_interval_sec`
  控制最短回复间隔

- `random_delay_range_sec`
  控制随机延迟区间

如果你想“更像真人”：

- 适当调大随机延迟

如果你想“更快回复”：

- 适当调小 `min_reply_interval_sec`

### 5.8 合并与发送

界面位置：

- 设置页 -> `合并与发送`

重点字段：

- `merge_user_messages_sec`
  作用：对方短时间内连续发几条时，是否合并成一次提问
  如果你觉得 AI 连发多条不自然：可以开大一点

- `reply_chunk_size`
  作用：单条消息最大发送长度

- `reply_chunk_delay_sec`
  作用：分段发送间隔

### 5.9 智能分段和流式回复

界面位置：

- `智能分段`
- `流式回复`

它们的作用：

- 让长回复不要一坨直接发完
- 更像人在打字、分句发送

如果你不喜欢机器人一条回很多字：

- 开启 `natural_split_enabled`
- 控制最大分段数

如果你更在意“尽快看到模型开始回”：

- 保持 `stream_reply = true`

### 5.10 群聊与发送

界面位置：

- 设置页 -> `群聊与发送`

重点字段：

- `group_reply_only_when_at`
  作用：群里是不是只有被 @ 才回复
  新手强烈建议：群聊先开这个

- `group_include_sender`
  作用：群聊上下文里是否带发送者信息

- `send_exact_match`
  作用：发送时是否要求目标会话名精确匹配

### 5.11 过滤规则和白名单

界面位置：

- `过滤规则`
- `白名单管理`

这部分很重要，因为“机器人不回复”经常是它们导致的。

重点字段：

- `whitelist_enabled`
  作用：是否只回复白名单里的会话
  如果你一开始调试发现机器人不回复，先检查这里

- `whitelist`
  作用：允许回复的会话名列表

- `ignore_names`
  作用：明确不处理的会话

- `ignore_keywords`
  作用：名字里含某些词就忽略

新手建议：

1. 第一次调试时，先关掉白名单。
2. 先保证私聊能通。
3. 后面再逐步收紧过滤规则。

### 5.12 个性化

界面位置：

- 设置页 -> `个性化`

重点字段：

- `personalization_enabled`
  作用：是否启用用户画像和个性化能力

- `remember_facts_enabled`
  作用：是否让 AI 提取并记住重要事实

- `profile_update_frequency`
  作用：每收到多少条消息更新一次画像

- `profile_inject_in_prompt`
  作用：是否把画像注入给模型

如果你想让回复逐渐更懂人：

- 这一组建议保持开启

### 5.13 导出聊天记录 RAG

配置文件位置：

- `export_rag_enabled`
- `export_rag_dir`
- `export_rag_auto_ingest`
- `export_rag_top_k`
- `export_rag_max_chunks_per_chat`
- `export_rag_chunk_messages`
- `export_rag_min_score`
- `export_rag_max_context_chars`

作用：

- 当你导出了某个联系人的历史聊天后
- 程序会把你本人过去的表达做成本地风格索引
- 后续这个联系人来找你时，会优先参考那些历史表达

这是“更像本人”的关键能力。

最常见配置解释：

- `export_rag_enabled`
  作用：开关总控
  没开：即使你导出了聊天记录，也不会用来增强回复

- `export_rag_dir`
  作用：导出聊天记录所在目录
  默认值：`chat_exports/聊天记录`
  一般建议不要改，保持默认最省事

- `export_rag_auto_ingest`
  作用：启动或热更新时自动扫描并导入
  新手建议：保持开启

- `export_rag_top_k`
  作用：每次检索拿多少条风格片段
  太小：风格参考不足
  太大：可能注入过多，回复变重
  新手建议：默认值即可

- `export_rag_chunk_messages`
  作用：把你连续发出的几条消息合并成一个片段
  越大：片段越完整
  越小：片段越碎

### 5.14 控制命令

界面位置：

- 设置页 -> `控制命令`

作用：

- 在聊天里用命令控制机器人，例如暂停、恢复、查看状态

重点字段：

- `control_commands_enabled`
- `control_command_prefix`
- `control_allowed_users`
- `control_reply_visible`

### 5.15 定时静默

界面位置：

- 设置页 -> `定时静默`

作用：

- 在某些时间段不自动回复

适合：

- 夜间不想打扰别人
- 避免半夜自动回消息

重点字段：

- `quiet_hours_enabled`
- `quiet_hours_start`
- `quiet_hours_end`
- `quiet_hours_reply`

### 5.16 用量监控

界面位置：

- 设置页 -> `用量监控`

作用：

- 控制 token 消耗
- 避免一天内用量超支

重点字段：

- `usage_tracking_enabled`
- `daily_token_limit`
- `token_warning_threshold`

### 5.17 情感识别

界面位置：

- 设置页 -> `情感识别`

作用：

- 对方明显开心、焦虑、难过时，回复语气更合适

重点字段：

- `emotion_detection_enabled`
- `emotion_detection_mode`
- `emotion_inject_in_prompt`

新手建议：

- 默认保持开启
- 模式用 `ai` 效果更好，`keywords` 更省资源

### 5.18 日志设置

界面位置：

- 设置页 -> `日志设置`

作用：

- 控制日志等级和是否记录消息内容

重点字段：

- `logging.level`
- `logging.file`
- `logging.log_message_content`
- `logging.log_reply_content`

安全建议：

- 不要随便打开消息内容日志
- 因为日志文件本身就是敏感数据

---

## 7. 推荐体验路线：先基础，再拟人，再像本人

你不需要一上来把所有功能都打开。

最推荐的顺序是：

### 第 1 阶段：先让它稳定回复

只关注：

- API 预设
- 测试连接
- 启动机器人
- 私聊文本能不能正常回复

### 第 2 阶段：再让它更像真人

开启并观察：

- 个性化
- 事实记忆
- 情绪识别
- 智能分段

### 第 3 阶段：最后让它更像你本人

去做这些：

1. 解密微信数据库
2. 导出某个联系人的聊天记录
3. 开启导出聊天记录 RAG
4. 再和这个联系人对话，观察风格变化

---

## 8. 聊天记录解密、导出、Prompt 生成与 RAG 增强

这一节是整个项目里最容易让人卡住，但也是最能提升体验的一节。

### 7.1 先明白：本项目导出命令需要“已解密”数据库

导出命令：

```bash
python -m tools.chat_exporter.cli --db-dir "E:\decrypted_wechat\wxid_xxx\Msg" --contact "张三"
```

这里的 `--db-dir` 必须是：

- 已解密
- 可读取
- 对应当前微信账号的 `Msg` 目录

不是微信安装目录，也不是任意 `WeChat Files` 根目录。

### 7.2 推荐解密路线

完整新手指南见：

- [docs/wechat-export-guide.md](docs/wechat-export-guide.md)

一句话概括流程：

1. 先保持微信登录
2. 用独立工具拿到 `wx_dir` 和 `db_key`
3. 把数据库解密到新目录
4. 再用本项目导出 CSV

联网检索时，我补充参考了：

- `wdecipher` 的公开说明页：<https://pypi.org/project/wdecipher/>
- `PyWxDump` 当前仓库状态：<https://github.com/xaoyaoo/PyWxDump>

### 7.3 导出聊天记录 CSV

示例：

```bash
python -m tools.chat_exporter.cli --db-dir "E:\decrypted_wechat\wxid_xxx\Msg" --contact "张三"
```

常用参数：

- `--db-dir`
  作用：指定已解密的数据库目录

- `--contact`
  作用：指定要导出的联系人
  可以传备注、昵称、wxid

- `--include-chatrooms`
  作用：是否连群聊一起导出

- `--start`
- `--end`
  作用：限制导出时间范围

导出成功后，一般会得到：

```text
chat_exports/聊天记录/张三(wxid_xxx)/张三.csv
```

### 7.4 生成个性化 Prompt

命令：

```bash
python -m tools.prompt_gen.generator
```

作用：

- 分析导出的聊天记录
- 总结你的表达习惯
- 生成更适合某些联系人的提示词

输出文件：

```text
chat_exports/top10_prompts_summary.json
```

### 7.5 开启导出聊天记录 RAG

最关键的配置：

- `export_rag_enabled = true`
- `export_rag_auto_ingest = true`
- `export_rag_dir = "chat_exports/聊天记录"`

工作原理：

1. 程序自动扫描你导出的 CSV
2. 把你本人过去的话切成风格片段
3. 建立本地索引
4. 当前联系人发消息时，优先参考你过去的真实表达

### 7.6 怎么判断 RAG 真生效了

看这几个点：

1. 状态接口中 `export_rag.indexed_contacts` 大于 0
2. 与已导出联系人对话时，语气更接近你历史表达
3. 没有导出的联系人仍然可以正常聊天

---

## 9. 常用命令速查

### 环境检查

```bash
python run.py check
```

### 启动机器人

```bash
python run.py
python run.py start
```

### 启动 Web 控制台

```bash
python run.py web
```

### 启动桌面端

```bash
npm run dev
```

### 导出聊天记录

```bash
python -m tools.chat_exporter.cli --db-dir "E:\decrypted_wechat\wxid_xxx\Msg" --contact "张三"
```

### 生成 Prompt

```bash
python -m tools.prompt_gen.generator
```

### 运行测试

```bash
python -m unittest discover -s tests
```

---

## 10. 常见问题排查

### 1. 报错 “Python 不是内部或外部命令”

原因：

- Python 没装
- Python 装了但没加 PATH

处理：

1. 重新安装 Python
2. 安装时勾选 `Add Python to PATH`
3. 重新打开终端再试

### 2. 报错 “No module named xxx”

原因：

- 依赖没装全

处理：

```bash
pip install -r requirements.txt
```

如果是桌面端报错，再执行：

```bash
npm install
```

### 3. 微信登录了，但程序说 “WeChat not running”

重点检查：

1. 是不是微信 4.x
2. 微信是不是最小化到任务栏了
3. 当前是不是用了不兼容版本

### 4. 机器人启动了，但不回复

按这个顺序排查：

1. 先确认 API 测试连接是否成功
2. 再确认当前联系人有没有被白名单/黑名单挡住
3. 再确认发的是不是纯文本
4. 最后看日志

最常见原因：

- 开启了白名单，但联系人不在白名单里
- 群聊设置成了“只在被 @ 时回复”
- 模型接口失败

### 5. API 连接失败

先检查：

1. `base_url` 是否正确
2. `api_key` 是否真实有效
3. `model` 名称是否正确
4. 你当前网络能否访问这个服务商

### 6. 导出聊天记录时报错

常见原因：

1. `--db-dir` 指错了
2. 目录不是已解密数据库目录
3. 联系人名字没匹配上

优先排查：

1. 先看 [docs/wechat-export-guide.md](docs/wechat-export-guide.md)
2. 再确认目录结构
3. 再确认联系人名字

### 7. 导出聊天记录 RAG 没效果

检查：

1. `export_rag_enabled` 是否开启
2. `export_rag_dir` 是否正确
3. embedding 模型是否配置
4. 你是否真的导出了对应联系人的聊天记录
5. 当前联系人的名字是否能匹配导出目录

---

## 11. 项目结构与文件作用

```text
wechat-chat/
├── run.py
├── requirements.txt
├── package.json
├── backend/
│   ├── bot.py
│   ├── api.py
│   ├── config.py
│   ├── core/
│   ├── handlers/
│   └── utils/
├── src/
│   ├── main/
│   ├── renderer/
│   └── preload/
├── tools/
│   ├── chat_exporter/
│   ├── prompt_gen/
│   └── wx_db/
├── docs/
├── data/
├── scripts/
└── wxauto_logs/
```

如果你只想快速知道关键文件是干嘛的，看这几个：

- `run.py`
  作用：统一入口，启动、检查、Web 面板都从这里走

- `backend/config.py`
  作用：默认配置总表

- `backend/bot.py`
  作用：消息处理主流程

- `backend/api.py`
  作用：前端和 Web 控制台用到的接口

- `src/renderer/index.html`
  作用：设置页结构

- `src/renderer/js/pages/SettingsPage.js`
  作用：设置页交互逻辑

- [docs/wechat-export-guide.md](docs/wechat-export-guide.md)
  作用：微信聊天记录解密与导出专门指南

---

## 12. 构建发行版

如果你想打包成 Windows 可执行文件：

```powershell
.\build.bat
```

构建前请确认：

1. Python 依赖已经安装
2. Node.js 依赖已经安装
3. `npm run dev` 能正常启动

如果你已经配置好了 GitHub Release，这一节更适合你自己维护发布流程时参考。  
对普通用户来说，优先直接去 Release 页面下载安装包即可。

---

## 最后给完全小白的建议

不要一上来就改所有配置。  
最正确的顺序永远是：

1. 先跑起来
2. 再稳定回复
3. 再调整风格
4. 最后再做历史聊天增强

你可以把整个上手过程拆成 4 次成功：

1. 第一次成功：程序能启动
2. 第二次成功：机器人能回复
3. 第三次成功：回复更像真人
4. 第四次成功：回复更像你本人

只要你按这个顺序走，排错会容易很多。

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
