"""Start the configured Discord bridge without requiring a WebUI chat."""

import logging

from helpers.extension import Extension


class DiscordChatBridge(Extension):
    async def execute(self, **kwargs):
        from usr.plugins.discord.helpers.discord_client import get_discord_config

        config = get_discord_config()
        token = (config.get("bot", {}).get("token", "") or "").strip()
        if not token or not config.get("chat_bridge", {}).get("auto_start", False):
            return

        from usr.plugins.discord.helpers.discord_bot import start_chat_bridge

        try:
            await start_chat_bridge(token)
        except Exception:
            logging.getLogger("discord_chat_bridge").exception(
                "Discord chat bridge auto-start failed"
            )
