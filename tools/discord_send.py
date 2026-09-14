import asyncio
from helpers.tool import Tool, Response
from usr.plugins.discord.helpers.delivery import bridge_delivery, deliver_message, read_attachments
from usr.plugins.discord.helpers.discord_client import (
    DiscordClient, DiscordAPIError, get_discord_config,
)
from usr.plugins.discord.helpers.sanitize import require_auth, validate_snowflake


class DiscordSend(Tool):
    """Send text, explicit file attachments or reactions via a bot account."""

    async def execute(self, **kwargs) -> Response:
        if self.args.get("action") == "workflow":
            from usr.plugins.discord.helpers.skill_workflows import run_workflow
            return await run_workflow(self)
        channel_id = self.args.get("channel_id", "")
        content = self.args.get("content", "")
        paths = self.args.get("attachments", [])
        reply_to = self.args.get("reply_to", "")
        action = self.args.get("action", "send")
        final = self.args.get("final", False)
        if not isinstance(final, bool) or (final and action != "send"):
            return Response(message="Error: final must be a boolean and is only valid for send.", break_loop=False)

        try:
            channel_id = validate_snowflake(channel_id, "channel_id")
        except ValueError as e:
            return Response(message=f"Error: {e}", break_loop=False)

        try:
            config = get_discord_config(self.agent, bot_id=self.args.get("bot_id"))
            require_auth(config)
        except ValueError as e:
            return Response(message=f"Auth error: {e}", break_loop=False)
        if not (config.get("bot", {}).get("token", "") or "").strip():
            return Response(
                message="Error: Bot token not configured. Sending requires a bot account.",
                break_loop=False,
            )

        receipt = bridge_delivery.get()
        if final and not (
            receipt and receipt["bot_id"] == config["bot_id"]
            and receipt["channel_id"] == channel_id
            and receipt["context_id"] == self.agent.context.id
            and self.agent.number == 0
        ):
            return Response(
                message="Error: final=true requires the root agent's active public Discord request, using its bot and channel. Otherwise use a normal response or final=false.",
                break_loop=False,
            )

        client = None
        try:
            client = DiscordClient.from_config(agent=self.agent, mode="bot", bot_id=config["bot_id"])
            allowed_servers = {str(value) for value in config.get("servers", [])}
            if allowed_servers:
                channel = await client.get_channel(channel_id)
                if str(channel.get("guild_id", "")) not in allowed_servers:
                    return Response(message="Channel is not in this bot's allowed servers list.", break_loop=False)

            if action == "send":
                if not isinstance(content, str):
                    return Response(message="Error: content must be text.", break_loop=False)
                if not content.strip() and not paths:
                    return Response(message="Error: content or attachments is required for sending.", break_loop=False)
                if reply_to:
                    reply_to = validate_snowflake(reply_to, "reply_to")
                attachments = await asyncio.to_thread(read_attachments, paths)

                async def send(text, files, first):
                    return await client.send_message(channel_id=channel_id, content=text,
                                                     reply_to=reply_to if first and reply_to else None,
                                                     files=list(files) or None)

                results, failed = await deliver_message(send, content, attachments)
                sent_ids = [result["id"] for result in results]
                summary = f"Sent {len(sent_ids)} message(s) (IDs: {', '.join(sent_ids)})."
                if failed:
                    summary += " Attachments NOT delivered: " + ", ".join(failed)
                elif final and sent_ids:
                    receipt["sent_ids"] = sent_ids
                    summary += " Final reply delivered. Finish cleanup and use response to end the turn; the bridge will not repost it."
                return Response(message=summary, break_loop=False)

            elif action == "react":
                emoji = self.args.get("emoji", "")
                message_id = self.args.get("message_id", "")
                if not emoji or not message_id:
                    return Response(message="Error: emoji and message_id required for reactions.", break_loop=False)
                await client.add_reaction(channel_id, message_id, emoji)
                await client.close()
                return Response(message=f"Reaction {emoji} added to message {message_id}.", break_loop=False)

            else:
                return Response(message=f"Unknown action '{action}'. Use 'send' or 'react'.", break_loop=False)

        except PermissionError as e:
            return Response(message=str(e), break_loop=False)
        except ValueError as e:
            return Response(message=f"Error: {e}", break_loop=False)
        except DiscordAPIError as e:
            return Response(message=f"Discord API error: {e}", break_loop=False)
        except Exception as e:
            return Response(message=f"Error sending to Discord: {type(e).__name__}", break_loop=False)
        finally:
            if client is not None:
                await client.close()
