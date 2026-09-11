"""Run with the A0 framework Python: -m usr.plugins.discord.tests.test_mentions."""

import asyncio
import importlib
import json
import tempfile
from contextlib import nullcontext
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent import Agent, AgentContext
from helpers import persist_chat
from usr.plugins.discord.helpers import discord_bot as bridge


async def main():
    bot = bridge.ChatBridgeBot("test-token")
    bot._connection.user = SimpleNamespace(id=123)
    config = {
        "bot": {"token": "test-token"},
        "servers": [789],
        "chat_bridge": {
            "auto_start": True, "allowed_users": [456],
            "default_preset": "Default", "default_agent_profile": "agent0",
        },
    }
    channel = SimpleNamespace(id=101, name="mention-check", typing=nullcontext, send=AsyncMock())
    message = SimpleNamespace(
        content="<@123> hello", channel=channel, guild=SimpleNamespace(id=789),
        author=SimpleNamespace(id=456, bot=False, display_name="Tester", name="Tester"),
        attachments=[], delete=AsyncMock(),
    )
    existing = {c.id for c in AgentContext.all()}
    try:
        with tempfile.TemporaryDirectory() as tmp, \
            patch.object(bridge, "_get_state_path", return_value=Path(tmp) / "state.json"), \
            patch.object(bot, "_get_config", return_value=config), \
            patch.object(persist_chat, "CHATS_FOLDER", tmp), \
            patch.object(Agent, "call_chat_model", new_callable=AsyncMock, return_value=("Mention received.", "")) as model, \
            patch.object(Agent, "call_utility_model", side_effect=AssertionError("Bridge used the utility model")), \
            patch.object(AgentContext, "communicate", side_effect=AssertionError("Restricted mode ran tools")):
            await bot.on_message(message)
            ctxid = bridge.get_context_id("101")
            assert ctxid, "A mention in an unregistered channel must create a chat"
            ctx = AgentContext.get(ctxid)
            assert ctx.name == "Discord #mention-check"
            assert ctx.config.profile == "agent0"
            assert ctx.get_data("chat_model_override") == {"preset_name": "Default"}
            saved = json.loads((Path(tmp) / ctxid / "chat.json").read_text())
            logs = saved["log"]["logs"]
            assert any(x["type"] == "user" and "hello" in x["content"] for x in logs)
            assert any(x["type"] == "response" and x["content"] == "Mention received." for x in logs)
            assert "Mention received." in json.dumps(saved["agents"][0]["history"])
            assert not bridge.get_chat_channels(), "Mentions must not enable every-message replies"

            for text, expected in (("<@!123> again", "again"), ("hello <@123>", "hello"), ("<@123>", "Hello!")):
                message.content = text
                await bot.on_message(message)
                assert bridge.get_context_id("101") == ctxid
                assert model.call_args.kwargs["messages"][-1].content.endswith("Tester: " + expected)

            calls = model.await_count
            for text, user, guild, is_bot in (
                ("ordinary message", 456, 789, False),
                ("<@999> other bot", 456, 789, False),
                ("<@123> denied user", 999, 789, False),
                ("<@123> denied guild", 456, 999, False),
                ("<@123> ignored bot", 456, 789, True),
            ):
                message.content, message.author.id = text, user
                message.guild.id, message.author.bot = guild, is_bot
                await bot.on_message(message)
                assert model.await_count == calls

            message.author.bot = False
            message.content = "<@123> !bridge-status"
            await bot.on_message(message)
            assert model.await_count == calls, "Mentioned commands must not reach the model"
            assert "Restricted" in channel.send.call_args.args[0]

            bridge.add_chat_channel("101")
            message.content = "registered channel"
            await bot.on_message(message)
            assert model.await_count == calls + 1

            AgentContext.remove(ctxid)
            message.content = "<@123> fresh chat"
            await bot.on_message(message)
            assert bridge.get_context_id("101") != ctxid

            startup = importlib.import_module(
                "usr.plugins.discord.extensions.python.job_loop._10_discord_chat"
            )
            with patch("usr.plugins.discord.helpers.discord_client.get_discord_config", return_value=config), \
                patch.object(bridge, "start_chat_bridge", new_callable=AsyncMock) as start:
                bridge.remove_chat_channel("101")
                await startup.DiscordChatBridge(agent=None).execute()
                start.assert_awaited_once_with("test-token")
                config["chat_bridge"]["auto_start"] = False
                await startup.DiscordChatBridge(agent=None).execute()
                assert start.await_count == 1

        class SettingsParser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                value = dict(attrs).get("x-init", "")
                if "config.bot" in value:
                    assert "config.chat_bridge.default_agent_profile = '';" in value

        SettingsParser().feed((Path(bridge.__file__).parents[1] / "webui/config.html").read_text())
        print("PASS: mentions, saved chats, defaults, access restrictions, commands, startup, settings markup")
    finally:
        for context in AgentContext.all():
            if context.id not in existing:
                AgentContext.remove(context.id)
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
