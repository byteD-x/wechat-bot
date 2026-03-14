# 微信聊天记录解密与导出指南

这份文档是给第一次折腾微信聊天记录导出的用户准备的。  
目标只有一个：把微信聊天记录变成这个项目可用的 CSV。

---

## 你最终要得到什么

你最后需要拿到两样东西：

1. 一份“已解密”的微信数据库目录
2. 通过本项目导出的联系人聊天 CSV

流程图可以简单理解成：

```text
微信正在登录
    ↓
找到当前账号目录和数据库密钥
    ↓
把数据库解密到新目录
    ↓
用本项目导出联系人聊天记录为 CSV
    ↓
再做 Prompt 生成或 RAG 增强
```

---

## 1. 开始前先确认

请先确认以下条件：

1. 你在 Windows 上操作。
2. 微信 PC 版已经登录。
3. 你操作的是你自己的聊天数据。
4. 你知道解密后的数据库、导出的 CSV 都属于高敏感隐私数据。

建议额外注意：

- 微信尽量保持打开，不要最小化。
- 操作前最好先备份你的原始数据目录。
- 不要把解密结果上传到公开网盘或代码仓库。

---

## 2. 微信聊天数据通常在哪

常见默认目录通常类似：

```text
C:\Users\你的用户名\Documents\WeChat Files\<wxid>\
```

在这个账号目录下，经常能看到这些内容：

```text
Msg
FileStorage
Config
```

其中你最关心的是：

```text
<账号目录>\Msg
```

但这里有一个关键点：

> 原始 `Msg` 目录里的数据库通常是加密状态，不能直接拿给本项目导出。

---

## 3. 推荐方案：先用专门工具拿到 `db_key` 和已解密数据库

### 为什么推荐这样做

因为本项目的强项是：

- 导出 CSV
- 生成个性化 Prompt
- 做导出语料 RAG 增强

而“从运行中的微信进程提取数据库密钥并批量解密”这一步，在当前仓库里属于底层能力，不是面向新手的一键入口。

### 推荐思路

建议你用独立的微信数据库解密工具，先做这两步：

1. 读取当前登录账号信息，拿到 `wx_dir` 和 `db_key`
2. 把数据库批量解密到一个新目录

我联网查到的一个公开可访问参考是 `wdecipher` 的 PyPI 页面。它公开说明里写明支持：

- 获取当前登录微信账号信息
- 定位工作目录
- 获取数据库密钥
- 解密微信数据库

参考链接：

- `wdecipher`：<https://pypi.org/project/wdecipher/>

### 推荐操作方式

建议在单独环境里做，不要污染你当前项目环境：

```bash
python -m venv .venv-export
.venv-export\Scripts\activate
pip install wdecipher
```

然后按照它的公开说明完成：

1. 获取当前登录微信信息
2. 找到 `wx_dir`
3. 获取 `db_key`
4. 将数据库解密到新目录

你解密完成后，建议把结果放在一个独立目录，类似：

```text
E:\decrypted_wechat\wxid_xxx\Msg
```

这样后续导出、复用和备份都更清晰。

---

## 4. 如果你想参考本仓库内的底层实现

本仓库已经包含相关底层代码，路径在：

- `tools/wx_db/decrypt/get_wx_info.py`
- `tools/wx_db/decrypt/decrypt_v3.py`
- `tools/wx_db/decrypt/decrypt_v4.py`

它们体现的是这套思路：

1. 从运行中的微信进程读取账号目录和密钥
2. 针对不同数据库版本执行批量解密

但请注意：

- 当前仓库没有把这一步封装成适合小白的完整 CLI
- 这部分还依赖一些额外组件，例如 `pycryptodome`、`pymem`、`pywin32`
- 如果你只是想快速导出聊天记录，不建议从这里起步

更适合的用户：

- 熟悉 Python 环境管理
- 能自己看源码
- 能接受排查底层依赖问题

---

## 5. 如何判断你已经“解密成功”

解密成功后，你应该具备以下特征：

1. 你已经拿到某个账号对应的目录。
2. 目录下有 `Msg`。
3. `Msg` 下存在 `.db` 文件。
4. 这些数据库可以被后续导出程序正常读取。

