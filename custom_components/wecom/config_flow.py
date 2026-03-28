"""企业微信插件的配置流程，支持多实例与自定义别名"""

import logging

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_CORP_ID,
    CONF_CORP_SECRET,
    CONF_AGENT_ID,
    CONF_DEFAULT_TOUSER,
    CONF_APP_NAME,
    API_GET_TOKEN,
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


async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """验证用户输入的凭据，尝试获取access_token"""
    session = async_get_clientsession(hass)
    params = {
        "corpid": data[CONF_CORP_ID],
        "corpsecret": data[CONF_CORP_SECRET],
    }
    try:
        async with session.get(API_GET_TOKEN, params=params) as resp:
            result = await resp.json()
            if result.get("errcode") != 0:
                _LOGGER.error("验证失败: %s", result.get("errmsg"))
                raise Exception(result.get("errmsg", "未知错误"))
            # 标题显示别名（如果有）或默认显示企业ID+AgentId
            title = data.get(CONF_APP_NAME) or f"企业微信 ({data[CONF_CORP_ID]}) - {data[CONF_AGENT_ID]}"
            return {"title": title}
    except aiohttp.ClientError as err:
        _LOGGER.error("连接企业微信API失败: %s", err)
        raise Exception("网络连接失败，请检查网络") from err


class WeComConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """企业微信配置流程"""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """用户初始化配置的第一步"""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                # 使用 corp_id + agent_id 作为唯一标识符，允许同一企业添加多个应用
                unique_id = f"{user_input[CONF_CORP_ID]}_{user_input[CONF_AGENT_ID]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)
            except Exception as err:
                errors["base"] = str(err)
                _LOGGER.exception("配置验证出错")

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "corp_id": "企业ID",
                "corp_secret": "应用的Secret",
                "agent_id": "应用AgentId",
                "default_touser": "默认接收成员ID（可选）",
                "app_name": "应用别名（可选，用于快速识别）",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """返回选项流处理器"""
        return WeComOptionsFlowHandler()


class WeComOptionsFlowHandler(config_entries.OptionsFlow):
    """处理选项更新，支持修改别名等"""

    # 注意：这里没有 __init__ 方法，直接使用父类的 config_entry 属性

    async def async_step_init(self, user_input=None):
        """管理选项页面"""
        if user_input is not None:
            # 更新配置条目数据
            data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            # 如果标题需要更新（别名变了），可以同步更新标题
            title = data.get(CONF_APP_NAME) or f"企业微信 ({data[CONF_CORP_ID]}) - {data[CONF_AGENT_ID]}"
            self.hass.config_entries.async_update_entry(self.config_entry, title=title)
            return self.async_create_entry(title="", data={})

        # 显示当前配置
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
        return self.async_show_form(step_id="init", data_schema=options_schema)