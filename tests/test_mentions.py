"""Run with the A0 framework Python: -m usr.plugins.discord.tests.test_mentions."""

import asyncio
import importlib
import json
import tempfile
from contextlib import nullcontext
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from agent import Agent, AgentContext
from helpers import persist_chat
from usr.plugins.discord.helpers import discord_bot as bridge
from usr.plugins.discord.helpers.bridge_reader import BridgeReader
from usr.plugins.discord.helpers.discord_client import resolve_agent_profile


async def main():
    assert resolve_agent_profile("Developer") == "developer"
    assert resolve_agent_profile("developer") == "developer"
    try:
        resolve_agent_profile("missing-profile-for-discord-test")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid profile must not silently fall back")
    bot = bridge.ChatBridgeBot("test-token")
    bot._connection.user = SimpleNamespace(id=123)
    config = {
        "bot": {"token": "test-token"},
        "servers": [789],
        "chat_bridge": {
            "auto_start": True, "allowed_users": [456],
            "default_preset": "Default", "default_agent_profile": "developer",
        },
    }
    channel = SimpleNamespace(id=101, name="mention-check", typing=nullcontext, send=AsyncMock())
    message = SimpleNamespace(
        content="<@123> hello", channel=channel, guild=SimpleNamespace(id=789),
        author=SimpleNamespace(id=456, bot=False, display_name="Tester", name="Tester"),
        attachments=[], delete=AsyncMock(), reference=None,
    )
    existing = {c.id for c in AgentContext.all()}
    try:
        with tempfile.TemporaryDirectory() as tmp, \
            patch.object(bridge, "_get_state_path", return_value=Path(tmp) / "state.json"), \
            patch.object(bot, "_get_config", return_value=config), \
            patch.object(persist_chat, "CHATS_FOLDER", tmp), \
            patch.object(BridgeReader, "read", new_callable=AsyncMock, return_value={"messages": []}) as reader, \
            patch.object(BridgeReader, "message_record", return_value={"content": "Earlier bot reply"}), \
            patch.object(Agent, "call_chat_model", new_callable=AsyncMock, return_value=("Mention received.", "")) as model, \
            patch.object(Agent, "call_utility_model", side_effect=AssertionError("Bridge used the utility model")), \
            patch.object(AgentContext, "communicate", side_effect=AssertionError("Restricted mode ran tools")):
            await bot.on_message(message)
            ctxid = bridge.get_context_id("101")
            assert ctxid, "A mention in an unregistered channel must create a chat"
            ctx = AgentContext.get(ctxid)
            assert ctx.name == "Discord #mention-check"
            assert ctx.config.profile == "developer"
            assert ctx.get_data("chat_model_override") == {"preset_name": "Default"}
            system = model.call_args.kwargs["messages"][0].content
            assert "## Developer" in system and '"model":' in system and '"preset": "Default"' in system
            assert "recent_channel_messages" in model.call_args.kwargs["messages"][-2].content
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
            assert "Read-only" in channel.send.call_args.args[0]

            replied = Mock(spec=discord.Message)
            replied.author = SimpleNamespace(id=123)
            message.reference = SimpleNamespace(channel_id=101, message_id=1001, resolved=replied, cached_message=None)
            message.content = "reply without mentioning the bot"
            await bot.on_message(message)
            calls += 1
            assert model.await_count == calls
            message.reference.resolved = None
            channel.fetch_message = AsyncMock(return_value=replied)
            await bot.on_message(message)
            calls += 1
            assert model.await_count == calls
            channel.fetch_message.assert_awaited_once_with(1001)
            replied.author.id = 999
            await bot.on_message(message)
            assert model.await_count == calls, "Replies to someone else should not summon the bot"
            message.reference = None
            bot._rate_limits.clear()

            reader.return_value = {"messages": [{"content": "latest bug evidence", "id": "900"}]}
            model.side_effect = [
                (json.dumps({"tool_name": "discord_read", "tool_args": {"action": "messages", "channel_id": "202"}}), ""),
                ("The latest bug is confirmed by message 900.", ""),
            ]
            message.content = "<@123> read the other channel"
            await bot.on_message(message)
            assert reader.call_args.args[0]["channel_id"] == "202"
            assert "latest bug evidence" in model.call_args.kwargs["messages"][-1].content
            assert ctx.get_data("discord_bridge_history")[-1]["content"].startswith("The latest bug")
            reads = reader.await_count
            model.side_effect = [
                (json.dumps({"tool_name": "code_execution_tool", "tool_args": {"code": "must not run"}}), ""),
                ("Only Discord reads are available.", ""),
            ]
            await bot.on_message(message)
            assert reader.await_count == reads + 1, "Only background history should be read; arbitrary tools must never execute"
            assert "Only discord_read is available" in model.call_args.kwargs["messages"][-1].content
            read_call = json.dumps({"tool_name": "discord_read", "tool_args": {"action": "channels"}})
            model.side_effect = [(read_call + read_call, ""), (read_call, ""), ("Other channels are readable.", "")]
            reads = reader.await_count
            await bot.on_message(message)
            assert reader.await_count == reads + 2, "Malformed duplicate calls must be repaired, never executed or sent as the answer"
            assert channel.send.call_args.args[0] == "Other channels are readable."
            model.side_effect = None
            calls = model.await_count
            bot._rate_limits.clear()

            bridge.add_chat_channel("101")
            message.content = "registered channel"
            await bot.on_message(message)
            assert model.await_count == calls + 1

            serialized = persist_chat._serialize_context(AgentContext.get(ctxid))
            AgentContext.remove(ctxid)
            restored = persist_chat._deserialize_context(serialized)
            assert not hasattr(restored.agent0, "loop_data"), "Reproduce the restored-chat lifecycle"
            message.content = "<@123> after restarting"
            await bot.on_message(message)
            assert channel.send.call_args.args[0] == "Mention received."
            assert restored.agent0.loop_data.last_response == "Mention received."
            assert bridge.get_context_id("101") == ctxid

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
