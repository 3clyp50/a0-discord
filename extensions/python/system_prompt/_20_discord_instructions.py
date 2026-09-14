from helpers.extension import Extension
from usr.plugins.discord.helpers.discord_client import get_discord_config


class DiscordInstructions(Extension):
    async def execute(self, system_prompt: list[str], **kwargs):
        if not self.agent or self.agent.number != 0:
            return
        bot_id = self.agent.context.get_data("discord_bot_id")
        if bot_id is None:
            return
        try:
            config = get_discord_config(bot_id=bot_id)
        except ValueError:
            # A saved chat can outlive the bot that created it.
            return
        instructions = config.get("chat_bridge", {}).get("instructions", "").strip()
        if instructions:
            system_prompt.append("## Discord bot instructions\n" + instructions)
