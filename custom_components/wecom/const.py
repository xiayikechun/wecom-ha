"""企业微信插件常量定义"""

DOMAIN = "wecom"

# 配置项键名
CONF_CORP_ID = "corp_id"
CONF_CORP_SECRET = "corp_secret"
CONF_AGENT_ID = "agent_id"
CONF_DEFAULT_TOUSER = "default_touser"
CONF_APP_NAME = "app_name"          # 新增：应用别名

# 服务参数
CONF_CONFIG_ENTRY_ID = "config_entry_id"
CONF_APP_NAME_PARAM = "app_name"    # 服务调用时的参数名

# 服务名称
SERVICE_SEND_MESSAGE = "send_message"

# 消息类型
MSG_TYPE_TEXT = "text"
MSG_TYPE_MARKDOWN = "markdown"

# API 端点
API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
API_GET_TOKEN = f"{API_BASE}/gettoken"
API_SEND_MESSAGE = f"{API_BASE}/message/send"

# Token 缓存时间（秒）
TOKEN_EXPIRE_TIME = 7200