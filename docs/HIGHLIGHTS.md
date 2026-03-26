# 项目亮点

> **适用场景**：产品对外宣传、项目介绍页面、技术交流展示
>
> 这份文档用于集中展示当前项目最值得对外强调的能力：差异化定位、核心亮点、技术难点与落地方案。

如果需要查看完整调用链、模块职责与运行顺序，请继续阅读 [SYSTEM_CHAINS.md](SYSTEM_CHAINS.md)。

> 想深入了解细节？推荐按需阅读：
> - [PROJECT_HIGHLIGHTS_SUMMARY.md](PROJECT_HIGHLIGHTS_SUMMARY.md) — 技术架构与实现细节
> - [STAR_REPO_STAR.md](STAR_REPO_STAR.md) — 简历用 STAR 案例

## 1. 项目定位

这个项目不是“收到微信消息后调用一次大模型”的轻量脚本，而是一个运行在 Windows 微信生态上的本地化 AI 助手运行时，目标是同时解决四类问题：

- 微信自动化接入要稳定，不能只在演示环境里能跑
- AI 回复不能只靠单轮对话，必须有记忆、检索和上下文编排
- 运行链路不能是黑盒，必须能诊断、观测和解释当前状态
- 部署不能默认强依赖联网下载模型，要兼顾本地化、可控性和可回退

一句话概括：

> 它的差异化不在“接了大模型”，而在“把微信接入、LangGraph 编排、分层记忆、可降级 RAG、配置热重载和运行观测，做成了一套可长期运行的本地 agent 基础设施”。

## 2. 最值得强调的差异化亮点

### 2.1 不是单点脚本，而是完整运行时

项目把微信消息接入、上下文加载、提示词构建、模型调用、流式回复、事实提取、向量写回、状态上报放进统一运行链，而不是散落在多个临时脚本里。

直接体现为：

- 微信入口抽象为 `BaseTransport`，主实现为 `wcferry`
- AI 主链路由 `LangChain + LangGraph` 编排
- 控制面同时覆盖 `Quart API + Electron`
- 回复之后仍有后台事实提取和记忆写回，不阻塞首响应

### 2.2 分层记忆不是堆功能，而是职责拆分

项目当前已经形成三层记忆结构：

1. 短期上下文：SQLite 中的最近对话
2. 运行期向量记忆：当前会话语义召回
3. 导出语料 RAG：历史真实聊天语料的风格召回

这套设计的价值在于：

- 让“事实延续”与“表达风格模仿”分开
- 让实时聊天的召回与离线导出语料的召回分开
- 让不同记忆层可以分别关闭、替换或调优，而不是全部绑死

### 2.3 RAG 做了精排，而且默认可回退

这个项目的 RAG 不是“只要检索命中了就塞进 Prompt”。当前实现已经有两层精排：

- 轻量重排：向量距离 + 关键词重合
- 可选本地 `Cross-Encoder` 精排：仅在本地模型目录存在且依赖可用时启用

这带来的差异化点是：

- 默认配置下就能运行，不要求用户先下载重模型
- 需要更高相关性时，可以按配置切换到本地精排
- 精排初始化失败时会自动回退到轻量重排，不阻断主链路

这比“要么没有精排，要么一上来就强绑重依赖”的方案更适合真实桌面环境。

### 2.4 LangGraph 不是包装层，而是运行时骨架

项目并不是把原有 HTTP 调用换成 `ChatOpenAI` 就结束，而是把主流程拆成可编排节点：

- `load_context`：只加载短期记忆和轻量画像摘要，保证对话快路径足够轻
- `build_prompt`：统一拼装系统提示、画像摘要、历史上下文和情绪/时间/风格注入，并在联系人 Prompt / 会话 override 缺少占位块时自动补齐系统必需段落
- 桌面端把系统提示和联系人专属 Prompt 都拆成“用户可编辑规则”和“只读固定注入块”，从 UI 层减少误改系统段落的机会
- `invoke`：统一走标准化兼容层，收敛字段映射、工具调用、错误结构和落盘元数据
- `finalize_request`：先完成落库，再把情绪、事实、向量写回、联系人专属 Prompt 更新和导出语料同步交给后台成长任务

