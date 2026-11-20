# wecom-ha

Home Assistant 企业微信通知集成，支持**文本 / Markdown / 图文（news）**消息、**多实例**、**应用别名**与**默认接收人**。

> 本文档包含完整的安装指南与功能原理详解，适合快速上手与深入了解集成行为。近期修复了多实例选择、token 失效重试、选项更新等多处问题（见[更新记录](#更新记录)）。

---

## 目录

- [功能特性](#功能特性)
- [安装](#安装)
- [配置](#配置)
- [服务调用](#服务调用)
- [参数说明](#参数说明)
- [架构与数据流](#架构与数据流)
- [核心功能详解](#核心功能详解)
- [内部机制](#内部机制)
- [依赖与兼容性](#依赖与兼容性)
- [调试](#调试)
- [已知问题与自动化](#已知问题与自动化)
- [更新记录](#更新记录)
- [License](#license)

---

## 功能特性

- 通过企业微信「应用」发送消息给成员、部门或标签
- 支持 `text`、`markdown`、`news`（图文）三种消息类型
- 支持添加多个企业微信应用实例
- 支持为实例设置别名，服务调用时按别名选择应用
- 支持配置默认接收人，调用服务时可省略接收方参数
- `access_token` 自动缓存、提前刷新，失效时自动重试
- 支持「保密消息」与「重复消息检查」
- 多实例并发安全：token 刷新加锁，避免重复获取

---

## 安装

### 方式一：HACS（推荐）

1. HACS → 集成 → 右上角菜单 → 自定义存储库
2. 添加本仓库地址，类别选择「集成」
3. 搜索「企业微信通知」并安装
4. 重启 Home Assistant

### 方式二：手动安装

1. 将 `custom_components/wecom` 目录复制到 HA 配置目录下的 `custom_components/`
2. 重启 Home Assistant

最终目录结构：

```text
custom_components/wecom/
├── __init__.py
├── config_flow.py
├── const.py
├── manifest.json
├── services.yaml
├── strings.json
└── translations/
    ├── zh-Hans.json
    └── zh.json
```

---

## 配置

1. 设置 → 设备与服务 → 添加集成 → 搜索「企业微信通知」
2. 填写：

| 字段 | 说明 | 必填 |
| --- | --- | --- |
| 企业 ID（CorpID） | 企业微信管理后台「我的企业」中获取 | 是 |
| 应用 Secret | 自建应用的 Secret | 是 |
| 应用 AgentId | 自建应用的 AgentId | 是 |
| 默认接收成员 | 未指定接收方时使用的成员 UserID，多个用 `\|` 分隔 | 否 |
| 应用别名 | 用于多实例时区分应用 | 否 |

3. 提交时会尝试获取 `access_token` 验证凭据，成功后创建条目。唯一标识为 `CorpID_AgentId`，同一企业可添加多个不同应用。
4. 添加后可在集成卡片「配置」中修改以上信息，**保存后会自动重载生效**。

---

## 服务调用

服务：`wecom.send_message`

### 发送文本消息

```yaml
action: wecom.send_message
data:
  message: "您好，这是一条测试消息。"
  touser: "zhangsan|lisi"
```

### 发送 Markdown 消息

```yaml
action: wecom.send_message
data:
  message: "**告警**：温度过高"
  message_type: markdown
  toparty: "1"
```

### 发送图文消息（news）

```yaml
action: wecom.send_message
data:
  message_type: news
  touser: "zhangsan"
  articles:
    - title: "今日头条"
      description: "这是一条图文消息"
      url: "https://example.com"
      picurl: "https://example.com/pic.jpg"
```

### 使用默认接收人

配置中填写「默认接收成员」后，调用时可省略 `touser` / `toparty` / `totag`：

```yaml
action: wecom.send_message
data:
  message: "这条消息发给默认接收人"
```

### 多实例时选择应用

使用配置时设置的别名：

```yaml
action: wecom.send_message
data:
  message: "发给办公应用"
  app_name: "办公应用"
```

或使用配置条目 ID：

```yaml
action: wecom.send_message
data:
  message: "发给指定实例"
  config_entry_id: "abcdef123456"
```

> 未指定 `app_name` 或 `config_entry_id` 时，使用第一个添加的应用。

---

## 参数说明

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `message` | text/markdown 必填 | `""` | 消息正文；news 类型可留空 |
| `message_type` | 否 | `text` | `text`、`markdown`、`news` |
| `touser` | 否 | — | 成员 UserID，多个用 `\|` 分隔 |
| `toparty` | 否 | — | 部门 ID，多个用 `\|` 分隔 |
| `totag` | 否 | — | 标签 ID，多个用 `\|` 分隔 |
| `articles` | news 必填 | — | 图文列表，每项含 `title`、`url`，可选 `description`、`picurl` |
| `safe` | 否 | `0` | 是否保密消息，0/1 |
| `enable_duplicate_check` | 否 | `0` | 是否开启重复消息检查，0/1 |
| `duplicate_check_interval` | 否 | `1800` | 重复检查间隔（秒），范围 0~86400 |
| `app_name` | 否 | — | 按应用别名选择实例 |
| `config_entry_id` | 否 | — | 按配置条目 ID 选择实例 |

> `touser`、`toparty`、`totag` 至少指定一个；均未指定时使用配置中填写的「默认接收成员」。

---

## 架构与数据流

```text
                     ┌──────────────────────┐
                     │   HA 自动化/脚本调用  │
                     │  wecom.send_message  │
                     └──────────┬───────────┘
                                │ 服务参数
                                ▼
              ┌─────────────────────────────────────┐
              │      handle_send_message 服务处理    │
              │  • 按 app_name / config_entry_id    │
              │    定位目标配置条目                  │
              │  • 未指定时用第一个实例              │
              └──────────┬──────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          │ 每个配置条目持有一个 WeComAPI 实例
          ▼                             ▼
 ┌────────────────────┐       ┌────────────────────┐
 │ 应用 A 的 WeComAPI  │       │ 应用 B 的 WeComAPI  │
 │ (corp/secret/agent) │       │ (corp/secret/agent) │
 └─────────┬──────────┘       └─────────┬──────────┘
           │                            │
           └────────────┬───────────────┘
                        ▼
        ┌────────────────────────────────────┐
        │  get_access_token()                │
        │  • 缓存有效直接返回（加锁防并发）    │
        │  • 提前 300s 过期，失效强制刷新重试  │
        └────────────────┬───────────────────┘
                         ▼
        ┌────────────────────────────────────┐
        │  POST /cgi-bin/message/send        │
        │  ?access_token=xxx  (JSON 消息体)   │
        └────────────────┬───────────────────┘
                         ▼
                  企业微信服务器
```

核心对象：

- **ConfigEntry（配置条目）**：每个企业微信应用对应一个条目，保存 corp_id / secret / agent_id / 默认接收人 / 别名。
- **WeComAPI**：每个条目一个实例，封装 token 管理与消息发送。
- **hass.data[DOMAIN]**：以 `entry_id` 为键存 `{config, api}`，另有 `aliases` 保留键存别名到条目的映射。
- **全局服务**：只在第一个条目加载时注册一次，最后一个条目卸载时移除。

---

## 核心功能详解

### 三种消息类型

服务按 `message_type` 构造不同的请求体：

- **text**：`{"msgtype": "text", "text": {"content": message}}`
- **markdown**：`{"msgtype": "markdown", "markdown": {"content": message}}`
- **news**：`{"msgtype": "news", "news": {"articles": [...]}}`，文章列表由 `articles` 参数构造，每项含 `title`、`url` 及可选的 `description`、`picurl`。

text/markdown 要求 `message` 非空；news 不需要正文，`message` 可留空。

### access_token 管理

企业微信 API 调用需要先获取 `access_token`（有效期通常 7200 秒）。集成的实现要点：

1. **缓存**：token 与过期时间存在 WeComAPI 实例中，缓存有效时直接返回，避免每次发消息都请求。
2. **提前刷新**：过期时间按 `expires_in - 300 秒` 计算，留出缓冲，避免在过期临界点使用即将失效的 token。
3. **并发安全**：用 `asyncio.Lock` 保护刷新逻辑，多个并发调用不会重复获取 token。
4. **失效重试**：若服务端返回错误码 `40014 / 42001 / 42007 / 42009`（token 失效），会强制刷新 token 并重试一次。这解决了「本地缓存未过期但服务端已失效」导致消息持续发送失败的问题。
5. **UTC 时间**：过期判断使用 UTC 时间，避免本地时区 / 夏令时偏差。

### 多实例与别名

- 可添加多个企业微信应用条目（唯一标识 `CorpID_AgentId`）。
- 每个条目可设一个别名，加载时建立 `别名 → entry_id` 映射。
- 服务调用时：
  - 指定 `app_name` → 按别名查映射
  - 指定 `config_entry_id` → 直接按 ID 定位
  - 都不指定 → 用第一个配置条目
- 别名重复时会记录警告日志，并指向最新配置的条目。

### 默认接收人

配置中的「默认接收成员」在发送时作为回退值：当调用服务未指定 `touser` / `toparty` / `totag` 任何一个时，自动用默认值作为 `touser`。若既没有指定接收方、也没有配置默认值，则抛出「必须指定接收方」错误。

### 选项更新生效

在集成选项里修改凭据或别名后，保存时会调用 `async_reload` 重载条目，确保运行中的 API 实例使用新配置——不会出现「界面改了但发送仍用旧值」的问题。

---

## 内部机制

### 数据存储结构

`hass.data["wecom"]` 的结构：

```python
{
    "<entry_id_1>": {
        "config": {...},      # 配置数据副本
        "api": WeComAPI(...), # 该条目的 API 实例
    },
    "<entry_id_2>": {...},
    "aliases": {              # 保留键：别名 → entry_id
        "办公应用": "<entry_id_1>",
    },
}
```

> 注意 `aliases` 是保留键，与真正的条目标键共存。服务处理与卸载逻辑都显式排除它，避免误把它当成配置条目。

### 服务参数校验

`SEND_MESSAGE_SCHEMA` 对服务参数做校验：

- `message_type` 必须是三种合法类型之一
- `safe`、`enable_duplicate_check` 限制为 0/1
- `duplicate_check_interval` 限制 0~86400
- `articles` 按文章架构逐项校验（`title`、`url` 必填）
- 允许额外参数（`extra=vol.ALLOW_EXTRA`）

### 卸载清理

卸载某个条目时：

1. 从 `hass.data` 移除该条目数据
2. 若该条目有别名且映射指向它，删除别名映射
3. 若已无任何配置条目（排除 `aliases` 保留键），移除全局服务并清空 `hass.data[DOMAIN]`

---

## 依赖与兼容性

| 项目 | 要求 |
| --- | --- |
| Home Assistant | 支持 UI 配置流程的现代版本（建议最新稳定版） |
| aiohttp / voluptuous | HA 内置 |
| pytraccar | 不需要（本集成直接调用企业微信 HTTP API） |
| 企业微信 | 需自建应用并具备 CorpID / Secret / AgentId |

本集成使用 HA 自带的 aiohttp 会话，无需额外的外部 Python 依赖（`requirements: []`）。

---

## 调试

在 `configuration.yaml` 开启日志：

```yaml
logger:
  default: warning
  logs:
    custom_components.wecom: debug
```

常见日志：

- `成功获取 access_token，有效期 N 秒`：token 获取成功
- `access_token 已失效 (errcode=...)，强制刷新后重试`：命中失效重试逻辑
- `发送企业微信消息失败: ... (errcode: ...)`：企业微信返回错误，检查接收方 ID / 应用权限
- `应用别名 'X' 已被其他配置使用`：别名冲突

---

## 已知问题与自动化

### GitHub Actions 自动化

- **校验**（`.github/workflows/validate.yml`）：push / PR / 每日定时运行 HACS + hassfest 校验。
- **发布**（`.github/workflows/release.yml`）：推送形如 `v1.2.0` 的 tag 时，自动校验 tag 与 `manifest.json` 版本一致，然后创建 GitHub Release。

发布新版本流程：

1. 修改 `manifest.json` 的 `version`；
2. 提交并推送到 `main`；
3. 打同名 tag 并推送：`git tag vX.Y.Z && git push origin vX.Y.Z`；
4. Actions 自动创建 Release。

---

## 更新记录

1. **默认实例选择 bug**：未指定实例时直接取 `hass.data[DOMAIN]` 第一个键，可能取到 `aliases` 保留键导致调用失败；现改为过滤出真正的配置条目。
2. **选项更新不生效**：修改凭据/别名后未重载，运行中的 API 实例仍用旧值；现保存后自动 `async_reload`。
3. **token 失效不重试**：服务端 token 提前失效时消息一直发送失败；现检测失效错误码后强制刷新并重试一次。
4. **token 过期计算不准**：使用本地时间且用满有效期，改为 UTC 时间并提前 300 秒刷新。
5. **默认接收人失效**：配置项 `default_touser` 定义了但从未使用；现作为接收方回退值生效。
6. **`message` 必填冲突**：news 类型不需要正文却强制要求；现改为 text/markdown 必填、news 可空。
7. **并发刷新 token**：多实例并发可能重复获取 token；现加锁处理。
8. **错误处理不规范**：配置流程改用 HA 标准错误码并补充 `strings.json` / 中文翻译。
9. **参数范围校验**：`safe` 等 0/1 参数及间隔增加范围校验。
10. **别名冲突**：重复别名会给出警告日志，避免静默覆盖。
11. **卸载清理**：卸载实例时正确清理别名映射与全局服务。

---

## License

MIT
