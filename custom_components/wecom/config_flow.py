"""企业微信插件的配置流程，支持多实例与自定义别名。"""

import logging

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_GET_TOKEN,
    CONF_AGENT_ID,
    CONF_APP_NAME,
    CONF_CORP_ID,
    CONF_CORP_SECRET,
    CONF_DEFAULT_TOUSER,
    DATA_ALIASES,
    DOMAIN,
    INVALID_CREDENTIAL_ERRCODES,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CORP_ID): str,
        vol.Required(CONF_CORP_SECRET): str,
        vol.Required(CONF_AGENT_ID): str,
        vol.Optional(CONF_DEFAULT_TOUSER, default=""): str,
        vol.Optional(CONF_APP_NAME, default=""): str,  # 别名，可选
    }
)


class CannotConnect(HomeAssistantError):
    """无法连接到企业微信 API。"""


class InvalidAuth(HomeAssistantError):
    """凭据无效。"""


def _build_title(data: dict) -> str:
    """根据别名或企业 ID 生成配置条目标题。"""
    return data.get(CONF_APP_NAME) or f"企业微信 ({data[CONF_CORP_ID]}) - {data[CONF_AGENT_ID]}"


async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """验证用户输入的凭据，尝试获取 access_token。"""
    session = async_get_clientsession(hass)
    params = {
        "corpid": data[CONF_CORP_ID],
        "corpsecret": data[CONF_CORP_SECRET],
    }
    try:
        async with session.get(API_GET_TOKEN, params=params) as resp:
            result = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.error("连接企业微信 API 失败: %s", err)
        raise CannotConnect from err

    errcode = result.get("errcode")
    if errcode != 0:
        errmsg = result.get("errmsg", "未知错误")
        _LOGGER.error("验证失败: errcode=%s, errmsg=%s", errcode, errmsg)
        if errcode in INVALID_CREDENTIAL_ERRCODES:
            raise InvalidAuth(errmsg)
        raise CannotConnect(errmsg)

    return {"title": _build_title(data)}


class WeComConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """企业微信配置流程。"""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """用户初始化配置的第一步。"""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                # 使用 corp_id + agent_id 作为唯一标识，允许同一企业添加多个应用
                unique_id = f"{user_input[CONF_CORP_ID]}_{user_input[CONF_AGENT_ID]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("配置验证出现未知错误")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """返回选项流处理器。"""
        return WeComOptionsFlowHandler()


class WeComOptionsFlowHandler(config_entries.OptionsFlow):
    """处理选项更新，支持修改凭据与别名。"""

    async def async_step_init(self, user_input=None) -> FlowResult:
        """管理选项页面。"""
        errors = {}
        if user_input is not None:
            # 合并新旧配置（选项表单已预填当前值）
            data = {**self.config_entry.data, **user_input}
            try:
                await validate_input(self.hass, data)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("配置验证出现未知错误")
                errors["base"] = "unknown"
            else:
                title = _build_title(data)
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=data, title=title
                )
                # 关键：重载条目，使新的凭据/别名在运行时生效
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        current_data = self.config_entry.data
        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_CORP_ID, default=current_data.get(CONF_CORP_ID, "")
                ): str,
                vol.Required(
                    CONF_CORP_SECRET, default=current_data.get(CONF_CORP_SECRET, "")
                ): str,
                vol.Required(
                    CONF_AGENT_ID, default=current_data.get(CONF_AGENT_ID, "")
                ): str,
                vol.Optional(
                    CONF_DEFAULT_TOUSER,
                    default=current_data.get(CONF_DEFAULT_TOUSER, ""),
                ): str,
                vol.Optional(
                    CONF_APP_NAME,
                    default=current_data.get(CONF_APP_NAME, ""),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors
        )