也就是说，LangGraph 在这里不是 SDK 装饰层，而是整个回复运行时的组织方式。

### 2.5 可观测性不是附属功能，而是主链路的一部分

当前后端和桌面端已经具备一套比较完整的运行反馈闭环：

- `/api/status`：启动进度、诊断、健康检查、系统指标、检索统计
- `/api/status.reply_quality`：当前会话与近 `24h / 7d` 的回复成功率、空回复、超时补发、检索增强和人工反馈摘要
- `/api/metrics`：Prometheus 风格导出
- 备份能力不再停留在“能创建和恢复”，而是补齐了保留策略与清理闭环：CLI / Web API / 设置页都能先 Dry Run 预览、再正式清理旧备份，并默认保护最近恢复前快照
- Electron 仪表盘：CPU、内存、任务积压、AI 延迟、RAG 状态、组件健康
- 成本管理页：按会话分组查看模型消耗、输入输出 token、金额、估算与未定价状态
- 成本管理页现在还能直接看到 helpful / unhelpful 反馈分布，并把“没帮助”回复整理成可复盘列表，附带上下文摘要、检索增强摘要、复盘原因与建议动作
- 复盘列表支持按 `provider / model / preset / review_reason` 筛选，并可直接导出当前筛选结果为 JSON，便于做批量复盘
- 复盘结果会再按 `suggested_action` 聚合成“优先处理建议”，用于快速判断先调检索、先调提示词，还是先补上下文来源
- 优先处理建议支持一键回写到成本页筛选，直接缩小到对应动作的低质量回复
- 导出结果会附带动作级排查模板，把“看哪些配置、哪些状态、先做哪些检查”一起打包出去
- 实际使用路径已经闭环：先在消息详情里标记“有帮助 / 没帮助”，再到成本管理页点击“优先处理建议”或“导出复盘”做批量复盘
- 消息页现在统一优先显示好友备注名/昵称，不再把内部 `chat_id` 或微信号直接当作“发送者 / 会话”展示
- `/api/pricing` 与 `/api/costs/*`：把价格目录、模型聚合和会话级成本分析暴露为可复用接口
- Windows 发布链路：默认只发 `setup + portable`，通过 GitHub Actions 自动构建并生成“相对上个版本”的 Release Notes
- 安装版应用内自动更新：启动即检查 GitHub 最新 Release，弹窗展示更新说明，并支持跳过版本、后台下载和安装重启
- `/api/config/audit`：排查未知配置、未消费字段和预计生效策略

这意味着项目不是“出了问题只能翻日志”，而是能直接告诉使用者现在卡在哪、退化到了什么模式、哪些配置已经生效。

### 2.6 工程细节考虑的是长期运行，而不是一次演示

已经落地的工程优化点包括：

- 会话级锁，避免同一聊天并发写乱上下文
- Embedding 缓存和 pending 去重，减少重复请求
- `load_context` 阶段并发执行，压缩首响应等待时间
- `MemoryManager.get_recent_context_batch()` 批量取上下文，减少多会话场景下的数据库往返
- `AIClient` 共享 `httpx.AsyncClient` 连接池，并用引用计数回收
- SQLite 开启 `WAL`、`synchronous = NORMAL`、`temp_store = MEMORY`、`mmap`

这些点单独看都不“炫”，但组合起来决定了项目能不能稳定跑起来。

### 2.7 模型与认证中心升级，兼顾本机授权复用与工程边界

这次模型配置不再停留在“填一个 API Key”的单一路径，而是升级成了一个独立的模型与认证中心，重点解决两类真实问题：

- 用户已经在本机用 `codex`、`qwen` 或 `gemini` CLI 登录过，不希望每个桌面应用再重复维护一份 Token。
- 不同 Provider 的认证能力和风险边界并不一致，界面不能把“正式可用”和“实验支持”混在一起展示。

