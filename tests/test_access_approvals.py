"""Offline: /opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_access_approvals."""
import asyncio
import json
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from usr.plugins.discord.helpers import discord_bot as bridge
from usr.plugins.discord.api.discord_bridge_api import DiscordBridgeApi


async def main():
    bot = bridge.ChatBridgeBot("test-token")
    bot._connection.user = SimpleNamespace(id=123)
    bridge_config = {"allowed_users": ["456"]}
    entry = {"id": "default", "enabled": True, "token": "never-return-this-token",
             "servers": ["789"], "chat_bridge": bridge_config}
    config = {"bot_id": "default", "bot": entry, "bots": [entry],
              "servers": entry["servers"], "chat_bridge": bridge_config}
    channel = SimpleNamespace(id=101, name="general", typing=nullcontext, send=AsyncMock())
    message = SimpleNamespace(id=1, content="<@123> summarize this", channel=channel,
        guild=SimpleNamespace(id=789, name="Server"), reference=None, attachments=[],
        author=SimpleNamespace(id=456, name="Tester", display_name="Tester", bot=False))
    api = object.__new__(DiscordBridgeApi)
    try:
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(bridge, "_get_state_path", return_value=Path(tmp) / "state.json"), \
             patch.object(bot, "_get_config", return_value=config), \
             patch("usr.plugins.discord.helpers.discord_client.get_discord_config", return_value=config), \
             patch.object(bot, "_get_agent_response", new_callable=AsyncMock, return_value="read only") as restricted, \
             patch.object(bot, "_get_full_agent_response", new_callable=AsyncMock, return_value="full agent") as full:
            assert DiscordBridgeApi.requires_auth() and DiscordBridgeApi.requires_csrf()
            await bot.on_message(message)
            restricted.assert_awaited_once()
            full.assert_not_awaited()
            records = bridge.list_access_requests("default", config)
            assert len(records) == 1 and not records[0]["approved"]
            request_id = records[0]["request_id"]
            assert request_id == "789:456:101"
            assert not (await api.process({"action": "approve", "request_id": request_id}, None))["ok"]
            for duration in (True, -1, 86401, "3600"):
                denied = await api.process({"action": "approve", "bot_id": "default",
                                           "request_id": request_id, "duration": duration}, None)
                assert not denied["ok"]
            assert not (await api.process({"action": "approve", "bot_id": "default", "request_id": "unknown"}, None))["ok"]
            granted = await api.process({"action": "approve", "bot_id": "default",
                                         "request_id": request_id, "duration": 3600}, None)
            assert granted["ok"] and granted["access"][0]["approved"]
            assert "never-return-this-token" not in json.dumps(granted)
            assert bot._has_tool_access("456", "101", 789)
            assert not bot._has_tool_access("999", "101", 789)
            assert not bot._has_tool_access("456", "202", 789)
            assert not bot._has_tool_access("456", "101", 999)
            assert not bot._has_tool_access("456", "101", None)
            saved_id = bot.bot_id
            bot.bot_id = "other"
            assert not bot._has_tool_access("456", "101", 789)
            bot.bot_id = saved_id
            await bot.on_message(message)
            full.assert_not_awaited(), "Approval must not replay the earlier request"
            message.id += 1
            await bot.on_message(message)
            full.assert_awaited_once()
            expires = granted["access"][0]["expires_at"]
            with patch.object(bridge.time, "time", return_value=expires + 1):
                assert not bot._has_tool_access("456", "101", 789)
            fresh = bridge.ChatBridgeBot("test-token")
            with patch.object(fresh, "_get_config", return_value=config):
                assert fresh._has_tool_access("456", "101", 789), "Restart must preserve unexpired approval"
            await fresh.close()
            entry["enabled"] = False
            assert not bot._has_tool_access("456", "101", 789)
            entry["enabled"] = True
            bridge_config["allowed_users"] = ["999"]
            assert not bot._has_tool_access("456", "101", 789)
            assert not (await api.process({"action": "approve", "bot_id": "default", "request_id": request_id}, None))["ok"]
            bridge_config["allowed_users"] = ["456"]
            permanent = await api.process({"action": "approve", "bot_id": "default",
                                           "request_id": request_id, "duration": 0}, None)
            assert permanent["ok"] and permanent["access"][0]["approved"]
            assert permanent["access"][0]["expires_at"] is None
            with patch.object(bridge.time, "time", return_value=time.time() + 100 * 365 * 86400):
                assert bot._has_tool_access("456", "101", 789)
                assert bridge.list_access_requests("default", config)[0]["approved"]
            assert not bridge._approval_active({}) and not bridge._approval_active({"expires_at": 0})
            assert not bot._has_tool_access("456", "202", 789)
            bridge_config["allowed_users"] = ["999"]
            assert not bot._has_tool_access("456", "101", 789)
            bridge_config["allowed_users"] = ["456"]
            entry["enabled"] = False
            assert not bot._has_tool_access("456", "101", 789)
            entry["enabled"] = True
            permanent_restart = bridge.ChatBridgeBot("test-token")
            try:
                with patch.object(permanent_restart, "_get_config", return_value=config):
                    assert permanent_restart._has_tool_access("456", "101", 789)
                    message.content = "<@123> !bridge-status"
                    message.id += 1
                    await bot.on_message(message)
                    assert "until revoked" in channel.send.call_args.args[0]
                    # A full request list must not evict a permanent approval.
                    another = SimpleNamespace(**vars(message))
                    another.channel = SimpleNamespace(id=202, name="other")
                    with patch.object(bridge, "MAX_ACCESS_REQUESTS", 1):
                        bot._register_access_request(another)
                    assert permanent_restart._has_tool_access("456", "101", 789)
                    await api.process({"action": "revoke", "bot_id": "default", "request_id": request_id}, None)
                    assert not permanent_restart._has_tool_access("456", "101", 789)
            finally:
                await permanent_restart.close()
            revoked = await api.process({"action": "revoke", "bot_id": "default", "request_id": request_id}, None)
            assert revoked["ok"] and not bot._has_tool_access("456", "101", 789)
            full.reset_mock()
            message.content = "<@123> /goal status"
            message.id += 1
            await bot.on_message(message)
            assert "Web UI approval" in channel.send.call_args.args[0]
            full.assert_not_awaited()
            message.content = "<@123> !bridge-status"
            message.id += 1
            await bot.on_message(message)
            assert "Read-only" in channel.send.call_args.args[0] and "!auth" not in channel.send.call_args.args[0]
            assert not hasattr(bot, "_is_elevated") and not hasattr(bot, "_elevated_sessions")
            # Old key commands have no authentication handler and never expose their payload.
            message.content = "<@123> !auth must-not-enter-the-model"
            message.id += 1
            before = restricted.await_count
            await bot.on_message(message)
            assert restricted.await_count == before
            assert "must-not-enter" not in channel.send.call_args.args[0]
            assert "must-not-enter" not in (Path(tmp) / "state.json").read_text()
    finally:
        await bot.close()
    print("PASS: explicit Web UI approvals, persistence, expiry, revocation, exact scopes, allowlists and key-free dispatch")


if __name__ == "__main__":
    asyncio.run(main())
