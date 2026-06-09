# Windows 安全模型与 IPC 审查清单

本文记录 Windows 桌面端在高权限微信接入场景下的安全边界、失败模式和回归检查点。它用于发布前审查和问题复盘，不表示已经完成真实安装包验签、代码签名证书审计或升级演练。

## 运行边界

- 当前官方支持环境仍是 Windows 10/11、微信 PC `3.9.12.51` 和默认传输后端 `wcferry`。
- 默认 `wcferry` 需要管理员权限和微信桌面进程；这让桌面端、后端进程和微信进程都处在更高影响面的本机信任边界内。
- Electron 桌面端会生成运行时 `WECHAT_BOT_API_TOKEN` 和 `WECHAT_BOT_SSE_TICKET`，后端 API 默认绑定本机回环地址；非回环绑定必须显式设置 `WECHAT_BOT_API_TOKEN`。
- 共享配置真实源是 `data/app_config.json`；发布或升级检查不能覆盖生产配置，也不能泄露真实密钥、聊天正文或诊断原始日志。

## 主要威胁与失败模式

1. 高权限进程误用
   - 风险：管理员权限下的 Electron 主进程或后端若暴露任意文件、任意命令或任意 HTTP 转发能力，影响面会放大到本机用户数据和微信会话环境。
   - 当前边界：`src/main/ipc.js` 只允许主渲染入口页调用受控 IPC，后端请求经 `ALLOWED_BACKEND_PATHS` 和 `ALLOWED_BACKEND_PATH_PATTERNS` 转发。
   - 审查要点：新增 IPC 时必须说明调用方、允许参数、是否触达文件系统/进程/网络，以及失败时返回的脱敏错误。

2. 渲染层逃逸或非预期导航
   - 风险：如果 renderer 获得 Node 能力、加载非受控页面或被重定向到外部 URL，preload 暴露的桌面能力可能被非预期页面调用。
   - 当前边界：`src/main/index.js` 中主窗口和 splash 均启用 `contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`、`webSecurity: true`；主窗口拦截 `window.open`、`will-navigate` 和 `will-redirect`。
   - 审查要点：任何窗口创建、导航、外链打开或 preload 变更，都要确认仍只加载受控本地入口，外链只能通过受控策略交给系统浏览器。

3. 本机 API 转发扩大化
   - 风险：`backend:request` 若允许任意路径、任意方法或超大 payload，renderer bug 可能绕过 API 边界触发管理接口、数据清理或资源耗尽。
   - 当前边界：`src/main/ipc.js` 只允许 `GET` 和 `POST`，限制 endpoint、query 和 payload 大小，`GET` 禁止携带 body。
   - 审查要点：新增 API 转发必须优先用精确路径；只有确实需要 ID 路径时才使用正则，并限制在单个资源层级。

4. 本机文件读取扩大化
   - 风险：知识库或诊断入口如果接收任意路径，可能暴露完整本机路径、聊天导出、凭据文件或大文件内容。
   - 当前边界：知识库文件选择只通过 `knowledge-base:select-file` 打开单文件对话框，仅允许 `.txt/.md/.markdown`，限制普通文件、大小和内容长度，返回 `.../<filename>` 形式来源。
   - 审查要点：不要新增目录扫描、glob、递归读取或 renderer 传入路径读取；确需固定目录能力时，应写明目录、扩展名、大小、是否 dry-run 和返回脱敏字段。

5. 诊断资料外泄
   - 风险：排障支持包可能包含 API Key、token、OAuth/session、聊天正文、联系人真实标识或完整路径。
   - 当前边界：`src/main/diagnostics-snapshot.js` 在本地写出前应用敏感值、聊天正文、联系人标识和本机路径脱敏，并包含 `privacy_notice`。
   - 审查要点：新增诊断字段时，必须确认是否属于密钥、联系人、聊天内容、路径或完整异常文本；不确定时默认只输出摘要、计数、短 reason 或 hash 引用。

## IPC 回归检查表

发布前至少确认：

- `src/main/index.js` 主窗口和 splash 仍启用 `contextIsolation`、禁用 `nodeIntegration`，并开启 `sandbox` 与 `webSecurity`。
- 主窗口仍拦截非受控 `window.open`、`will-navigate` 和 `will-redirect`。
- `src/preload/index.js` 只通过 `contextBridge.exposeInMainWorld('electronAPI', ...)` 暴露受控方法，不暴露 `ipcRenderer`、`require`、`fs`、`shell` 或通用执行能力。
- `src/main/ipc.js` 的 IPC 处理仍经过 `handleTrusted` 和 `assertTrustedRendererSender`。
- `backend:request` 仍使用 allowlist，且新增路径有对应业务边界和测试依据。
- 文件选择、诊断导出、更新安装、管理员重启等高影响 IPC 仍由主进程完成校验和用户确认，不接受 renderer 传入的任意本机路径。
- 诊断支持包仍默认脱敏密钥、token、OAuth/session、聊天正文、联系人标识和完整本机路径。

## 自动门禁覆盖范围

`scripts/check_windows_release_readiness.py` 会执行 `electron_security_baseline` 静态检查，确认 Electron 窗口加固、preload 受控 API、IPC sender 校验、后端请求 allowlist、知识库文件选择限制和诊断脱敏相关标记仍存在。

该检查只用于阻止明显回归，不替代代码审查。它不能证明：

- IPC 参数验证在所有业务路径上都完整。
- 真实 Windows 安装包已经可安装、可升级或可回滚。
- 代码签名证书、时间戳服务和证书链信任已经完成生产审计。
- 微信 `wcferry` 注入、真实收发消息和长期运行稳定性已经在目标机器通过。

## 变更准入规则

- 新增高影响 IPC 前，先补充威胁或失败模式，再实现。
- 新增发布门禁前，优先选择只读、可重复、不会修改 release 产物的检查。
- 涉及配置、凭据、诊断、更新、管理员提权或本机文件访问时，验证记录必须说明执行命令、结果和未覆盖风险。