当前落地后的关键能力包括：

- 设置页与模型页职责拆分。设置页只保留机器人、提示词、日志、备份等通用配置，并展示当前生效模型摘要；所有模型预设、认证方式切换、授权状态刷新都集中到独立“模型”页。
- 每个 Provider 现在可以并存 `api_key / oauth / local_import / web_session` 多种认证方式，模型中心会统一管理自动优先级与手动指定规则：只配置 `API Key` 能完整运行，只配置 `OAuth / 本机同步` 也能完整运行，同时配置时默认优先 `OAuth / 本机同步`，当前认证不可用时自动回退到同一 Provider 下另一种可用认证。
- 模型卡片不再静态硬编码，而是由增强后的 model catalog 驱动，并按 `当前激活 -> 认证可用 -> 检测到本机登录但未绑定 -> 未配置` 排序；卡片状态明确区分 `当前生效 / OAuth 可用 / API Key 可用 / 待授权 / 实验能力`。
- `OpenAI / Codex / ChatGPT` 与 `Google / Gemini / Gemini CLI` 已补齐纯 OAuth / 本机同步直连对话链路，不再要求用户额外补一个 `API Key` 才能开始对话。
- 对支持本机授权复用的 Provider，项目不把本地认证源复制成长期真源，而是运行时按需读取本地标准授权位置或本地凭据缓存；因此本机认证变化后，项目内的实际认证也会跟着变化。
- 模型中心新增后台本机认证同步器，已支持“路径级 watcher + polling fallback”，负责缓存最近一次本机授权快照、变更指纹和手动强刷结果。
- 这轮继续补齐了 `Claude / Claude Code` 与 `Kimi / Kimi Code` 的真实本地发现器，以及 `Doubao / Yuanbao` 的浏览器 Cookie / Session 本地探测通路。
- 本轮又往下补了一层：模型中心同步器现在支持目录级 watch target，因此浏览器 `IndexedDB / Local Storage` 也能进入本机会话发现与跟随链路。
- Provider 卡片新增后端聚合的同步/健康摘要面板，用户可以直接看到“本机同步是否新鲜、默认认证最近一次检查是否通过、当前有多少条认证待处理”。
- 已绑定认证方法现在会继续显示 `运行时可用 / 运行时未就绪`，默认认证若被 runtime 阻塞，卡片会直接带出原因，避免把“本地已登录”和“真的能发请求”混成一个状态。
- 后端不再继续往单一 OAuth 文件堆逻辑，而是拆成 `provider registry + status resolver + runtime auth resolver + flow runner` 四层，让新增 Provider、实验能力控制和运行时适配有清晰边界。
- 最新一轮前端又把模型中心改成“左侧紧凑 Provider 列表 + 右侧向导/工作台”的主从结构，默认只暴露最明显的下一步，明显降低信息密度。
- 未配置时右侧直接给三步向导：`选择模型 -> 选择认证方式 -> 设为回复模型`；已配置后自动切换到紧凑工作台，3 次点击内就能完成换模型或换认证。
- 模型切换也改成了傻瓜式：在 `改模型` 弹窗里既能保存默认模型，也能一键 `保存并用于回复`；当前活跃 Provider 则直接显示 `切换当前模型`。
- 认证配置不再把 API Key、OAuth、会话导入、本机同步全部平铺在页面里，而是统一收敛到工作流弹窗；首次触发时再按认证方式展示一次极简说明。
- 模型页主按钮、状态词和操作入口统一改成中文，重复说明和低频元信息折叠收纳，让非技术用户也能靠直觉完成配置。
- 最新补丁又把一条易用性短板补齐了：工作台里已配置的 `API Key` 也能直接重设，`Doubao / Yuanbao` 这类 `web_session` 方法的 `去登录` 会直接打开网页登录页，而不是把用户带进错误弹窗。

Provider 分层策略也更清晰：

