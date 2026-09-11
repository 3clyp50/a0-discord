from helpers.tool import Tool, Response
from usr.plugins.discord.helpers.discord_client import (
    DiscordClient, DiscordAPIError, format_messages, get_discord_config,
    get_modes_to_try,
)
from usr.plugins.discord.helpers.sanitize import require_auth, sanitize_channel_name


class DiscordRead(Tool):
    """Read messages, list channels, or list threads from a Discord server."""

    async def execute(self, **kwargs) -> Response:
        action = self.args.get("action", "messages")
        if action not in ("messages", "channels", "threads", "members", "member"):
            return Response(message="Use messages, channels, threads, members or member. Load a Discord skill for optional workflows.", break_loop=False)
        try:
            config = get_discord_config(self.agent, bot_id=self.args.get("bot_id"))
            require_auth(config)
            if not config["bot"].get("enabled", True):
                raise ValueError("This Discord bot is disabled.")
            guild_id = str(self.args.get("guild_id", "") or "")
            target_id = str(self.args.get("thread_id") or self.args.get("channel_id") or "")
            limit = max(1, min(int(self.args.get("limit", 50)), 1000 if action == "members" else 200))
            allowed = {str(value) for value in config.get("servers", [])}
            if action != "messages" and not guild_id:
                raise ValueError("guild_id is required.")
            if action == "messages" and not target_id:
                raise ValueError("channel_id or thread_id is required.")
            if guild_id and allowed and guild_id not in allowed:
                raise ValueError("Server is not in this bot's allowed servers list.")
            if action == "member" and not self.args.get("user_id"):
                raise ValueError("user_id is required for member lookup.")
            modes = get_modes_to_try(config, self.args.get("mode") or None)
        except (ValueError, TypeError) as exc:
            return Response(message=f"Discord read: {exc}", break_loop=False)

        for mode in modes:
            client = None
            try:
                client = DiscordClient.from_config(agent=self.agent, mode=mode, bot_id=config["bot_id"])
                if action == "channels":
                    text = _format_channels(await client.get_guild_channels(guild_id))
                elif action == "threads":
                    data = await client.get_active_threads(guild_id)
                    text = _format_threads(data.get("threads", []))
                elif action == "members":
                    members = await client.get_guild_members(guild_id, limit=limit, after=str(self.args.get("after") or "0"))
                    text = _format_members(members, guild_id)
                elif action == "member":
                    member = await client.get_guild_member(guild_id, str(self.args["user_id"]))
                    text = _format_members([member], guild_id)
                else:
                    if allowed:
                        channel = await client.get_channel(target_id)
                        if str(channel.get("guild_id", "")) not in allowed:
                            raise ValueError("Channel is not in this bot's allowed servers list.")
                    messages = await client.get_all_channel_messages(
                        channel_id=target_id, limit=limit, after=self.args.get("after") or None,
                    )
                    text = (f"Retrieved {len(messages)} messages from {target_id}:\n\n" + format_messages(messages, include_ids=True)
                            if messages else "No messages found in the specified channel/thread.")
                return Response(message=text, break_loop=False)
            except DiscordAPIError as exc:
                if exc.status == 403 and mode != modes[-1]:
                    continue
                return Response(message=f"Discord API error: {exc.status}", break_loop=False)
            except ValueError as exc:
                return Response(message=f"Discord read: {exc}", break_loop=False)
            except Exception as exc:
                return Response(message=f"Discord read failed: {type(exc).__name__}", break_loop=False)
            finally:
                if client is not None:
                    await client.close()
        return Response(message="No Discord account is available for this read.", break_loop=False)


def _format_members(members: list, guild_id: str) -> str:
    from usr.plugins.discord.helpers.sanitize import sanitize_username
    lines = [f"Members of guild {guild_id} ({len(members)} shown; this is one page):"]
    for member in members:
        user = member.get("user", {})
        username = sanitize_username(user.get("username", "Unknown"))
        display = sanitize_username(member.get("nick") or user.get("global_name") or username)
        lines.append(f"- {display} (@{username}, ID: {user.get('id', '?')})"
                     f" | Roles: {', '.join(str(role) for role in member.get('roles', []))}"
                     f" | Joined: {str(member.get('joined_at') or '')[:10]}"
                     f" | Bot: {bool(user.get('bot'))}")
    if members:
        lines.append(f"Next page: members with after={members[-1].get('user', {}).get('id', '')}")
    return "\n".join(lines)


def _format_channels(channels: list) -> str:
    if not channels:
        return "No channels found."

    categories = {}
    uncategorized = []

    for ch in channels:
        if ch.get("type") == 4:
            categories[ch["id"]] = {"name": sanitize_channel_name(ch["name"]), "channels": []}

    for ch in channels:
        if ch.get("type") == 4:
            continue
        parent = ch.get("parent_id")
        ch_type = _channel_type_name(ch.get("type", 0))
        safe_name = sanitize_channel_name(ch.get("name", "unknown"))
        entry = f"  - [{ch_type}] #{safe_name} (ID: {ch['id']})"
        if parent and parent in categories:
            categories[parent]["channels"].append(entry)
        else:
            uncategorized.append(entry)

    lines = ["Channels:"]
    for cat_data in categories.values():
        lines.append(f"\n{cat_data['name'].upper()}:")
        lines.extend(cat_data["channels"])
    if uncategorized:
        lines.append("\nUNCATEGORIZED:")
        lines.extend(uncategorized)
    return "\n".join(lines)


def _format_threads(threads: list) -> str:
    if not threads:
        return "No active threads found."
    lines = ["Active Threads:"]
    for t in threads:
        safe_name = sanitize_channel_name(t.get("name", "unknown"))
        lines.append(
            f"  - {safe_name} (ID: {t['id']}) "
            f"- {t.get('message_count', '?')} messages, {t.get('member_count', '?')} members"
        )
    return "\n".join(lines)


def _channel_type_name(type_id: int) -> str:
    return {
        0: "text", 2: "voice", 4: "category", 5: "announcement",
        10: "thread", 11: "thread", 12: "thread",
        13: "stage", 15: "forum", 16: "media",
    }.get(type_id, f"type-{type_id}")
