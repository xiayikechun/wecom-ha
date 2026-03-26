"""企业微信通知插件，支持多实例、别名、图文消息等"""

import logging
from datetime import datetime, timedelta

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_CORP_ID,
    CONF_CORP_SECRET,
    CONF_AGENT_ID,
    CONF_DEFAULT_TOUSER,
    CONF_APP_NAME,
    CONF_CONFIG_ENTRY_ID,
    CONF_APP_NAME_PARAM,
    SERVICE_SEND_MESSAGE,
    MSG_TYPE_TEXT,
    MSG_TYPE_MARKDOWN,
    MSG_TYPE_NEWS,
    API_GET_TOKEN,
    API_SEND_MESSAGE,
    TOKEN_EXPIRE_TIME,
)

_LOGGER = logging.getLogger(__name__)

# 单篇文章验证架构
ARTICLE_SCHEMA = vol.Schema(
    {
        vol.Required("title"): cv.string,
        vol.Optional("description", default=""): cv.string,
        vol.Required("url"): cv.string,
        vol.Optional("picurl", default=""): cv.string,
    }
)

# 服务参数验证
SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("message"): cv.string,
        vol.Optional("message_type", default=MSG_TYPE_TEXT): vol.In(
            [MSG_TYPE_TEXT, MSG_TYPE_MARKDOWN, MSG_TYPE_NEWS]
        ),
        vol.Optional("touser"): cv.string,
        vol.Optional("toparty"): cv.string,
        vol.Optional("totag"): cv.string,
        vol.Optional("safe", default=0): vol.Coerce(int),
        vol.Optional("enable_duplicate_check", default=0): vol.Coerce(int),
        vol.Optional("duplicate_check_interval", default=1800): vol.Coerce(int),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_APP_NAME_PARAM): cv.string,
        vol.Optional("articles"): vol.All(cv.ensure_list, [ARTICLE_SCHEMA]),
    },
    extra=vol.ALLOW_EXTRA,
)


