"""Offline: /opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_delivery."""
import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from usr.plugins.discord.helpers.delivery import (
    DEFAULT_UPLOAD_LIMIT, deliver_message, fences, read_attachments, split_message,
)
from usr.plugins.discord.helpers.discord_bot import ChatBridgeBot
from usr.plugins.discord.helpers.discord_client import DiscordClient, DiscordAPIError
from usr.plugins.discord.helpers.native_commands import InteractionChannel
from usr.plugins.discord.tools.discord_send import DiscordSend


async def main():
    sent = []

    async def send(content, files, first):
        sent.append((content, files, first))
        return {"id": str(len(sent))}

    for language, extension in (
        ("js", "js"), ("JavaScript", "js"), ("markdown", "md"), ("md", "md"),
        ("text", "txt"), ("", "md"), ("unknown/../../env", "txt"), ("python", "py"),
    ):
        sent.clear()
        text = f"Requested artifact:\n```{language}\nline one\n  line two\n```\nAfterward."
        results, failed = await deliver_message(send, text)
        assert not failed and len(results) == 2
        assert sent[0] == ("Requested artifact:\n", [(f"snippet-1.{extension}", b"line one\n  line two\n")], True)
        assert sent[1] == ("Afterward.", (), False)

    sent.clear()
    body = "# Prompt\r\n```js\r\nrun();\r\n```\r\n"
    await deliver_message(send, "````markdown\r\n" + body + "````\r\n")
    assert sent == [(None, [("snippet-1.md", body.encode())], True)]
    sent.clear()
    await deliver_message(send, "~~~yaml\nkey: value\n~~~\n```json\n{}\n```")
    assert [entry[1][0][0] for entry in sent] == ["snippet-1.yaml", "snippet-2.json"]
    sent.clear()
    await deliver_message(send, "Use `x` or inline ``` markers, not a block.")
    assert len(sent) == 1 and not sent[0][1]

    long_text = "Before\n```javascript\n" + "x" * 7000 + "\n```\nAfter"
    for status, body_json in ((403, "{}"), (413, "{}"), (400, '{"code":40005}')):
        sent.clear()
        attempts = []

        async def denied(content, files, first):
            attempts.append(bool(files))
            if files:
                raise DiscordAPIError(status, body_json, "/messages")
            return await send(content, files, first)

        results, failed = await deliver_message(denied, long_text, [("image.png", b"image")])
        assert failed == ["image.png"] and attempts.count(True) == 1
        assert all(len(content) <= 2000 for content, _files, _first in sent)
        assert sum(first for _content, _files, first in sent) == 1
        assert "Attachments not delivered" in sent[-1][0]
        code = [block for content, _files, _first in sent for block in fences(content)]
        assert "".join(block[3].rstrip("\n") for block in code) == "x" * 7000

    for text in ("```text\n" + "a" * 5000, "Before\n````md\n```js\nx\n```\n````\nAfter", "`" * 2100 + "\nx\n" + "`" * 2100):
        chunks = split_message(text)
        assert chunks and all(len(chunk) <= 2000 for chunk in chunks)
        for chunk in chunks:
            assert list(fences(chunk)) == list(fences(chunk, include_unclosed=True)), "Each chunk must have closed fences"
    sent.clear()
    await deliver_message(send, "```text\n" + "x" * 20 + "\n```", upload_limit=10)
    assert sent and all(not files for _content, files, _first in sent)
    sent.clear()
    await deliver_message(send, "```text\nunfinished")
    assert sent and not sent[0][1] and list(fences(sent[0][0]))
    for error in (DiscordAPIError(500, "{}", "/messages"), TimeoutError()):
        broken = AsyncMock(side_effect=error)
        try:
            await deliver_message(broken, "```text\ncontent\n```")
        except type(error):
            pass
        else:
            raise AssertionError("Ambiguous delivery errors must not trigger duplicate text sends")
        assert broken.await_count == 1

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.md"
        path.write_bytes(b"# Report\n")
        link = Path(tmp) / "link"
        link.symlink_to(path)
        fifo = Path(tmp) / "pipe"
        os.mkfifo(fifo)
        assert read_attachments([str(path)]) == [("report.md", b"# Report\n")]
        for paths in ("not-a-list", [str(path)] * 11, ["relative.md"], ["https://example.com/image.png"], [None], [str(link)], [tmp], [str(fifo)], [str(Path(tmp) / "missing")]):
            try:
                read_attachments(paths)
            except ValueError:
                pass
            else:
                raise AssertionError(f"Invalid attachment accepted: {paths!r}")
        try:
            read_attachments([str(path)], upload_limit=3)
        except ValueError:
            pass
        else:
            raise AssertionError("Oversized attachment accepted")

        config = {"bot_id": "default", "bot": {"token": "test", "enabled": True}, "servers": ["999999999999999999"]}
        client = SimpleNamespace(
            get_channel=AsyncMock(return_value={"guild_id": "999999999999999999"}),
            send_message=AsyncMock(return_value={"id": "123"}), close=AsyncMock(),
        )
        tool = DiscordSend(agent=object(), name="discord_send", method=None, message="", loop_data=None,
                           args={"channel_id": "123456789012345678", "attachments": [str(path)]})
        with patch("usr.plugins.discord.tools.discord_send.get_discord_config", return_value=config), \
             patch("usr.plugins.discord.tools.discord_send.DiscordClient.from_config", return_value=client):
            result = await tool.execute()
            assert "Sent 1" in result.message
            assert client.send_message.call_args.kwargs["files"] == [("report.md", b"# Report\n")]
            client.get_channel.return_value = {"guild_id": "888888888888888888"}
            assert "allowed servers" in (await tool.execute()).message
            assert client.send_message.await_count == 1
            client.get_channel.return_value = {"guild_id": "999999999999999999"}
            tool.args["content"] = str(path)
            tool.args["attachments"] = []
            await tool.execute()
            assert client.send_message.call_args.kwargs["files"] is None, "Never scrape a path from prose"

    bot = ChatBridgeBot("test-token")
    gateway_calls, opened = [], []

    async def gateway(content, **kwargs):
        files = kwargs.get("files", [])
        opened.extend(files)
        gateway_calls.append((content, [(file.filename, file.fp.read()) for file in files], kwargs))
        return SimpleNamespace(id=len(gateway_calls))

    try:
        channel = SimpleNamespace(send=gateway, guild=SimpleNamespace(filesize_limit=DEFAULT_UPLOAD_LIMIT))
        reference = object()
        await bot._send_response(channel, "```js\nrun();\n```\n@everyone Done.", reference)
        assert gateway_calls[0][1] == [("snippet-1.js", b"run();\n")]
        assert gateway_calls[0][2]["reference"] is reference
        assert gateway_calls[1][2]["reference"] is None
        assert all(call[2]["allowed_mentions"].to_dict()["parse"] == [] for call in gateway_calls)
        assert all(file.fp.closed for file in opened)
        gateway_calls.clear()
        interaction = SimpleNamespace(channel_id=123, channel=SimpleNamespace(name="private"),
                                      filesize_limit=DEFAULT_UPLOAD_LIMIT, followup=SimpleNamespace(send=gateway))
        await bot._send_response(InteractionChannel(interaction), "```md\n# Private report\n```", reference)
        assert gateway_calls[0][2]["ephemeral"] is True and "reference" not in gateway_calls[0][2]
    finally:
        await bot.close()

    client = DiscordClient("test-token")
    await client._ensure_session()
    assert "Content-Type" not in client._session.headers, "Multipart boundary must not be overridden by a JSON session header"
    await client.close()
    requests, bodies = [], []
    statuses = iter([429, 200])

    class Reply:
        headers = {}
        def __init__(self, kwargs):
            self.status = next(statuses)
            self.kwargs = kwargs
        async def __aenter__(self):
            payload = self.kwargs["data"]()
            data = bytearray()
            async def write(chunk):
                data.extend(chunk)
            await payload.write(SimpleNamespace(write=write))
            bodies.append(bytes(data))
            return self
        async def __aexit__(self, *args):
            return False
        async def json(self):
            return {"retry_after": 0} if self.status == 429 else {"id": "sent"}

    def request(method, url, **kwargs):
        requests.append(kwargs)
        return Reply(kwargs)

    client._session = SimpleNamespace(closed=False, request=request, close=AsyncMock())
    result = await client.send_message("123", "caption", reply_to="456", files=[("image.png", b"PNG-BYTES")])
    assert result["id"] == "sent" and len(bodies) == 2
    assert requests[0]["data"] is not requests[1]["data"], "Retry must rebuild consumed multipart data"
    for body in bodies:
        assert b"PNG-BYTES" in body and b"image/png" in body and b'filename="image.png"' in body
        assert b'"parse": []' in body and b'"message_id": "456"' in body
        assert b'"attachments": [{"id": 0, "filename": "image.png"}]' in body
    await client.close()
    print("PASS: language artifacts, nested/unfinished fences, bounded fallback, safe files, tool scopes, gateway privacy and multipart retries")


if __name__ == "__main__":
    asyncio.run(main())
