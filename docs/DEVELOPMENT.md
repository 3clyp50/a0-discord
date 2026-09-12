# Discord Integration Plugin — Development Guide

## Project Structure

```
a0-discord/
├── plugin.yaml              # Plugin manifest
├── default_config.yaml      # Default settings
├── initialize.py            # Dependency installer (aiohttp, pyyaml, discord.py)
├── hooks.py                 # Plugin lifecycle hooks (install/uninstall)
├── install.sh               # Deployment script
├── .gitignore
├── helpers/
│   ├── __init__.py
│   ├── discord_client.py    # REST API wrapper with rate limiting
│   ├── discord_bot.py       # Chat bridge bot (discord.py Gateway + AgentContext)
│   ├── sanitize.py          # Prompt injection defense, input validation
│   ├── persona_registry.py  # JSON-based persistent user tracking
│   └── poll_state.py        # Polling state tracker (last seen IDs, alert history)
├── tools/
│   ├── discord_read.py      # Read channels/threads/messages
│   ├── discord_send.py      # Send messages/reactions (bot only)
│   ├── discord_summarize.py # Summarize → LLM → memory
│   ├── discord_insights.py  # Insights → LLM → memory
│   ├── discord_members.py   # Member queries + persona registry
│   ├── discord_poll.py      # Channel monitoring with image analysis
│   └── discord_chat.py      # Chat bridge management (start/stop/add/remove)
├── prompts/
│   ├── agent.system.tool.discord_read.md
│   ├── agent.system.tool.discord_send.md
│   ├── agent.system.tool.discord_summarize.md
│   ├── agent.system.tool.discord_insights.md
│   ├── agent.system.tool.discord_members.md
│   ├── agent.system.tool.discord_poll.md
│   └── agent.system.tool.discord_chat.md
├── skills/
│   ├── discord-research/SKILL.md
│   ├── discord-communicate/SKILL.md
│   ├── discord-persona-mapping/SKILL.md
│   ├── discord-alerts/SKILL.md
│   └── discord-chat/SKILL.md
├── api/
│   ├── discord_test.py          # Connection test endpoint
│   ├── discord_config_api.py    # Custom actions (auth key generation)
│   └── discord_bridge_api.py    # Chat bridge start/stop/status
├── webui/
│   ├── discord-store.js     # Per-bot status, controls and configuration state
│   └── config.html          # Settings (Alpine.js x-model bindings)
├── extensions/
│   └── python/agent_init/_10_discord_chat.py  # Auto-start bridge
├── tests/
│   ├── regression_test.sh
│   ├── HUMAN_TEST_PLAN.md
│   ├── HUMAN_TEST_RESULTS.md
│   └── SECURITY_ASSESSMENT_RESULTS.md
└── docs/
    ├── README.md
    ├── QUICKSTART.md
    ├── SETUP.md
    ├── CHAT_BRIDGE.md
    ├── API_REFERENCE.md
    └── DEVELOPMENT.md
```

## Development Setup

1. Start the dev container:
   ```bash
   docker start agent-zero-dev
   ```

2. Install the plugin:
   ```bash
   docker cp a0-discord/. agent-zero-dev:/a0/usr/plugins/discord/
   docker exec agent-zero-dev bash /a0/usr/plugins/discord/install.sh
   ```

3. For iterative development (push changes without full reinstall):
   ```bash
   docker cp a0-discord/. agent-zero-dev:/a0/usr/plugins/discord/
   docker exec agent-zero-dev supervisorctl restart run_ui
   ```

4. Run tests:
   ```bash
   bash tests/regression_test.sh agent-zero-dev 50083
   ```

---

## WebUI Patterns

### config.html — Alpine.js x-model Standard

The settings panel uses Agent Zero's standard Alpine.js `x-model` bindings. The `config` variable is inherited from the parent scope (the framework's plugin-settings modal). The framework handles Save, Load, CSRF, and defaults automatically — no custom JavaScript is needed.

