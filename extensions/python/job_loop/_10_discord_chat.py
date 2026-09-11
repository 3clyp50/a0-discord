"""Synchronize configured Discord bridges without requiring a WebUI chat."""
import logging
from helpers.extension import Extension


class DiscordChatBridge(Extension):
    async def execute(self, **kwargs):
        from usr.plugins.discord.helpers.discord_client import get_discord_config, get_bot_configs
        from usr.plugins.discord.helpers.discord_bot import sync_chat_bridges
        try:
            await sync_chat_bridges(get_bot_configs(get_discord_config()))
        except Exception:
            logging.getLogger("discord_chat_bridge").exception("Discord bridge synchronization failed")