- 已接入核心能力：`OpenAI / Codex / ChatGPT`、`Google / Gemini / Gemini CLI`、`Qwen / DashScope / Qwen Code`、`Doubao / 火山方舟 / TRAE`、`Yuanbao / 元宝`
- 扩展预留：`Claude / Claude Code`、`Kimi / Moonshot / Kimi Code`、`GLM / 智谱`、`MiniMax`、`DeepSeek`
- `Qwen` 的 `DashScope API Key` 与 `Coding Plan API Key` 现在是同一 Provider 下的两条独立认证方法，卡片会分别展示推荐模型、入口和能力说明
- `Doubao / Yuanbao` 的网页登录当前按 `web_session` 建模，不伪装成标准 OAuth
- `Claude / Claude Code` 现在会探测 `~/.claude.json` / `~/.claude/settings.json` / `~/.claude/.credentials.json` / `C:/ProgramData/ClaudeCode/managed-settings.json`，并在本地存在 `apiKeyHelper` 或 Claude API credential cache 时直接进入 `anthropic_native` 运行时；`Kimi / Kimi Code` 现在会探测 `~/.kimi/config.toml` / `~/.kimi/credentials/*.json`
- `Claude / Claude Code` 进入 `anthropic_native` 运行时后，如果 helper 或本地 credential cache 已在后台轮换，首次 `401` 会先强制刷新一次本地认证并自动重试，降低短暂失配带来的失败率
- `Doubao / Yuanbao` 现在会优先探测本机浏览器 Cookie 数据库、`IndexedDB / Local Storage`、桌面私有存储或显式导出 Session 文件，并通过 `web_session + follow mode` 接入统一状态机
- 模型中心现在还会把 `system_keychain` 纳入补充发现信号，并把 `keychain_provider / keychain_targets` 一并带进 Provider 状态卡片
- `Kimi / Kimi Code` 的本机认证已经开始进入真实运行时链路：优先跟随 `~/.kimi/config.toml` 的本地 provider 配置，必要时再回退到 `~/.kimi/credentials/*.json`，同时方法级默认 `base_url / model` 会跟着切到 Kimi Coding endpoint

这部分改动的价值不只是“多了几个登录按钮”，而是把模型切换、认证状态、风险提示、运行时凭证来源和 UI 反馈统一进了一套能长期维护的工程结构中。

## 3. 技术难点与解决思路

### 3.1 难点一：微信自动化不是标准 API，对运行环境极其敏感

这个项目运行在 Windows 微信生态上，传输层本身就带有几个现实约束：

- 需要匹配指定微信版本
- `wcferry` 依赖注入微信进程
- 在 Windows 下需要管理员权限
- 消息接收链路不是天然稳定的，需要等待登录、处理通道初始化和失败重试

对应做法：

- 把接入边界抽象成 `BaseTransport`
- 在 `WcferryTransport` 内做版本门禁、管理员权限检查、消息通道就绪等待和错误包装
- 通过 `get_transport_status()` 把微信版本、所需版本、能力信息和 warning 暴露给上层

解决的核心不是“把微信连上”，而是“把不稳定边界关进传输层里”。

### 3.2 难点二：RAG 相关性和部署复杂度天然冲突

只做向量召回，结果往往不稳定；直接引入重型精排，又会把部署门槛、资源占用和失败面抬高。

这个项目的取舍是：

- 默认用轻量重排保证基础效果
- 用户明确提供本地模型目录时，再启用 `Cross-Encoder`
- 不自动联网下载模型
- 精排失败自动回退，并在状态接口里暴露当前实际精排后端与回退次数

这是一种偏工程化的做法，重点不是追求理论最佳，而是追求“默认可跑、增强可配、失败可退”。

### 3.3 难点三：热重载要保证一致性，不能让 GUI 和运行时各读各的

桌面端可配项很多，如果还是让各模块各自读配置文件，长期一定会出现：

- GUI 显示值和实际生效值不一致
- 热重载后局部模块生效、局部模块不生效
- 不知道哪些配置修改需要重连、哪些可以即时生效

