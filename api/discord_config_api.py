"""Key generation; configuration uses Agent Zero's settings framework."""
from helpers.api import ApiHandler, Request, Response


class DiscordConfigApi(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    @classmethod
    def requires_csrf(cls) -> bool:
        return True

    async def process(self, input: dict, request: Request) -> dict | Response:
        if input.get("action") != "generate_auth_key":
            return {"error": "Unknown action"}
        from usr.plugins.discord.helpers.discord_client import persist_auth_key
        from usr.plugins.discord.helpers.sanitize import generate_auth_key
        try:
            key = generate_auth_key()
            if not input.get("draft", False):
                persist_auth_key(key, input.get("bot_id", "default"))
            return {"auth_key": key}
        except Exception:
            return {"error": "Failed to generate auth key."}
