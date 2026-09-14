"""Offline: /opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_reply_delivery."""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from helpers.defer import DeferredTask
from usr.plugins.discord.helpers import discord_bot as bridge
from usr.plugins.discord.helpers.delivery import bridge_delivery
from usr.plugins.discord.tools.discord_send import DiscordSend


async def main():
    bot = bridge.ChatBridgeBot("test-token")
    bot._connection.user = SimpleNamespace(id=123)
    channel_id = "123456789012345678"
    channel = SimpleNamespace(id=int(channel_id), typing=nullcontext, send=AsyncMock())
    message = SimpleNamespace(id=1001, content="<@123> hello", channel=channel,
                              guild=SimpleNamespace(id=789), reference=None, attachments=[],
                              author=SimpleNamespace(id=456, bot=False, display_name="Tester", name="Tester"))
    config = {"bot_id": "default", "bot": {"token": "test-token"}, "servers": []}
    task = DeferredTask(thread_name="DiscordDeliveryRegression")
    try:
        with patch.object(bot, "_get_config", return_value=config), \
             patch.object(bridge, "get_chat_channels", return_value={}), \
             patch.object(bot, "_register_access_request"), \
             patch.object(bot, "_has_tool_access", return_value=False), \
             patch.object(bot, "_get_agent_response", new_callable=AsyncMock, return_value="Hello.") as model:
            await asyncio.gather(bot.on_message(message), bot.on_message(message))
            await bot.on_message(message)
            assert model.await_count == channel.send.await_count == 1
            message.id += 1
            await bot.on_message(message)
            assert model.await_count == channel.send.await_count == 2, "New IDs with identical text remain valid"
            for quiet in ("NO_REPLY", None):
                message.id += 1
                model.return_value = quiet
                await bot.on_message(message)
                assert channel.send.await_count == 2

        context = SimpleNamespace(id="delivery-test")
        agent = SimpleNamespace(context=context, number=0)
        client = SimpleNamespace(send_message=AsyncMock(return_value={"id": "sent"}), close=AsyncMock())
        tool = DiscordSend(agent=agent, name="discord_send", method=None, message="", loop_data=None,
                           args={"channel_id": channel_id, "content": "Requested screenshot.", "final": True})
        results, receipts, cleaned = [], [], []

        async def run(_message):
            receipts.append(bridge_delivery.get())
            results.append(await tool.execute())
            cleaned.append(True)
            return "WebUI completion."

        context.communicate = lambda msg: task.start_task(run, msg)
        with patch.object(bot, "_has_tool_access", return_value=True), \
             patch("helpers.message_queue.log_user_message"), \
             patch("usr.plugins.discord.tools.discord_send.get_discord_config", return_value=config), \
             patch("usr.plugins.discord.tools.discord_send.DiscordClient.from_config", return_value=client):
            async def request():
                return await bot._get_full_agent_response(channel_id, "send screenshot", message, context=context)

            assert await request() is None, "Final tool delivery must not be followed by a bridge recap"
            assert cleaned == [True] and not results[-1].break_loop, "Delivery must allow remaining cleanup"
            assert receipts[-1]["sent_ids"] == ["sent"], "Receipt crosses the actual DeferredTask thread"
            assert bridge_delivery.get() is None, "Receipt cannot leak into another request"

            tool.args["final"] = False
            assert await request() == "WebUI completion.", "Progress must not suppress the answer"
            assert not receipts[-1]["sent_ids"]
            tool.args["final"] = True
            client.send_message.side_effect = TimeoutError()
            assert await request() == "WebUI completion.", "Unconfirmed writes must not suppress errors"
            assert not receipts[-1]["sent_ids"] and "Error" in results[-1].message
            client.send_message.side_effect = None
            with patch("usr.plugins.discord.tools.discord_send.deliver_message", new_callable=AsyncMock,
                       return_value=([{"id": "fallback"}], ["image.png"])):
                assert await request() == "WebUI completion."
                assert not receipts[-1]["sent_ids"] and "NOT delivered" in results[-1].message

            count = client.send_message.await_count
            tool.args["channel_id"] = "223456789012345678"
            assert await request() == "WebUI completion."
            tool.args["channel_id"] = channel_id
            config["bot_id"] = "another"
            assert await request() == "WebUI completion."
            config["bot_id"] = "default"
            agent.number = 1
            assert await request() == "WebUI completion."
            agent.number = 0
            channel.interaction = object()
            assert await request() == "WebUI completion."
            assert receipts[-1] is None, "Private interactions cannot create public final receipts"
            del channel.interaction
            assert "requires" in (await tool.execute()).message, "WebUI-only calls cannot claim bridge delivery"
            assert client.send_message.await_count == count, "Invalid final scopes must not post"
            tool.args["final"] = "true"
            assert "boolean" in (await tool.execute()).message
            assert client.send_message.await_count == count

            tool.args["final"] = True
            assert await request() is None
            assert bridge_delivery.get() is None
    finally:
        task.kill(terminate_thread=True)
        await bot.close()
    print("PASS: replay IDs, silent replies, final delivery, cross-thread receipts, cleanup, failures and private/cross-bot scope")


if __name__ == "__main__":
    asyncio.run(main())
