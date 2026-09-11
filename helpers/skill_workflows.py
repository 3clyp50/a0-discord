"""On-demand workflows behind the existing write-capable Discord tool."""
import importlib

from helpers import skills, tool_policy
from helpers.tool import Response
from usr.plugins.discord.helpers.discord_client import DiscordClient, get_discord_config, get_modes_to_try
from usr.plugins.discord.helpers.sanitize import require_auth


WORKFLOWS = {
    "research": ("discord-research", {
        "summarize": ("discord_summarize", "DiscordSummarize"),
        "insights": ("discord_insights", "DiscordInsights"),
    }),
    "administration": ("discord-chat", {
        action: ("discord_chat", "DiscordChat")
        for action in ("start", "stop", "status", "add_channel", "remove_channel", "list")
    }),
    "monitoring": ("discord-alerts", {
        action: ("discord_poll", "DiscordPoll")
        for action in ("check", "watch", "unwatch", "list", "setup_scheduler")
    }),
    "personas": ("discord-persona-mapping", {
        action: ("discord_members", "DiscordMembers")
        for action in ("list", "info", "search", "note", "registry", "sync")
    }),
}


async def _check_scope(agent, config, parameters, workflow, operation):
    """Keep helper calls inside the same configured server boundary as reads."""
    allowed = {str(value) for value in config.get("servers", [])}
    if not allowed:
        return
    guild_id = str(parameters.get("guild_id", "") or "")
    if guild_id and guild_id not in allowed:
        raise ValueError("Server is not in this bot's allowed servers list.")
    targets = [parameters.get("thread_id") or parameters.get("channel_id")]
    if workflow == "monitoring" and operation == "check" and not targets[0]:
        from usr.plugins.discord.helpers.poll_state import get_watch_channels
        targets = list(get_watch_channels())
    for target in filter(None, targets):
        modes = get_modes_to_try(config, parameters.get("mode") or None)
        for mode in modes:
            client = DiscordClient.from_config(agent=agent, mode=mode, bot_id=config["bot_id"])
            try:
                channel = await client.get_channel(str(target))
                if str(channel.get("guild_id", "")) not in allowed:
                    raise ValueError("Channel is not in this bot's allowed servers list.")
                break
            except Exception as exc:
                if getattr(exc, "status", None) == 403 and mode != modes[-1]:
                    continue
                raise
            finally:
                await client.close()
    if workflow == "personas" and not guild_id:
        raise ValueError("Provide an allowed guild_id for persona operations when servers are restricted.")


async def run_workflow(tool):
    try:
        workflow = tool.args.get("workflow", "")
        operation = tool.args.get("operation", "")
        if not isinstance(workflow, str) or workflow not in WORKFLOWS:
            raise ValueError("Unknown Discord workflow. Load its Discord skill first.")
        skill_name, operations = WORKFLOWS[workflow]
        if skill_name not in skills.get_loaded_skill_names(tool.agent):
            raise ValueError(f"Load {skill_name} with skills_tool before using this workflow, then read its reference files.")
        if not isinstance(operation, str) or operation not in operations:
            raise ValueError("Unknown operation. Read the loaded skill's reference file.")
        parameters = tool.args.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be an object.")
        parameters = dict(parameters)
        module_name, class_name = operations[operation]
        # Retain explicit legacy blocks after removing the old public tools.
        for name in ("discord_send", module_name):
            decision = tool_policy.resolve_tool(tool.agent, name, canonical_id=f"plugin:discord:{name}")
            if not decision.allowed:
                raise ValueError(f"{name} is blocked by the current tool policy.")
        config = get_discord_config(tool.agent, bot_id=parameters.get("bot_id"))
        require_auth(config)
        if not config["bot"].get("enabled", True):
            raise ValueError("The selected Discord bot is disabled.")
        if workflow != "administration" and parameters.get("bot_id"):
            current = get_discord_config(tool.agent)
            if current["bot_id"] != parameters["bot_id"]:
                raise ValueError("This workflow uses the current chat's bot. Use that bot's chat or change the default first.")
        await _check_scope(tool.agent, config, parameters, workflow, operation)
        if workflow == "research":
            value = parameters.get("save_to_memory", "false")
            parameters["save_to_memory"] = str(value).lower()
            if parameters["save_to_memory"] not in ("true", "false"):
                raise ValueError("save_to_memory must be true or false.")
        else:
            parameters["action"] = operation
        if workflow == "monitoring" and operation == "setup_scheduler":
            interval = int(parameters.get("interval", 15))
            if interval < 1 or interval > 1440 or (interval < 60 and 60 % interval) or (interval >= 60 and (interval % 60 or 24 % (interval // 60))):
                raise ValueError("Use a supported interval: 1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 480, 720 or 1440 minutes.")
            parameters["interval"] = str(interval)
        module = importlib.import_module(f"usr.plugins.discord.helpers.workflows.{module_name}")
        backend = getattr(module, class_name)(
            agent=tool.agent, name=module_name, method=None, args=parameters,
            message=tool.message, loop_data=tool.loop_data,
        )
        backend.set_progress = tool.set_progress
        return await backend.execute()
    except (ValueError, TypeError) as exc:
        return Response(message=f"Discord workflow: {exc}", break_loop=False)
    except Exception as exc:
        return Response(message=f"Discord workflow failed: {type(exc).__name__}", break_loop=False)
