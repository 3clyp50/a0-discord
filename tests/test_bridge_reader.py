"""Run in the framework runtime: -m usr.plugins.discord.tests.test_bridge_reader."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from usr.plugins.discord.helpers.bridge_reader import BridgeReader


async def main():
    member = SimpleNamespace(id=456, display_name="Reporter")
    guild = SimpleNamespace(id=789, me=SimpleNamespace(id=123), channels=[], active_threads=AsyncMock(return_value=[]),
                            get_member=Mock(return_value=member), fetch_member=AsyncMock(return_value=member))
    permissions = SimpleNamespace(view_channel=True, read_message_history=True, manage_threads=False)

    def record(number, content):
        return SimpleNamespace(id=number, content=content, author=member, created_at=datetime.now(timezone.utc),
                               jump_url=f"https://discord.com/channels/789/101/{number}", embeds=[], attachments=[], reference=None)

    items = [record(110, "latest bug report"), record(109, "<@123>!auth never-expose-this-key"), record(108, "previous report")]

    class Channel:
        def __init__(self, number, visible=True):
            self.id, self.name, self.guild, self.type = number, "reports", guild, discord.ChannelType.text
            self.visible = visible
            self.fetch_message = AsyncMock(return_value=items[0])
            self.history_calls = []

        def permissions_for(self, who):
            assert who is member or who is guild.me, "Permissions require a server member, not a bare Discord user"
            return permissions if self.visible else SimpleNamespace(view_channel=False, read_message_history=False)

        async def history(self, **kwargs):
            self.history_calls.append(kwargs)
            before = kwargs.get("before")
            after = kwargs.get("after")
            selected = [m for m in items if (not before or m.id < before.id) and (not after or m.id > after.id)]
            for item in selected[:kwargs["limit"]]:
                yield item

    current, other, hidden, foreign = Channel(101), Channel(202), Channel(303, False), Channel(404)
    foreign.guild = SimpleNamespace(id=999)
    guild.channels = [current, other, hidden]
    config = {"servers": [789], "chat_bridge": {"allowed_users": [456]}}
    bot = SimpleNamespace(user=SimpleNamespace(id=123), _get_config=lambda: config,
                          get_channel=lambda n: {101: current, 202: other, 303: hidden, 404: foreign}.get(n))
    message = SimpleNamespace(guild=guild, channel=current, author=member)
    reader = BridgeReader(bot, message)
    result = await reader.read({"action": "messages"})
    assert [m["id"] for m in result["messages"]] == ["110", "108"]
    assert "never-expose" not in str(result)
    assert result["next_before"] == "108"
    assert result["messages"][0]["url"].endswith("/110")
    result = await reader.read({"action": "channels"})
    assert [c["id"] for c in result["channels"]] == ["101", "202"]
    assert "error" not in await reader.read({"channel_id": "202"})
    assert "error" in await reader.read({"channel_id": "303"})
    assert "error" in await reader.read({"channel_id": "404"})
    assert not hidden.history_calls and not foreign.history_calls
    assert "error" in await reader.read({"guild_id": "999"})
    assert "error" in await reader.read({"action": "send", "content": "must not send"})
    assert "error" in await reader.read({"limit": "invalid"})
    result = await reader.read({"before": "110", "after": "107", "limit": 1000})
    assert [m["id"] for m in result["messages"]] == ["108"]
    assert current.history_calls[-1]["limit"] == 100
    result = await reader.read({"message_id": "110"})
    current.fetch_message.assert_awaited_once_with(110)
    assert result["messages"][0]["content"] == "latest bug report"

    reader.MAX_OUTPUT_CHARS = 4500
    items[:] = [record(200 - i, "x" * 3000) for i in range(3)]
    first = await reader.read({})
    second = await reader.read({"before": first["next_before"]})
    assert [m["id"] for m in first["messages"]] == ["200"]
    assert [m["id"] for m in second["messages"]] == ["199"]

    private = Mock(spec=discord.Thread)
    private.guild, private.id = guild, 505
    private.is_private.return_value = True
    private.permissions_for.return_value = permissions
    private.fetch_member = AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "not a member"))
    assert not await reader._visible(private)

    archived = Channel(606)
    archived.parent_id = current.id
    archived.archive_timestamp = datetime(2026, 9, 1, tzinfo=timezone.utc)
    archive_calls = []

    async def archives(**kwargs):
        archive_calls.append(kwargs)
        yield archived

    current.archived_threads = archives
    result = await reader.read({"action": "threads", "channel_id": "101"})
    assert result["threads"][0]["id"] == "606"
    assert result["next_before"] == archived.archive_timestamp.isoformat()
    await reader.read({"action": "threads", "channel_id": "101", "before": result["next_before"]})
    assert archive_calls[-1]["before"] == archived.archive_timestamp

    # Gateway and fetched messages can carry a User when the member is uncached.
    message.author = Mock(spec=discord.User)
    message.author.id = member.id
    guild.get_member.return_value = None
    uncached_reader = BridgeReader(bot, message)
    assert "error" not in await uncached_reader.read({"action": "channels"})
    assert "error" not in await uncached_reader.read({"channel_id": "202"})
    guild.fetch_member.assert_awaited_once_with(member.id)
    guild.fetch_member.side_effect = discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "not a member")
    assert "error" in await BridgeReader(bot, message).read({"channel_id": "202"})

    config["chat_bridge"]["allowed_users"] = [999]
    assert "error" in await reader.read({})
    print("PASS: server browsing, pagination, source links, auth redaction, permissions, private threads, archives, read-only enforcement")


if __name__ == "__main__":
    asyncio.run(main())