```html
<html>
<head><title>Discord Settings</title></head>
<body>
<div x-data x-init="...">
  <template x-if="config">
    <div>
      <div class="section-title">Bot Account</div>
      <div class="field">
        <label class="field-label">
          <span class="field-title">Bot Token</span>
          <span class="field-description">From Discord Developer Portal → Bot → Token</span>
        </label>
        <div class="field-control">
          <input type="password" x-model="config.bot.token" placeholder="Enter token" />
        </div>
      </div>
      <!-- Toggles use the .toggler class -->
      <div class="field">
        <label class="field-label">
          <span class="field-title">Auto-save Summaries</span>
        </label>
        <div class="field-control">
          <label class="toggle">
            <input type="checkbox" x-model="config.memory.auto_save_summaries" />
            <span class="toggler"></span>
          </label>
        </div>
      </div>
    </div>
  </template>
</div>
</body>
</html>
```

CSS classes provided by the framework: `field`, `field-label`, `field-title`, `field-description`, `field-control`, `section-title`, `section-description`, `toggle`, `toggler`.

### Bot controls in Config

`config.html` is the only plugin page. `discord-store.js` uses `createStore`,
`callJsonApi` and Agent Zero notifications for per-bot icon controls and status.
Keep runtime status separate from editable bot settings. Actions send only the
stable saved `bot_id`; new or changed drafts cannot start or restart a bot.
Stop may pause an already running bot even with pending edits. Global bridge
controls are disabled in project/profile scopes. Clean up the status timer and
ignore pending responses when the modal closes or reloads.

Run `node --test tests/test_config_store.mjs` for control routing, draft isolation
and modal lifecycle coverage.

---

## Thumbnail

Keep `thumbnail.png` (catalog) and `webui/thumbnail.png` (installed plugin list)
identical: 256x256 PNG, below 20 KB, with an opaque background and enough inset
to show the entire logo in the rounded thumbnail tile.

## Tool prompt maintenance

Public tool prompts live in `prompts/agent.system.tool.discord_read.md` and
`prompts/agent.system.tool.discord_send.md`. The read-only bridge has a separate
protocol in `prompts/discord.bridge.md`; do not mix its actions or limits with
the public reader.

Use terse directives while preserving argument names, defaults, limits, complete
JSON examples, permission boundaries and pagination rules. Compare `o200k_base`
token counts, not character counts. Template measurements exclude the injected
profile, runtime facts, checkpoints and history.

Verify rendered profile/runtime placeholders, parse examples with the framework
tool extractor and compare native tool names/schemas. Run the offline
`test_skill_workflows`, `test_mentions`, `test_bridge_search` and
`test_bridge_ledger` modules in the framework runtime.

## Adding a New Tool

For read-only bridge search, extend `helpers/bridge_reader.py` and its separate
bridge prompt instead of adding a baseline tool. `_search_server` owns bounded
four-way channel sweeps and stateless continuations; `_search` owns filters and
message cursors. Never bypass `_visible` for a cached message or resumed target.
`discord_bot.py` owns the 24-read budget, requester-scoped evidence/checkpoints
and one optional progress message. Keep server coverage separate from threads.
Run `python -m usr.plugins.discord.tests.test_server_search` in the framework
runtime for offline sweep, filter, continuation and cache checks.

### Step 1: Create the tool file

Create `tools/discord_search.py`:

```python
from helpers.tool import Tool, Response
from plugins.discord.helpers.discord_client import (
    DiscordClient, DiscordAPIError, get_discord_config,
)


class DiscordSearch(Tool):
    """Search messages in a Discord server."""

    async def execute(self, **kwargs) -> Response:
        guild_id = self.args.get("guild_id", "")
        query = self.args.get("query", "")

        if not guild_id or not query:
            return Response(
                message="Error: guild_id and query are required.",
                break_loop=False,
            )

        config = get_discord_config(self.agent)
        mode = "bot" if config.get("bot", {}).get("token") else "user"

        try:
            client = DiscordClient.from_config(agent=self.agent, mode=mode)
            self.set_progress("Searching...")

            results = await client.search_messages(guild_id=guild_id, query=query)
            await client.close()

            messages = results.get("messages", [])
            if not messages:
                return Response(
                    message=f"No messages found matching '{query}'.",
                    break_loop=False,
                )

            lines = [f"Found {len(messages)} results for '{query}':"]
            for group in messages:
                for msg in group:
                    author = msg.get("author", {}).get("username", "?")
                    content = msg.get("content", "")[:200]
                    lines.append(f"  - @{author}: {content}")

            return Response(message="\n".join(lines), break_loop=False)

        except DiscordAPIError as e:
            return Response(message=f"Discord API error: {e}", break_loop=False)
        except Exception as e:
            return Response(message=f"Error: {e}", break_loop=False)
```

