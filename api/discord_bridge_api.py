"""Authenticated, per-bot bridge controls and secret-free configuration status."""
import logging
from helpers.api import ApiHandler, Request, Response


class DiscordBridgeApi(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    @classmethod
    def requires_csrf(cls) -> bool:
        return True

    async def process(self, input: dict, request: Request) -> dict | Response:
        from usr.plugins.discord.helpers.discord_client import get_discord_config
        from usr.plugins.discord.helpers.discord_bot import (
            get_bot_status, start_chat_bridge, stop_chat_bridge, list_access_requests, set_access_approval,
        )

        try:
            action = input.get("action", "status")
            config = get_discord_config(bot_id=input.get("bot_id"))
            bot_id = config["bot_id"]
            if action == "status":
                bots = []
                for bot in config["bots"]:
                    bridge = bot.get("chat_bridge", {})
                    bots.append({
                        **get_bot_status(bot["id"]),
                        "id": bot["id"], "name": bot.get("name") or bot["id"],
                        "enabled": bot.get("enabled", True), "configured": bool(bot.get("token")),
                        "auto_start": bridge.get("auto_start", False),
                        "preset": bridge.get("default_preset", ""),
                        "profile": bridge.get("default_agent_profile", ""),
                        "access": list_access_requests(bot["id"], {"bot": bot, "servers": bot.get("servers", []), "chat_bridge": bridge}),
                    })
                return {"ok": True, **get_bot_status(bot_id), "bots": bots}
            if action in ("approve", "revoke"):
                if not input.get("bot_id"):
                    raise ValueError("Choose a saved bot for access approvals.")
                access = set_access_approval(bot_id, input.get("request_id"), action, config, input.get("duration", 3600))
                return {"ok": True, "access": access}
            if action not in ("start", "stop", "restart"):
                return {"ok": False, "error": "Unknown bridge action."}
            if action != "stop":
                if not config["bot"].get("enabled", True):
                    raise ValueError("Enable this bot in Config before starting it.")
                if not config["bot"].get("token"):
                    raise ValueError("Save a bot token in Config first.")
            if action in ("stop", "restart"):
                await stop_chat_bridge(bot_id)
            if action in ("start", "restart"):
                await start_chat_bridge(config["bot"]["token"], bot_id)
            return {"ok": True, **get_bot_status(bot_id)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            logging.getLogger("discord_chat_bridge").exception("Discord bridge control failed")
            return {"ok": False, "error": "Bridge control failed. Check the Agent Zero log."}