class WeComAPI:
    """企业微信API封装，处理access_token获取与刷新"""

    def __init__(self, corp_id, corp_secret, agent_id):
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = agent_id
        self._access_token = None
        self._token_expires_at = None

    async def get_access_token(self, session: aiohttp.ClientSession) -> str:
        """获取有效的access_token，如果缓存有效则直接返回"""
        if (
            self._access_token
            and self._token_expires_at
            and datetime.now() < self._token_expires_at
        ):
            return self._access_token

        params = {
            "corpid": self.corp_id,
            "corpsecret": self.corp_secret,
        }
        try:
            async with session.get(API_GET_TOKEN, params=params) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    _LOGGER.error("获取企业微信access_token失败: %s", data.get("errmsg"))
                    raise Exception(f"获取token失败: {data.get('errmsg')}")

                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", TOKEN_EXPIRE_TIME)
                self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                _LOGGER.debug("成功获取access_token，有效期%d秒", expires_in)
                return self._access_token
        except aiohttp.ClientError as err:
            _LOGGER.error("请求企业微信API出错: %s", err)
            raise

    async def send_message(
        self,
        session: aiohttp.ClientSession,
        message: str,
        message_type: str = MSG_TYPE_TEXT,
        touser: str = None,
        toparty: str = None,
        totag: str = None,
        safe: int = 0,
        enable_duplicate_check: int = 0,
        duplicate_check_interval: int = 1800,
        articles: list = None,
    ) -> dict:
        """发送消息到企业微信"""
        token = await self.get_access_token(session)

        msg_body = {
            "agentid": self.agent_id,
            "safe": safe,
            "enable_duplicate_check": enable_duplicate_check,
            "duplicate_check_interval": duplicate_check_interval,
        }

        if touser:
            msg_body["touser"] = touser
        if toparty:
            msg_body["toparty"] = toparty
        if totag:
            msg_body["totag"] = totag

        if not any([touser, toparty, totag]):
            raise ValueError("必须指定touser、toparty或totag中的至少一个")

        # 根据消息类型填充内容
        if message_type == MSG_TYPE_TEXT:
            msg_body["msgtype"] = "text"
            msg_body["text"] = {"content": message}
        elif message_type == MSG_TYPE_MARKDOWN:
            msg_body["msgtype"] = "markdown"
            msg_body["markdown"] = {"content": message}
        elif message_type == MSG_TYPE_NEWS:
            if not articles:
                raise ValueError("发送 news 类型消息时必须提供 articles 参数")
            article_list = []
            for article in articles:
                article_list.append(
                    {
                        "title": article["title"],
                        "description": article.get("description", ""),
                        "url": article["url"],
                        "picurl": article.get("picurl", ""),
                    }
                )
            msg_body["msgtype"] = "news"
            msg_body["news"] = {"articles": article_list}
        else:
            raise ValueError(f"不支持的消息类型: {message_type}")

        url = f"{API_SEND_MESSAGE}?access_token={token}"
        try:
            async with session.post(url, json=msg_body) as resp:
                result = await resp.json()
                if result.get("errcode") != 0:
                    _LOGGER.error(
                        "发送企业微信消息失败: %s (errcode: %s)",
                        result.get("errmsg"),
                        result.get("errcode"),
                    )
                    raise Exception(f"发送失败: {result.get('errmsg')}")
                _LOGGER.debug("消息发送成功，返回: %s", result)
                return result
        except aiohttp.ClientError as err:
            _LOGGER.error("发送消息时请求异常: %s", err)
            raise


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """根据配置条目设置集成，支持多实例与别名映射"""
    hass.data.setdefault(DOMAIN, {})

    # 保存配置和API实例
    config = dict(entry.data)
    hass.data[DOMAIN][entry.entry_id] = {
        "config": config,
        "api": WeComAPI(
            corp_id=config[CONF_CORP_ID],
            corp_secret=config[CONF_CORP_SECRET],
            agent_id=config[CONF_AGENT_ID],
        ),
    }

    # 建立别名映射（用于快速查找）
    if CONF_APP_NAME in config and config[CONF_APP_NAME]:
        alias = config[CONF_APP_NAME]
        # 存储到别名映射字典，便于服务调用时查找
        hass.data[DOMAIN].setdefault("aliases", {})[alias] = entry.entry_id

    # 如果服务尚未注册，则注册全局服务
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        async def handle_send_message(call: ServiceCall) -> None:
            """处理发送消息的服务调用，支持多实例与别名"""
            data = call.data
            entry_id = data.get(CONF_CONFIG_ENTRY_ID)
            app_name = data.get(CONF_APP_NAME_PARAM)

            # 确定使用的配置条目
            if app_name:
                aliases = hass.data[DOMAIN].get("aliases", {})
                if app_name not in aliases:
                    raise ValueError(f"未找到别名为 '{app_name}' 的应用，请检查配置或使用 config_entry_id")
                entry_id = aliases[app_name]
                _LOGGER.debug("通过别名 '%s' 找到配置条目: %s", app_name, entry_id)
            elif entry_id:
                if entry_id not in hass.data[DOMAIN]:
                    raise ValueError(f"未找到配置条目ID: {entry_id}")
            else:
                # 未指定任何标识，使用第一个配置条目
                first_entry_id = next(iter(hass.data[DOMAIN].keys()))
                entry_id = first_entry_id
                _LOGGER.debug("未指定 config_entry_id 或 app_name，使用默认: %s", entry_id)

            target_entry = hass.data[DOMAIN][entry_id]
            api = target_entry["api"]
            try:
                await api.send_message(
                    session=async_get_clientsession(hass),
                    message=data["message"],
                    message_type=data.get("message_type", MSG_TYPE_TEXT),
                    touser=data.get("touser"),
                    toparty=data.get("toparty"),
                    totag=data.get("totag"),
                    safe=data.get("safe", 0),
                    enable_duplicate_check=data.get("enable_duplicate_check", 0),
                    duplicate_check_interval=data.get("duplicate_check_interval", 1800),
                    articles=data.get("articles"),
                )
            except Exception as err:
                _LOGGER.error("服务调用失败: %s", err)
                raise

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_MESSAGE,
            handle_send_message,
            schema=SEND_MESSAGE_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载集成时清理"""
    # 移除该配置条目的数据
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        # 如果该条目有别名，从映射中删除
        config = hass.data[DOMAIN][entry.entry_id].get("config", {})
        if CONF_APP_NAME in config and config[CONF_APP_NAME]:
            alias = config[CONF_APP_NAME]
            aliases = hass.data[DOMAIN].get("aliases", {})
            if aliases.get(alias) == entry.entry_id:
                del aliases[alias]
        hass.data[DOMAIN].pop(entry.entry_id)

    # 如果没有任何配置条目了，移除全局服务
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_MESSAGE)
        hass.data.pop(DOMAIN, None)

    return True