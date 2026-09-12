---
name: discord-chat
description: "On-demand Discord administration: multi-bot status, lifecycle and automatic-reply channel registration."
version: "1.2.0"
allowed-tools: [discord_read, discord_send]
---

# Discord administration

Prefer the plugin Config page for each bot's Start, Stop, Restart and status controls, tokens, presets, profiles and access rules. Save bot changes before using the controls. Never put credentials into tool arguments or Discord messages.

Mentions and replies work without registering channels. Register a channel only when the operator wants replies to every message there.

For agent-driven administration, read references/bridge.md with skills_tool action=read_file, skill_name=discord-chat. It documents the discord_send administration workflow. Pass the stable bot_id inside parameters to select a bot. New names retain existing chat mappings.

Read-only is the default. Full agent execution requires operator opt-in plus a live !auth session. Loading this skill is not elevation and does not bypass tool policy.

Stop pauses auto-start until a manual Start or Agent Zero restart. Removing channel registration does not delete saved Agent Zero chats.