### Step 2: Create the tool prompt

Create `prompts/agent.system.tool.discord_search.md`:

```markdown
## discord_search
Search messages in a Discord server by keyword.

**Arguments:**
- **guild_id** (string): Server ID to search in
- **query** (string): Search term

~~~json
{"guild_id": "123456789", "query": "migration plan"}
~~~
```

### Step 3: Restart Agent Zero

The plugin framework auto-discovers tools by filename. No registration needed.

---

## Adding a New Extension

Extensions hook into Agent Zero's lifecycle. They must subclass `Extension` and implement a sync `execute()` method.

Create `extensions/python/tool_execute_after/_50_discord_log.py`:

```python
from helpers.extension import Extension


class DiscordToolLogger(Extension):
    def execute(self, tool=None, response=None, **kwargs):
        if tool and tool.name.startswith("discord_"):
            self.agent.log.log(
                type="info",
                content=f"Discord tool {tool.name} completed",
            )
```

The `_50_` prefix controls execution order (lower = earlier). The directory name (`tool_execute_after`) must match a valid extension point.

---

## Adding a Discord API Method

To add a new Discord API call, edit `helpers/discord_client.py`:

```python
async def get_guild_roles(self, guild_id: str) -> list:
    return await self._request("GET", f"/guilds/{guild_id}/roles")
```

The `_request` method handles authentication, rate limiting, 429 retry, and error handling.

For bot-only operations, add the guard:

```python
async def ban_member(self, guild_id: str, user_id: str) -> None:
    self._assert_bot_only("ban_member")
    await self._request("PUT", f"/guilds/{guild_id}/bans/{user_id}")
```

---

## Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| Alpine.js `x-model` for config | Framework handles save/load/CSRF/defaults; no custom JS needed |
| Lazy `fetchApi` | CSRF wrapper may not exist at script parse time; must resolve at call time |
| `data-dcm=` attributes | Framework reloads WebUI components; bare IDs can collide |
| Inline `onclick` handlers | `addEventListener` accumulates on component reload |
| `window._dcMain` namespace | Prevents global pollution; survives component reload |
| `Extension` subclass with sync `execute()` | Required by A0 framework; bare async functions are not discovered |
| `hooks.py` with `logging` | `print()` doesn't route through A0's log aggregation |

---

## Testing

### Regression Tests

```bash
# Run full regression suite against a container
bash tests/regression_test.sh <container_name> <port>

# Example
bash tests/regression_test.sh a0-testing 50085
```

### Integration Testing

1. Install the plugin into a running Agent Zero instance
2. Open the WebUI and check a saved bot's status and Start, Stop and Restart controls in Config
3. Ask the agent to list channels, read messages, etc.
4. Check Agent Zero logs for errors

### Important: Plugin Installation Path

Agent Zero uses a dual-path architecture:
- `/git/agent-zero/` — source code (persists across rebuilds)
- `/a0/` — runtime copy (where the server runs from)

User plugins go in `usr/plugins/<name>/` but need a symlink at `plugins/<name>/` for Python imports:
```bash
ln -sf /a0/usr/plugins/discord /a0/plugins/discord
```

Without this symlink, `from plugins.discord.helpers...` imports will fail with `ModuleNotFoundError`. The `install.sh` script and `hooks.py` create this automatically.
