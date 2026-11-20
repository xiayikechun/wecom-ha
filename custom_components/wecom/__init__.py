"""企业微信通知集成，支持多实例、别名、图文消息等。"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_GET_TOKEN,
    API_SEND_MESSAGE,
    CONF_APP_NAME,
    CONF_APP_NAME_PARAM,
    CONF_CONFIG_ENTRY_ID,
    CONF_AGENT_ID,
    CONF_CORP_ID,
    CONF_CORP_SECRET,
    CONF_DEFAULT_TOUSER,
    DATA_ALIASES,
    DOMAIN,
    INVALID_TOKEN_ERRCODES,
    MSG_TYPE_MARKDOWN,
    MSG_TYPE_NEWS,
    MSG_TYPE_TEXT,
    SERVICE_SEND_MESSAGE,
    TOKEN_EXPIRE_TIME,
    TOKEN_REFRESH_MARGIN,
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
        vol.Optional("message", default=""): cv.string,
        vol.Optional("message_type", default=MSG_TYPE_TEXT): vol.In(
            [MSG_TYPE_TEXT, MSG_TYPE_MARKDOWN, MSG_TYPE_NEWS]
        ),
        vol.Optional("touser"): cv.string,
        vol.Optional("toparty"): cv.string,
        vol.Optional("totag"): cv.string,
        vol.Optional("safe", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=1)),
        vol.Optional("enable_duplicate_check", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=1)
        ),
        vol.Optional("duplicate_check_interval", default=1800): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=86400)
        ),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_APP_NAME_PARAM): cv.string,
        vol.Optional("articles"): vol.All(cv.ensure_list, [ARTICLE_SCHEMA]),
    },
    extra=vol.ALLOW_EXTRA,
)


class WeComAPI:
    """企业微信 API 封装，处理 access_token 获取、缓存与刷新。"""

    def __init__(self, corp_id, corp_secret, agent_id):
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = agent_id
        self._access_token = None
        self._token_expires_at = None
        # 防止多实例并发重复获取 token
        self._token_lock = asyncio.Lock()

    def _now(self) -> datetime:
        """返回 UTC 时间，避免本地时区/夏令时导致的缓存计算偏差。"""
        return datetime.now(timezone.utc)

    async def get_access_token(
        self, session: aiohttp.ClientSession, force_refresh: bool = False
    ) -> str:
        """获取有效的 access_token；缓存有效时直接返回。

        force_refresh=True 用于 token 被服务端判定失效时强制重新获取。
        """
        now = self._now()
        if (
            not force_refresh
            and self._access_token
            and self._token_expires_at
            and now < self._token_expires_at
        ):
            return self._access_token

        # 加锁，避免并发调用同时刷新 token
        async with self._token_lock:
            now = self._now()
            if (
                not force_refresh
                and self._access_token
                and self._token_expires_at
                and now < self._token_expires_at
            ):
                return self._access_token

            params = {
                "corpid": self.corp_id,
                "corpsecret": self.corp_secret,
            }
            try:
                async with session.get(API_GET_TOKEN, params=params) as resp:
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.error("请求企业微信 API 出错: %s", err)
                raise

            if data.get("errcode") != 0:
                _LOGGER.error(
                    "获取企业微信 access_token 失败: %s (errcode: %s)",
                    data.get("errmsg"),
                    data.get("errcode"),
                )
                raise Exception(f"获取token失败: {data.get('errmsg')}")

            self._access_token = data["access_token"]
            expires_in = int(data.get("expires_in", TOKEN_EXPIRE_TIME))
            # 提前 TOKEN_REFRESH_MARGIN 秒过期，留出刷新缓冲
            self._token_expires_at = now + timedelta(
                seconds=max(expires_in - TOKEN_REFRESH_MARGIN, 0)
            )
            _LOGGER.debug("成功获取 access_token，有效期 %d 秒", expires_in)
            return self._access_token

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
        default_touser: str = None,
    ) -> dict:
        """发送消息到企业微信。"""
        # 未指定任何接收方时，回退到配置的默认接收人
        if not any([touser, toparty, totag]) and default_touser:
            touser = default_touser

        if not any([touser, toparty, totag]):
            raise ValueError("必须指定 touser、toparty 或 totag 中的至少一个")

        # news 类型正文可为空，text/markdown 必须有内容
        if message_type in (MSG_TYPE_TEXT, MSG_TYPE_MARKDOWN) and not message:
            raise ValueError("text/markdown 类型消息的消息内容不能为空")

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
            article_list = [
                {
                    "title": article["title"],
                    "description": article.get("description", ""),
                    "url": article["url"],
                    "picurl": article.get("picurl", ""),
                }
                for article in articles
            ]
            msg_body["msgtype"] = "news"
            msg_body["news"] = {"articles": article_list}
        else:
            raise ValueError(f"不支持的消息类型: {message_type}")

        result = await self._post(session, token, msg_body)
        # token 在服务端失效（而本地缓存未过期）时，强制刷新并重试一次
        if result.get("errcode") in INVALID_TOKEN_ERRCODES:
            _LOGGER.warning(
                "access_token 已失效 (errcode=%s)，强制刷新后重试", result.get("errcode")
            )
            token = await self.get_access_token(session, force_refresh=True)
            result = await self._post(session, token, msg_body)

        if result.get("errcode") != 0:
            _LOGGER.error(
                "发送企业微信消息失败: %s (errcode: %s)",
                result.get("errmsg"),
                result.get("errcode"),
            )
            raise Exception(f"发送失败: {result.get('errmsg')}")

        _LOGGER.debug("消息发送成功，返回: %s", result)
        return result

    @staticmethod
    async def _post(
        session: aiohttp.ClientSession, token: str, msg_body: dict
    ) -> dict:
        """向发送消息接口提交请求并返回 JSON 结果。"""
        url = f"{API_SEND_MESSAGE}?access_token={token}"
        try:
            async with session.post(url, json=msg_body) as resp:
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("发送消息时请求异常: %s", err)
            raise


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """根据配置条目设置集成，支持多实例与别名映射。"""
    hass.data.setdefault(DOMAIN, {})

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
    if config.get(CONF_APP_NAME):
        alias = config[CONF_APP_NAME]
        aliases = hass.data[DOMAIN].setdefault(DATA_ALIASES, {})
        existing = aliases.get(alias)
        if existing and existing != entry.entry_id:
            _LOGGER.warning(
                "应用别名 '%s' 已被其他配置使用，现已指向最新的配置条目", alias
            )
        aliases[alias] = entry.entry_id

    # 如果服务尚未注册，则注册全局服务
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):

        async def handle_send_message(call: ServiceCall) -> None:
            """处理发送消息的服务调用，支持多实例与别名。"""
            data = call.data
            entry_id = data.get(CONF_CONFIG_ENTRY_ID)
            app_name = data.get(CONF_APP_NAME_PARAM)

            # 仅统计真正的配置条目，排除 aliases 保留键
            entries = {
                key: value
                for key, value in hass.data[DOMAIN].items()
                if key != DATA_ALIASES and isinstance(value, dict) and "api" in value
            }
            if not entries:
                raise ValueError("尚未配置任何企业微信应用")

            # 确定使用的配置条目
            if app_name:
                aliases = hass.data[DOMAIN].get(DATA_ALIASES, {})
                if app_name not in aliases:
                    raise ValueError(
                        f"未找到别名为 '{app_name}' 的应用，请检查配置或使用 config_entry_id"
                    )
                entry_id = aliases[app_name]
                _LOGGER.debug("通过别名 '%s' 找到配置条目: %s", app_name, entry_id)
            elif entry_id:
                if entry_id not in entries:
                    raise ValueError(f"未找到配置条目ID: {entry_id}")
            else:
                # 未指定任何标识，使用第一个配置条目
                entry_id = next(iter(entries))
                _LOGGER.debug(
                    "未指定 config_entry_id 或 app_name，使用默认: %s", entry_id
                )

            target_entry = entries[entry_id]
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
                    duplicate_check_interval=data.get(
                        "duplicate_check_interval", 1800
                    ),
                    articles=data.get("articles"),
                    default_touser=target_entry["config"].get(CONF_DEFAULT_TOUSER),
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
    """卸载集成时清理。"""
    domain_data = hass.data.get(DOMAIN, {})

    if entry.entry_id in domain_data:
        config = domain_data[entry.entry_id].get("config", {})
        if config.get(CONF_APP_NAME):
            alias = config[CONF_APP_NAME]
            aliases = domain_data.get(DATA_ALIASES, {})
            if aliases.get(alias) == entry.entry_id:
                del aliases[alias]
        domain_data.pop(entry.entry_id)

    # 没有任何配置条目时移除全局服务（aliases 是保留键，不算条目）
    remaining = [
        key
        for key, value in domain_data.items()
        if key != DATA_ALIASES and isinstance(value, dict) and "api" in value
    ]
    if not remaining:
        if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
            hass.services.async_remove(DOMAIN, SERVICE_SEND_MESSAGE)
        hass.data.pop(DOMAIN, None)

    return True