项目当前通过中心化 `Config Snapshot` 解决这个问题：

- 后端统一发布当前有效配置快照
- GUI 保存后返回 `changed_paths` 与 `reload_plan`，并将非敏感字段同步回写默认配置文件
- `/api/config/audit` 输出未知 override、未消费字段和生效策略摘要
- 热重载优先用 `watchdog`，缺失依赖时再回退轮询，并保留防抖

核心价值是把“配置文件”升级成“可解释的运行时配置系统”。

### 3.4 难点四：首响应速度和后台增强能力要兼得

如果把记忆、RAG、情绪分析、事实提取、写库全部串行执行，回复延迟会很差；如果一味异步化，又容易造成上下文混乱或状态不可控。

当前实现的关键做法是：

- 把同步对话链收敛为“短期上下文 + 轻量画像摘要”
- 把 RAG、情绪分析、事实提取、向量写回、联系人专属 Prompt 更新和导出语料同步统一改为后台成长任务
- 用会话级锁保证单会话回复顺序
- 对成长任务逐步做失败隔离，避免任一增强步骤拖垮主回复链路

这让系统更接近“回复优先、增强随后完成”的产品体验。

### 3.5 难点五：本地桌面型 agent 必须能排障

这类项目最怕的不是单次报错，而是用户不知道为什么没回、卡在哪、当前到底是配置问题、模型问题还是微信侧问题。

所以项目把诊断能力前置成标准输出：

- 启动过程有 `startup`
- 故障归因有 `diagnostics`
- 组件级状态有 `health_checks`
- 压力和延迟有 `system_metrics`
- 外部采集有 `/api/metrics`

这部分通常最容易被忽视，但恰恰决定了项目是不是“可维护系统”。

## 4. 对外介绍时建议重点强调的话术

如果要对外介绍这个项目，建议优先强调以下几点：

- 不是普通微信自动回复，而是把微信接入、记忆、RAG、LangGraph 编排和可观测性做成统一运行时
- 不是单模型绑定，而是兼容 OpenAI-compatible 生态，模型供应商可以替换，运行时链路不需要重写
- 不是只有召回，还做了轻量精排和可选本地 `Cross-Encoder` 精排，并且支持失败自动回退
- 不是只追求功能可用，而是补齐了配置热重载、状态诊断、指标导出和工程级降级策略

## 5. 证据索引

下面这些文件可以直接作为亮点表述的证据来源：

- `backend/core/agent_runtime.py`：LangGraph 运行时、并发上下文准备、精排与回退、Embedding 缓存、后台任务
- `backend/core/ai_client.py`：共享 `httpx.AsyncClient` 连接池、引用计数释放
- `backend/core/memory.py`：SQLite 记忆层、批量上下文读取、WAL 和 mmap 优化
- `backend/core/config_service.py`：中心化配置快照与运行时发布
- `backend/api.py`：`/api/status`、`/api/metrics`、本机访问限制与配置接口
- `backend/transports/base.py`：传输层抽象边界
- `backend/transports/wcferry_adapter.py`：版本门禁、管理员权限校验、消息接收通道初始化与状态暴露
- `tests/test_agent_runtime.py`：运行时上下文聚合、缓存命中、Cross-Encoder 精排测试
- `tests/test_optimization_tasks.py`：连接池复用、批量上下文、传输层抽象与重排测试
- `tests/test_runtime_observability.py`：配置监听、防抖、健康检查与指标导出测试

## 补充亮点：运行准备度与自愈排障

项目现在把“能不能跑起来”前置成一条明确链路，而不是把用户直接丢给日志。

新增能力：

