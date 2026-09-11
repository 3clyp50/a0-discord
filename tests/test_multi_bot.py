"""Run from /a0: /opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_multi_bot."""
import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from usr.plugins.discord.helpers import discord_bot as bridge
from usr.plugins.discord.helpers.discord_client import get_bot_configs, get_discord_config
from usr.plugins.discord.hooks import save_plugin_config


async def main():
    legacy = {"bot": {"token": "first"}, "chat_bridge": {"default_preset": "Original"}}
    migrated = save_plugin_config(legacy)
    first = migrated["bots"][0]
    assert first["id"] == "default" and first["chat_bridge"]["default_preset"] == "Original"
    second = {"id": "support", "name": "Support", "token": "second", "enabled": True,
              "servers": [123], "chat_bridge": {"auto_start": True, "default_preset": "Support"}}
    migrated["bots"].append(second)
    with patch("helpers.plugins.get_plugin_config", return_value=migrated), patch.dict("os.environ", {}, clear=True):
        selected = get_discord_config(bot_id="support")
        assert selected["bot"]["token"] == "second"
        assert selected["chat_bridge"]["default_preset"] == "Support"
        agent = SimpleNamespace(context=SimpleNamespace(get_data=lambda _: "support"))
        assert get_discord_config(agent)["bot_id"] == "support"
        assert get_discord_config()["bot"]["token"] == "first"
        try:
            get_discord_config(bot_id="missing")
        except ValueError:
            pass
        else:
            raise AssertionError("Unknown bot must not fall back to another token")
    assert get_bot_configs({"bots": [], "bot": {"token": "old"}}) == []
    with tempfile.TemporaryDirectory() as tmp, patch.object(bridge, "_get_state_path", return_value=Path(tmp) / "state.json"):
        bridge.set_context_id("123", "existing")
        bridge.set_context_id("123", "separate", "support")
        bridge.add_chat_channel("123", bot_id="support")
        assert bridge.get_context_id("123") == "existing"
        assert bridge.get_context_id("123", "support") == "separate"
        assert bridge.get_chat_channels() == {}
        assert "123" in bridge.get_chat_channels("support")
        bridge.remove_chat_channel("123", "support")
        assert bridge.get_context_id("123") == "existing"
    with patch.object(bridge, "_bots", {}), patch.object(bridge, "_paused_bots", set()), \
         patch.object(bridge, "start_chat_bridge", new_callable=AsyncMock) as start:
        await bridge.sync_chat_bridges(migrated["bots"])
        start.assert_awaited_once_with("second", "support")
        bridge._paused_bots.add("support")
        await bridge.sync_chat_bridges(migrated["bots"])
        assert start.await_count == 1, "Manual stop must survive the next job tick"
    with patch.object(bridge, "_bots", {"support": SimpleNamespace(bot_token="second")}), \
         patch.object(bridge, "stop_chat_bridge", new_callable=AsyncMock) as stop, \
         patch.object(bridge, "start_chat_bridge", new_callable=AsyncMock):
        await bridge.sync_chat_bridges([first, dict(second, enabled=False)])
        stop.assert_awaited_once_with("support", pause=False)
    duplicate = {"bots": [first, dict(second, token="first")]}
    try:
        save_plugin_config(duplicate)
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate bot tokens must be rejected")
    print("Multi-bot configuration, routing, state and lifecycle checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
