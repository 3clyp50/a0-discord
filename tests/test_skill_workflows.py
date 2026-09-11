"""Offline: /opt/venv-a0/bin/python -m usr.plugins.discord.tests.test_skill_workflows."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from usr.plugins.discord.helpers import skill_workflows as workflows
from usr.plugins.discord.tools.discord_read import DiscordRead


async def main():
    root = Path(__file__).resolve().parents[1]
    assert {p.stem for p in (root / "tools").glob("*.py") if p.stem != "__init__"} == {"discord_read", "discord_send"}
    assert {p.name for p in (root / "prompts").glob("agent.system.tool.*.md")} == {
        "agent.system.tool.discord_read.md", "agent.system.tool.discord_send.md",
    }
    tool = SimpleNamespace(agent=object(), args={"workflow": "research", "operation": "summarize", "parameters": {}},
                           message="", loop_data=None, set_progress=AsyncMock())
    config = {"bot_id": "default", "bot": {"token": "test", "enabled": True}, "servers": []}
    backend = SimpleNamespace(execute=AsyncMock(return_value="result"))
    factory = Mock(return_value=backend)
    with patch.object(workflows.skills, "get_loaded_skill_names", return_value=[]) as loaded, \
         patch.object(workflows.tool_policy, "resolve_tool", return_value=SimpleNamespace(allowed=True)) as policy, \
         patch.object(workflows, "get_discord_config", return_value=config), \
         patch.object(workflows.importlib, "import_module", return_value=SimpleNamespace(DiscordSummarize=factory)) as modules:
        result = await workflows.run_workflow(tool)
        assert "Load discord-research" in result.message
        modules.assert_not_called()
        loaded.return_value = ["discord-research"]
        assert await workflows.run_workflow(tool) == "result"
        assert factory.call_args.kwargs["args"]["save_to_memory"] == "false"
        assert policy.call_args.kwargs["canonical_id"] == "plugin:discord:discord_summarize"
        policy.return_value = SimpleNamespace(allowed=False)
        assert "blocked" in (await workflows.run_workflow(tool)).message
        assert backend.execute.await_count == 1
        policy.return_value = SimpleNamespace(allowed=True)
        tool.args["operation"] = "__import__"
        assert "Unknown operation" in (await workflows.run_workflow(tool)).message
        tool.args = {"workflow": "monitoring", "operation": "setup_scheduler", "parameters": {"interval": 0}}
        loaded.return_value = ["discord-alerts"]
        assert "supported interval" in (await workflows.run_workflow(tool)).message
    client = SimpleNamespace(get_guild_members=AsyncMock(return_value=[{
        "user": {"id": "456", "username": "Reporter"}, "roles": [],
    }]), close=AsyncMock())
    reader = DiscordRead(agent=object(), name="discord_read", method=None,
                         args={"action": "members", "guild_id": "123456789012345678"}, message="", loop_data=None)
    with patch("usr.plugins.discord.tools.discord_read.get_discord_config", return_value=config), \
         patch("usr.plugins.discord.tools.discord_read.DiscordClient.from_config", return_value=client):
        assert "Reporter" in (await reader.execute()).message
        client.close.assert_awaited_once()
        config["servers"] = ["999999999999999999"]
        assert "allowed" in (await reader.execute()).message
        assert client.get_guild_members.await_count == 1
    print("PASS: two-tool baseline, skill gating, legacy policy, member reads and scheduler input")


if __name__ == "__main__":
    asyncio.run(main())
