"""Test one configured Discord bot without exposing its token."""
from helpers.api import ApiHandler, Request, Response


class DiscordTest(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    @classmethod
    def requires_csrf(cls) -> bool:
        return True

    async def process(self, input: dict, request: Request) -> dict | Response:
        from usr.plugins.discord.helpers.discord_client import DiscordClient, get_discord_config
        client = None
        try:
            config = get_discord_config(bot_id=input.get("bot_id"))
            mode = "bot" if input.get("bot_id") or config["bot"].get("token") else "user"
            client = DiscordClient.from_config(mode=mode, bot_id=input.get("bot_id"))
            user = await client.get_current_user()
            return {"ok": True, "user": user.get("username", "Unknown"), "mode": mode, "id": user.get("id")}
        except Exception as exc:
            return {"ok": False, "error": f"Connection failed: {type(exc).__name__}"}
        finally:
            if client is not None:
                await client.close()
