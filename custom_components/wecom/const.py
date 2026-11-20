"""企业微信通知集成常量定义。"""

DOMAIN = "wecom"

# 配置项键名
CONF_CORP_ID = "corp_id"
CONF_CORP_SECRET = "corp_secret"
CONF_AGENT_ID = "agent_id"
CONF_DEFAULT_TOUSER = "default_touser"
CONF_APP_NAME = "app_name"  # 应用别名

# 服务调用参数
CONF_CONFIG_ENTRY_ID = "config_entry_id"
CONF_APP_NAME_PARAM = "app_name"  # 服务调用时的别名参数

# 服务名称
SERVICE_SEND_MESSAGE = "send_message"

# 消息类型
MSG_TYPE_TEXT = "text"
MSG_TYPE_MARKDOWN = "markdown"
MSG_TYPE_NEWS = "news"

# API 端点
API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
API_GET_TOKEN = f"{API_BASE}/gettoken"
API_SEND_MESSAGE = f"{API_BASE}/message/send"

# Token 缓存时间（秒）
TOKEN_EXPIRE_TIME = 7200

# 提前刷新缓冲（秒）：避免在过期临界点使用即将失效的 token
TOKEN_REFRESH_MARGIN = 300

# token 失效类错误码：命中后强制刷新 token 并重试一次
INVALID_TOKEN_ERRCODES = frozenset({40014, 42001, 42007, 42009})

# 凭据类错误码（配置校验时归类为 invalid_auth）
INVALID_CREDENTIAL_ERRCODES = frozenset({40001, 40013, 41004})

# hass.data[DOMAIN] 中存放别名映射的保留键
DATA_ALIASES = "aliases"