- `run.py check`、`run.py check --json`、`GET /api/readiness` 与桌面端首次运行引导共用同一套 readiness 检查逻辑
- Dashboard 常驻“运行准备度”卡片，持续展示当前还差什么才能启动
- 首次运行引导只聚焦非技术用户最容易理解的阻塞项：管理员权限、微信是否已启动、版本兼容、可用模型与认证
- 每个阻塞项都直接绑定动作：`打开微信`、`前往设置`、`重新检查`
- Electron 主进程支持导出自动脱敏的诊断快照，统一打包 `/api/status`、`/api/readiness`、`/api/config/audit`、更新器状态和最近日志摘要

这让项目从“功能能跑”进一步变成“知道为什么跑不起来，并能指导用户自救”。

## 补充亮点：自动提权与智能恢复

- Windows 桌面端支持自动提权重启：当 readiness 判定缺少管理员权限时，用户可以直接在应用内触发 UAC 重启，而不是依赖手动关闭再重开。
- “运行诊断”与“运行准备度”不再割裂：恢复按钮会优先处理启动前阻塞项，例如管理员权限、微信未启动、配置未补齐；运行态没有阻塞项时才回退到 `/api/recover`。
- `run.py check` 的提示与桌面端动作保持一致，减少“命令行说要管理员，桌面端却只能重试”的割裂体验。

## 补充亮点：稳定性产品化闭环

这一轮补的是“长期使用能力”，不是再堆一层 demo 功能：

- 回复策略前置到统一 evaluator，命中新联系人、静音时段、敏感词或显式手动模式时，不再冒险直接发送，而是进入可审阅、可编辑、可拒绝的持久化待审批队列。
- 工作区备份与恢复形成闭环：支持 `quick/full` 两种备份、`backup_manifest.json` 清单、恢复前 `dry-run` 校验、`checksum_summary` 完整性校验，以及 `pre-restore` 自动快照，强调可恢复而不是只做导出。
- `run.py backup list/create/verify/cleanup/restore` 让这套恢复能力从“只有界面里能点”升级成“可以脚本化演练和 headless 运维”，同时控制长期运行下的备份膨胀。
- 离线评测从“主观感觉质量还行”升级成确定性门禁：固定 smoke 数据集、固定指标、固定回归阈值，并直接接入 CI。
- Electron renderer 目录单独声明 ESM 边界，消除了 `MODULE_TYPELESS_PACKAGE_JSON` 警告，同时保持主进程 CommonJS，不把模块制式切换扩散成全仓重构。

这组能力说明项目已经不只是“把微信接上大模型”，而是在往“可长期运行、可恢复、可验证”的个人产品演进。

可以直接作为证据的新增实现包括：

- `backend/core/reply_policy.py`
- `backend/core/workspace_backup.py`
- `backend/core/eval_runner.py`
- `backend/core/memory.py` 中的 `pending_replies` 表与相关方法
- `backend/api.py` 中的回复策略、待审批回复、备份恢复与评测接口
- `run.py eval`
- `run.py check --json`
- `run.py backup`
- `tests/test_reply_policy.py`
- `tests/test_backup_service.py`
- `tests/test_eval_runner.py`
- `tests/node/renderer_esm_boundary.test.mjs`

## 补充亮点：Provider + Auth Framework

- 模型与认证不再围绕少数示例 Provider 写死，而是升级成统一的 Provider registry、Auth method registry、状态聚合与动作编排框架。
- 同一 Provider 现在可以并存 `api_key / oauth / local_import / web_session` 多种认证方法；运行时默认优先 `OAuth / 本机同步`，也支持手动固定当前认证，并在当前认证失效时自动回退到同一 Provider 下另一种可用认证。
- 旧 `api.presets + active_preset` 运行时链路继续保留，但由新的认证中心统一投影生成，兼顾扩展性与兼容性。
- API Key 与 Session 改为后端安全存储；本地 CLI/Auth 同步则优先保存绑定关系与来源信息，不复制长期明文凭据。
- `OpenAI / Codex / ChatGPT` 与 `Google / Gemini / Gemini CLI` 的 OAuth 现已支持直接进入对话链路，真正做到“登录后即可用”。
- 详细矩阵、扩展方式与安全边界见 `docs/MODEL_AUTH_CENTER.md`。