对于本项目来说，最关键的验证标准是：

> 你把这份目录传给 `tools.chat_exporter.cli` 后，不再报 `db init failed`。

---

## 6. 用本项目导出聊天记录 CSV

当你已经有“已解密的 `Msg` 目录”后，就可以直接导出。

示例：

```bash
python -m tools.chat_exporter.cli --db-dir "E:\decrypted_wechat\wxid_xxx\Msg" --contact "张三"
```

如果你要导出多个联系人：

```bash
python -m tools.chat_exporter.cli --db-dir "E:\decrypted_wechat\wxid_xxx\Msg" --contact "张三" --contact "李四"
```

如果你要带时间范围：

```bash
python -m tools.chat_exporter.cli --db-dir "E:\decrypted_wechat\wxid_xxx\Msg" --contact "张三" --start "2024-01-01 00:00:00" --end "2025-12-31 23:59:59"
```

参数说明：

- `--db-dir`：已解密的 `Msg` 目录
- `--contact`：联系人昵称、备注或 wxid，可重复传
- `--db-version`：微信数据库版本，默认是 `4`
- `--include-chatrooms`：包含群聊
- `--output-dir`：导出目录，默认 `chat_exports`

导出成功后，通常会生成：

```text
chat_exports/聊天记录/张三(wxid_xxx)/张三.csv
```

---

## 7. 导出后还能做什么

导出 CSV 之后，你可以继续体验两条功能链路。

### 方案 1：生成个性化 Prompt

```bash
python -m tools.prompt_gen.generator
```

它会分析导出的聊天记录，产出适合写进配置的个性化提示词。

### 方案 2：开启导出语料 RAG

如果你已经在设置里开启：

- `export_rag_enabled`
- `export_rag_auto_ingest`

程序会自动扫描 `chat_exports/聊天记录`，把你本人过往对这个联系人的表达做成本地风格索引。  
后续对话时，就会优先参考这些真实历史表达，让回复更像你本人。

---

## 8. 最推荐的新手完整路径

如果你只想最省心地体验完整能力，按这个顺序走：

1. 登录微信 PC。
2. 用独立解密工具拿到 `wx_dir`、`db_key` 和已解密数据库。
3. 用本项目导出 1 个最常聊联系人的 CSV。
4. 启动本项目，确认基础自动回复正常。
5. 开启导出聊天记录 RAG。
6. 再和这个联系人聊天，观察回复是否更像你本人。

为什么只推荐先导出 1 个联系人：

- 排查最简单
- 效果最容易观察
- 出问题时定位最清楚

---

## 9. 常见报错怎么理解

### `db-dir not found`

原因：

- 你传入的目录不存在
- 路径写错了

处理：

- 重新检查 `--db-dir`
- 确认最终指向的是 `Msg` 目录

### `db init failed: check db_dir/db_version`

原因通常是：

- 目录不是解密后的数据库目录
- `db_version` 不对
- 目录结构不完整

处理：

1. 优先确认是不是解密没成功
2. 再确认版本是否为 3 或 4
3. 再确认目录里是否真的有 `.db`

### `no contacts matched the filter`

原因：

- 联系人名字没匹配上
- 备注和昵称跟你输入的不一致

处理：

- 先尝试更完整的备注名
- 不行就直接传 wxid

---

## 10. 隐私与合规提醒

聊天记录导出和解密是高敏感操作。

你至少要做到：

1. 只处理你自己的数据。
2. 解密结果只保存在本地。
3. 不把 CSV、数据库、`chat_exports` 提交到 Git。
4. 不把原始聊天记录随手发给别人帮你排查问题。

另外，和微信数据库提取相关的开源工具经常会因为合规风险变动。  
我联网检索时也看到 `PyWxDump` 当前仓库已经公开标注移除通知，因此你在使用任何第三方解密工具前，都应该先自行判断风险。

参考链接：

- `wdecipher`：<https://pypi.org/project/wdecipher/>
- `PyWxDump` 仓库当前状态：<https://github.com/xaoyaoo/PyWxDump>
