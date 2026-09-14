# Discord Plugin for Agent Zero

A full-featured Discord integration plugin for Agent Zero that enables reading, summarizing, analyzing, and interacting with Discord servers directly through the agent.

## Verification Status

| Stage | Result |
|-------|--------|
| Regression Tests | 52/52 PASS |
| Human Verification | Completed (red-team exercise) |
| Security Assessment | Red-team pentest completed 2026-03-09 |
| Standards Conformance | v1.1.0 (Alpine.js config, docs suite, thumbnail) |

## Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Tools Reference](#tools-reference)
- [Skills Reference](#skills-reference)
- [Usage Examples](#usage-examples)
- [Chat Bridge Setup Guide](#chat-bridge-setup-guide) (also see [CHAT_BRIDGE.md](CHAT_BRIDGE.md) for full reference)
- [Alert Monitoring Setup Guide](#alert-monitoring-setup-guide)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)

> For credential setup details, see [SETUP.md](SETUP.md).

---

## Installation

### Prerequisites

- Agent Zero running on the **development branch** (plugin framework required)
- A Discord Bot application (created at [Discord Developer Portal](https://discord.com/developers/applications))
- Python 3.10+ with `aiohttp`, `pyyaml`, and `discord.py` (auto-installed)

### Step 1: Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**, name it (e.g., "MyAgentZeroBot"), and create
3. Go to the **Bot** tab:
   - Click **Reset Token** and **copy the entire token** (save it somewhere safe -- you can only see it once)
   - Under **Privileged Gateway Intents**, enable:
     - **Message Content Intent** (required -- without this the bot cannot read message text)
     - **Server Members Intent** (recommended for member sync)
4. Go to the **Installation** tab (left sidebar):
   - Under **Installation Contexts**, ensure **Guild Install** is checked
   - Under **Default Install Settings** for Guild Install:
     - Add scope: `bot`
     - Add bot permissions: `View Channels`, `Send Messages`, `Read Message History`, `Add Reactions`, `Embed Links`, `Manage Messages`
   - Copy the install link
5. Open the install link in a browser to invite the bot to your server(s)

> **Note:** Use **Guild Install** (not User Install). Bots need to be installed as guild members to access server channels.

### Step 2: Install the Plugin

Agent Zero runs inside a Docker container with a dual-path architecture:
- `/git/agent-zero/` -- source code (persists across rebuilds)
- `/a0/` -- runtime copy (where the server actually runs from)

You must install to **`/a0/`** for immediate effect. The install script handles this automatically.

**Method A -- Install script (recommended):**

```bash
# Copy plugin source into the container
docker cp discord-plugin/ <container_name>:/tmp/discord-plugin

# Run the installer
docker exec <container_name> bash /tmp/discord-plugin/install.sh
```

The install script:
- Auto-detects the Agent Zero root (`/a0/` or `/git/agent-zero/`)
- Copies plugin files to `usr/plugins/discord/`
- Creates the required symlink at `plugins/discord` -> `usr/plugins/discord`
- Installs Python dependencies (`aiohttp`, `pyyaml`, `discord.py`)
- Enables the plugin (creates `.toggle-1`)
- Also copies to `/git/agent-zero/` for persistence across container rebuilds

**Method B -- Manual Docker install:**

```bash
# Copy plugin files
docker cp discord-plugin/ <container_name>:/a0/usr/plugins/discord

# Create symlink (REQUIRED for Python imports)
docker exec <container_name> ln -sf /a0/usr/plugins/discord /a0/plugins/discord

# Install dependencies
docker exec <container_name> python /a0/usr/plugins/discord/initialize.py

# Enable the plugin
docker exec <container_name> touch /a0/usr/plugins/discord/.toggle-1

# Also copy to /git/agent-zero/ for persistence across rebuilds
docker exec <container_name> bash -c "mkdir -p /git/agent-zero/usr/plugins && cp -r /a0/usr/plugins/discord /git/agent-zero/usr/plugins/discord"

# Restart Agent Zero
docker exec <container_name> supervisorctl restart run_ui
```

> **Important:** The symlink from `plugins/discord` to `usr/plugins/discord` is **required**. Without it, Python imports like `from plugins.discord.helpers.discord_client import ...` will fail with `ModuleNotFoundError`.

**Method C -- Local/mapped volume:**

```bash
cd discord-plugin
./install.sh /path/to/agent-zero
```

### Step 3: Configure the Bot Token

**Option A -- Config file (most reliable):**

```bash
docker exec <container_name> bash -c 'cat > /a0/usr/plugins/discord/config.json << EOF
{
  "bot": {
    "token": "YOUR_BOT_TOKEN_HERE"
  }
}
EOF'
```

**Option B -- Environment variable:**

Add to your Agent Zero `.env` or Docker environment:

```
DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
```

**Option C -- WebUI:**

Open Agent Zero's web interface, navigate to the Discord plugin settings page, and enter your bot token.

### Step 4: Restart Agent Zero

```bash
docker exec <container_name> supervisorctl restart run_ui
```

### Step 5: Verify Installation

Test the connection:

```bash
# Quick API test
docker exec <container_name> curl -s http://localhost/api/plugins/discord/discord_test | python3 -m json.tool
```

Expected output:
```json
{
    "ok": true,
    "user": "MyAgentZeroBot",
    "mode": "bot",
    "id": "1234567890123456789"
}
```

Or open Agent Zero's chat and say:
> List channels in Discord server YOUR_SERVER_ID

---

## Configuration

### Full Configuration Reference

Configuration is stored in `usr/plugins/discord/config.json`. Defaults come from `default_config.yaml`.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `bot.token` | string | `""` | Discord bot token (primary) |
| `user.token` | string | `""` | User token for read-only access (optional) |
| `user.read_only` | bool | `true` | Enforced -- user tokens cannot send |
| `servers` | list | `[]` | Allowed guild IDs. Empty = all servers |
| `defaults.message_limit` | int | `100` | Default messages for summarization |
| `defaults.insight_limit` | int | `200` | Default messages for insight extraction |
| `defaults.member_sync_limit` | int | `1000` | Max members per guild sync |
| `memory.auto_save_summaries` | bool | `true` | Auto-persist summaries to memory |
| `memory.auto_save_insights` | bool | `true` | Auto-persist insights to memory |
| `memory.export_format` | string | `"markdown"` | Export format (markdown or json) |
| `persona.auto_sync_on_read` | bool | `false` | Auto-update persona registry on reads |
| `persona.track_activity` | bool | `true` | Track last-seen timestamps |
| `polling.interval_minutes` | int | `15` | Default alert polling interval |
| `polling.auto_analyze_images` | bool | `true` | Analyze images in polled alerts |
| `chat_bridge.auto_start` | bool | `false` | Auto-start chat bridge on agent init |
| `chat_bridge.allowed_users` | list | `[]` | Discord user IDs allowed to interact with the bridge. Empty = allow all. |

### Token Modes

| Mode | Capabilities | ToS Compliance |
|------|-------------|----------------|
| **Bot token** | Read + Write + React + Member info + Chat bridge | Fully compliant |
| **User token** | Read-only (messages, channels, members) | Gray area -- use at own risk |

The plugin always prefers the bot token. The user token is only used when no bot token is configured, and it is **hard-gated to read-only operations** -- any attempt to send a message or react with a user token raises a `PermissionError`.

The chat bridge **requires a bot token** -- it uses Discord's Gateway (WebSocket) connection which only works with bot authentication.

### Multi-Server Setup

Add guild IDs to the `servers` list to restrict which servers the plugin can access:

```json
{
  "servers": [
    "1234567890123456789",
    "9876543210987654321"
  ]
}
```

Leave `servers` empty (`[]`) to allow access to all servers the bot has been invited to.

### Getting Discord IDs

1. Open Discord desktop or web app
2. Go to **User Settings > Advanced > Developer Mode** and enable it
3. Right-click any server name, channel, user, or message and select **Copy ID**

You can also extract IDs from a Discord channel URL:
```
https://discord.com/channels/SERVER_ID/CHANNEL_ID
```

---

## Tools Reference

The plugin provides 7 tools that Agent Zero's LLM can invoke:

### `discord_read`

Read messages, list channels, or list active threads.

| Argument | Required | Description |
|----------|----------|-------------|
| `action` | yes | `messages`, `channels`, or `threads` |
| `channel_id` | for messages | Target channel ID |
| `thread_id` | optional | Thread ID (replaces channel_id) |
| `guild_id` | for channels/threads | Server ID |
| `limit` | no | Messages to fetch (default 50, max 200) |
| `after` | no | Only messages after this message ID |

### `discord_send`

Send a message or add a reaction. **Bot token required.**

| Argument | Required | Description |
|----------|----------|-------------|
| `action` | yes | `send` or `react` |
| `channel_id` | yes | Target channel ID |
| `content` | for send | Message text |
| `reply_to` | no | Message ID to reply to |
| `message_id` | for react | Target message ID |
| `emoji` | for react | Emoji to react with |

### `discord_summarize`

Summarize a channel or thread conversation. Auto-saves to Agent Zero memory.

| Argument | Required | Description |
|----------|----------|-------------|
| `channel_id` | yes* | Channel to summarize |
| `thread_id` | yes* | Thread to summarize (*one of these*) |
| `guild_id` | no | Server ID for labeling |
| `limit` | no | Messages to analyze (default 100) |
| `save_to_memory` | no | `"true"` or `"false"` (default `"true"`) |

### `discord_insights`

Extract high-level ideas and research concepts. Deeper than summarization.

| Argument | Required | Description |
|----------|----------|-------------|
| `channel_id` | yes* | Channel to analyze |
| `thread_id` | yes* | Thread to analyze (*one of these*) |
| `guild_id` | no | Server ID for labeling |
| `limit` | no | Messages to analyze (default 200) |
| `focus` | no | Specific topic to focus on |
| `save_to_memory` | no | `"true"` or `"false"` (default `"true"`) |

### `discord_members`

Query members and manage the persona registry.

| Argument | Required | Description |
|----------|----------|-------------|
| `action` | yes | `list`, `info`, `search`, `note`, `registry`, `sync` |
| `guild_id` | varies | Server ID |
| `user_id` | varies | User ID |
| `query` | for search | Search term |
| `notes` | for note | Notes to attach to a user |

### `discord_poll`

Monitor channels for new messages with automatic image analysis. Tracks last-seen message per channel so each poll only returns new content.

| Argument | Required | Description |
|----------|----------|-------------|
| `action` | yes | `check`, `watch`, `unwatch`, `list`, `setup_scheduler` |
| `channel_id` | varies | Channel to watch or check |
| `guild_id` | for watch | Server ID |
| `label` | no | Friendly name for the channel |
| `owner_id` | no | Only alert on messages from this user |
| `interval` | for scheduler | Minutes between polls (default 15) |

**Image support:** When alerts contain image attachments (charts, targets, screenshots), the images are automatically downloaded, compressed, and injected into the agent's context for multimodal analysis by the LLM.

### `discord_chat`

Manage the Discord chat bridge -- a persistent bot that routes Discord messages through Agent Zero's LLM. Users can chat with the agent directly from designated Discord channels.

| Argument | Required | Description |
|----------|----------|-------------|
| `action` | yes | `start`, `stop`, `add_channel`, `remove_channel`, `list`, `status` |
| `channel_id` | varies | Channel ID (for add/remove) |
| `guild_id` | for add | Server ID |
| `label` | no | Friendly name for the channel |

**How it works:** The chat bridge uses Discord's Gateway (WebSocket) connection via the `discord.py` library for real-time message delivery. Each designated channel gets its own conversation context. Messages from Discord users are prefixed with their display name and routed through Agent Zero's LLM. The bot shows a typing indicator while processing and automatically splits long responses into 2000-character chunks. Image attachments are saved to temp files and forwarded to the LLM for analysis.

---

## Skills Reference

Five SKILL.md skills are included and installed to `usr/skills/`:

| Skill | Triggers | Description |
|-------|----------|-------------|
| `discord-research` | "summarize discord", "discord insights" | Full research workflow |
| `discord-communicate` | "send discord message", "reply on discord" | Messaging workflow |
| `discord-persona-mapping` | "discord personas", "who is on discord" | Community mapping |
| `discord-alerts` | "monitor discord", "discord alerts" | Alert monitoring with image analysis |
| `discord-chat` | "discord chat bridge", "chat through discord" | Discord as LLM chat frontend |

Skills are loaded semantically -- just mention Discord research or summarization in your message and Agent Zero will activate the appropriate skill.

---

## Usage Examples

### Example 1: Explore a Server

**You say:**
> Show me the channels in my Discord server YOUR_SERVER_ID

**Agent Zero will:**
1. Call `discord_read` with `action: channels` and the guild ID
2. Return a categorized channel listing with IDs

**Output:**
```
Channels:

GENERAL:
  - [text] #general (ID: 1111111111111111111)
  - [text] #announcements (ID: 2222222222222222222)
  - [voice] #voice-chat (ID: 3333333333333333333)

DEVELOPMENT:
  - [text] #dev-chat (ID: 4444444444444444444)
  - [text] #code-review (ID: 5555555555555555555)
  - [forum] #proposals (ID: 6666666666666666666)
```

### Example 2: Summarize a Channel

**You say:**
> Summarize the last 150 messages in #dev-chat (channel ID YOUR_CHANNEL_ID) from server YOUR_SERVER_ID

**Agent Zero will:**
1. Call `discord_summarize` with the channel ID, guild ID, and limit 150
2. Fetch the messages via Discord API
3. Run them through the utility LLM for structured summarization
4. Auto-save the summary to Agent Zero memory
5. Return the summary

### Example 3: Deep Research with Focused Insights

**You say:**
> Extract insights about tokenomics and governance from #proposals (channel YOUR_CHANNEL_ID), analyze the last 300 messages

**Agent Zero will:**
1. Call `discord_insights` with the channel ID, limit 300, and focus "tokenomics and governance"
2. Return structured research findings including themes, key ideas, knowledge findings, and research directions

### Example 4: Track Community Members

**You say:**
> Sync the members from server YOUR_SERVER_ID and tell me about user YOUR_USER_ID

**Agent Zero will:**
1. Call `discord_members` with `action: sync` and the guild ID
2. Call `discord_members` with `action: info` for the specific user
3. Return combined Discord + persona registry data

**Follow up:**
> Add a note that this user is the lead smart contract developer and focuses on Solidity

**Agent Zero will:**
1. Call `discord_members` with `action: note`, the user ID, and the note text
2. The note persists in the persona registry across all future sessions

### Example 5: Send a Message

**You say:**
> Send a message to #general (channel YOUR_CHANNEL_ID) saying "The v2 staging environment is now live."

**Agent Zero will:**
1. Call `discord_send` with `action: send`, the channel ID, and the content
2. Confirm the message was sent with the message ID

### Example 6: Reply to a Specific Message

**You say:**
> Read the last 10 messages in #dev-chat, then reply to the one from @bob about the staging environment

**Agent Zero will:**
1. Call `discord_read` to get recent messages (with IDs)
2. Identify Bob's message about the staging environment
3. Call `discord_send` with `reply_to` set to that message ID

### Example 7: Research Workflow (Multi-Step)

**You say:**
> I want a full research breakdown of the Discord server YOUR_SERVER_ID. Start by mapping the channels, then summarize the top 3 most active text channels, and extract insights focused on product roadmap.

**Agent Zero will run a multi-step workflow:**

1. `discord_read` -- list all channels in the server
2. `discord_read` -- read messages from the 3 most active channels
3. `discord_summarize` -- summarize each channel (3 summaries, all auto-saved to memory)
4. `discord_insights` -- extract insights with focus "product roadmap"
5. Present a consolidated report

All summaries and insights are automatically persisted in Agent Zero's memory system, so you can reference them in future conversations.

### Example 8: Set Up the Discord Chat Bridge

**You say:**
> I want to chat with you through Discord. Set up a chat bridge in channel YOUR_CHANNEL_ID in server YOUR_SERVER_ID, call it "llm-chat"

**Agent Zero will:**
1. Call `discord_chat` with `action: add_channel` to register the channel
2. Call `discord_chat` with `action: start` to launch the bot
3. Confirm the bridge is live

```
Channel YOUR_CHANNEL_ID added to chat bridge (#llm-chat).
Messages in this channel will be routed to Agent Zero's LLM.

Chat bridge started as MyBot#1234.
Listening in 1 channel(s).
```

Now anyone messaging in `#llm-chat` on Discord will get responses from Agent Zero's LLM.

### Example 9: Set Up Alert Monitoring

**You say:**
> Watch Discord channel YOUR_CHANNEL_ID in server YOUR_SERVER_ID, call it "alerts", filter to user OWNER_USER_ID. Then set up polling every 15 minutes.

**Agent Zero will:**
1. `discord_poll` with `action: watch` -- registers the channel with owner filtering
2. `discord_poll` with `action: setup_scheduler` -- creates a scheduled task

### Example 10: Manual Alert Check

**You say:**
> Check for new Discord alerts

**Agent Zero will:**
1. Call `discord_poll` with `action: check`
2. Fetch only messages newer than the last poll
3. Download and analyze any images
4. Return results (or "No new alerts found" if nothing new)

---

## Chat Bridge Setup Guide

For full details, see [CHAT_BRIDGE.md](CHAT_BRIDGE.md).

### Prerequisites

- A Discord **bot token** (the bot must be in the server)
- A **channel ID** where you want the bot to respond
- The bot must have **Message Content Intent** enabled in the Developer Portal

### Quick Setup (3 commands to Agent Zero)

```
You: List channels in Discord server YOUR_SERVER_ID
Agent: [shows channels with IDs]

You: Add channel YOUR_CHANNEL_ID to the Discord chat bridge, call it "llm-chat"
Agent: Channel added to chat bridge (#llm-chat).

You: Start the Discord chat bridge
Agent: Chat bridge started as MyBot#1234. Listening in 1 channel(s).
```

Go to `#llm-chat` in Discord and start chatting.

### Security Configuration

The chat bridge includes multiple security layers. See [CHAT_BRIDGE.md -- Security](CHAT_BRIDGE.md#security) for full details.

**User Allowlist** -- Restrict which Discord users can interact with the bot:
```json
{
  "chat_bridge": {
    "allowed_users": ["YOUR_DISCORD_USER_ID"]
  }
}
```
Unlisted users are silently ignored. Changes take effect immediately without restarting the bridge.

**Agent access approvals** -- Contact the bot, then approve the exact bot/server/user/channel in Config > Agent access under Global / All profiles. Choose 1 hour (default), 8 hours, 24 hours, or Until revoked for permanent access. All approvals survive restarts and still require the existing server/user allowlists. Revoke blocks new requests; stop active tasks separately. Messages and slash commands share this gate. See [the bridge guide](CHAT_BRIDGE.md#agent-access-approvals).

### How It Works

```
Discord User types in #llm-chat
    |
    v
Discord Gateway (WebSocket) delivers message to bot
    |
    v
ChatBridgeBot.on_message() fires
    |
    v
Check: is this channel in our chat channel list? (ignore if not)
Check: is this from a bot? (ignore bots)
    |
    v
Show typing indicator
    |
    v
Create/retrieve AgentContext for this channel
Route through AgentContext.communicate(UserMessage(...))
  - Prefixed with "[Discord - DisplayName]: "
  - Image attachments saved to temp files and forwarded
  - Per-channel conversation context maintained
    |
    v
LLM processes and generates response
    |
    v
Response sent back to Discord channel (split if > 2000 chars)
  - First chunk replies to the original message
```

### Conversation Context

Each Discord channel gets its own Agent Zero conversation context:
- Conversation history is maintained per channel across messages
- Different channels have independent conversations
- Restarting the bot preserves channel assignments (stored in `data/chat_bridge_state.json`)
- After a full Agent Zero restart, conversation history resets but channel assignments persist

---

## Alert Monitoring Setup Guide

### Prerequisites

- A configured bot or user token
- The **server (guild) ID** and **channel ID** you want to monitor
- Optionally, the **user ID** of the person whose alerts you want to track

### Step-by-Step

1. **Get Discord IDs** -- Enable Developer Mode in Discord, then right-click to copy Server ID, Channel ID, and optionally the owner's User ID

2. **Register the watch**:
   > Watch Discord channel YOUR_CHANNEL_ID in server YOUR_SERVER_ID, call it "alerts", filter to user OWNER_USER_ID

3. **Test manually**:
   > Check for new Discord alerts

4. **Set up automatic polling**:
   > Set up Discord alert polling every 15 minutes

### What Happens When an Alert Arrives

Every polling interval, Agent Zero automatically:
1. Checks the watched channel for messages newer than the last poll
2. Filters to only the specified user's messages (if `owner_id` is set)
3. Downloads and compresses any image attachments
4. Injects images into the agent's context for multimodal analysis
5. Saves everything to Agent Zero's memory system
6. Records the last seen message ID so the next poll only gets new content

### Managing Watches

| Action | What to say |
|--------|-------------|
| See all watches | "Show me what Discord channels I'm monitoring" |
| Add another channel | "Also watch channel X in server Y" |
| Stop watching | "Stop watching Discord channel YOUR_CHANNEL_ID" |
| Manual check | "Check for new Discord alerts" |

---

## Architecture

### Plugin Structure

```
usr/plugins/discord/
+-- plugin.yaml              # Manifest (discovered by plugin framework)
+-- default_config.yaml      # Default settings
+-- config.json              # Active config (created via WebUI or API)
+-- initialize.py            # Dependency installer
+-- hooks.py                 # Plugin lifecycle hooks (install/uninstall)
+-- install.sh               # Automated installer
+-- helpers/
|   +-- discord_client.py    # REST API wrapper with rate limiting
|   +-- discord_bot.py       # Chat bridge bot (discord.py Gateway)
|   +-- persona_registry.py  # Persistent user tracking (JSON)
|   +-- poll_state.py        # Polling state tracker
+-- tools/                   # 7 tools (auto-discovered)
|   +-- discord_read.py
|   +-- discord_send.py
|   +-- discord_summarize.py
|   +-- discord_insights.py
|   +-- discord_members.py
|   +-- discord_poll.py
|   +-- discord_chat.py
+-- prompts/                 # LLM tool descriptions (auto-discovered)
+-- extensions/python/
|   +-- agent_init/          # Auto-start chat bridge on agent init
+-- api/                     # WebUI API endpoints
|   +-- discord_test.py      # POST /api/plugins/discord/discord_test
|   +-- discord_config_api.py  # POST /api/plugins/discord/discord_config_api (auth key generation)
+-- webui/                   # Dashboard + settings UI
+-- skills/                  # 5 SKILL.md files (copied to usr/skills/)
+-- data/
|   +-- persona_registry.json     # User tracking data
|   +-- poll_state.json           # Polling state
|   +-- chat_bridge_state.json    # Chat bridge channel assignments
+-- docs/                    # Documentation
|   +-- README.md            # Full reference (this file)
|   +-- QUICKSTART.md        # 5-minute setup guide
|   +-- SETUP.md             # Credential setup guide
|   +-- CHAT_BRIDGE.md       # Chat bridge reference
|   +-- API_REFERENCE.md     # API endpoints and data formats
|   +-- DEVELOPMENT.md       # Development guide
```

### How It Works

1. **Plugin discovery**: Agent Zero scans `usr/plugins/` for directories containing `plugin.yaml`. A symlink at `plugins/discord` -> `usr/plugins/discord` enables Python imports.

2. **Tool invocation**: When you ask about Discord, the LLM sees the tool prompts in its system context and outputs a tool call (e.g., `discord_read`). Agent Zero resolves `discord_read.py` from `plugins/discord/tools/`, loads the `DiscordRead` class, and calls `execute()`.

3. **Discord API**: The tool creates a `DiscordClient` instance, authenticates with the configured token, makes REST API calls to Discord, and returns formatted results.

4. **Memory integration**: Summarization and insight tools use the memory plugin's API (`Memory.get(agent)` -> `db.insert_text()`) to persist results. If the memory plugin isn't available, results are saved as markdown files.

5. **Chat bridge**: Uses `discord.py`'s Gateway (WebSocket) for real-time messages. Creates an `AgentContext` (matching A0's own `api_message.py` pattern) for each channel and routes messages through `AgentContext.communicate()`.

### Data Flow

```
User Message
    |
    v
Agent Zero LLM (sees tool prompts)
    |
    v
Tool Call: discord_read / discord_summarize / etc.
    |
    v
DiscordClient (REST API -> Discord)
    |
    v
Response formatted -> returned to LLM
    |
    v
(Optional) Saved to Memory / Persona Registry
    |
    v
Agent responds to user
```

---

## Troubleshooting

### Plugin Not Loading

1. Verify `plugin.yaml` exists in the plugin directory
2. Check the symlink: `ls -la /a0/plugins/discord` -- should point to `/a0/usr/plugins/discord`
3. Check for `.toggle-1` file (or remove any `.toggle-0` file)
4. Make sure you're on the development branch (plugin framework required)
5. Check Agent Zero logs for loading errors

### "No module named 'plugins.discord'"

The symlink is missing. Create it:
```bash
docker exec <container_name> ln -sf /a0/usr/plugins/discord /a0/plugins/discord
```

### "Bot token not configured"

Set `DISCORD_BOT_TOKEN` as an environment variable, write it to `config.json`, or configure via the WebUI settings page.

### "Discord API error 403"

The bot lacks permissions in the target channel. Ensure the bot role has:
- View Channels
- Read Message History
- Send Messages (for sending)

### "Discord API error 401"

Invalid or expired token. Generate a new token from the Discord Developer Portal > Bot tab > Reset Token.

### "No messages found"

- The channel might be empty or the bot doesn't have `Read Message History` permission
- Check that the channel/thread ID is correct (use Developer Mode to copy IDs)

### Chat Bridge Not Responding

1. **Check the User Allowlist** -- If `chat_bridge.allowed_users` is configured, only listed user IDs get responses. Verify your user ID is in the list.
2. Check status: ask "Show Discord chat bridge status"
3. Verify the channel is registered: ask "List Discord chat bridge channels"
4. Ensure **Message Content Intent** is enabled in Developer Portal > Bot > Privileged Gateway Intents
5. The bot only responds in explicitly added channels -- check the channel ID
6. Check Agent Zero logs for `discord_chat_bridge` logger messages

### Chat Bridge Won't Start

- Verify the bot token: `curl -H "Authorization: Bot YOUR_TOKEN" https://discord.com/api/v10/users/@me`
- If you see "Bot failed to connect within timeout", check network access to `gateway.discord.gg`
- Only one bot instance runs at a time. If it shows "already running", stop it first

### Config Changes Not Taking Effect

After editing config files directly, restart Agent Zero:
```bash
docker exec <container_name> supervisorctl restart run_ui
```

If updating Python code, also clear the bytecode cache:
```bash
docker exec <container_name> find /a0 -path '*/discord*/__pycache__' -type d -exec rm -rf {} +
docker exec <container_name> supervisorctl restart run_ui
```

### Rate Limiting

The plugin handles Discord rate limits automatically with backoff. If you're hitting limits frequently, increase the time between requests or reduce the `limit` parameter.

### Memory Save Failures

If summaries aren't saving to memory, the plugin falls back to writing markdown files to `memory/discord_summaries/`, `memory/discord_insights/`, and `memory/discord_alerts/` inside the Agent Zero root. Check that the directory exists and is writable.

### Polling Returns "No new alerts found" Every Time

- **First poll** sets the baseline -- it won't alert on messages that existed before you started watching. New messages posted *after* the first poll will be detected.
- If `owner_id` is set, only that user's messages count. Verify the owner ID is correct.
- Check that the token has access to the channel: try `discord_read` with `action: messages` first.

### Images Not Being Analyzed

- Your main chat model must support **vision/multimodal** input (e.g., GPT-4o, Claude Opus/Sonnet, Gemini Pro Vision)
- Text-only models will receive the image data but cannot interpret it
- Large images are automatically compressed to max 768K pixels at JPEG quality 75

### Files Changed But Not Taking Effect

Agent Zero runs from `/a0/`, not `/git/agent-zero/`. Always copy changes to `/a0/usr/plugins/discord/`, clear `__pycache__`, and restart:

```bash
docker cp your-file.py <container_name>:/a0/usr/plugins/discord/path/to/file.py
docker exec <container_name> find /a0 -path '*/discord*/__pycache__' -type d -exec rm -rf {} +
docker exec <container_name> supervisorctl restart run_ui
```
