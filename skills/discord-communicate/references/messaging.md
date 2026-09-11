# Messaging examples

Read context before sending. Bot IDs are optional and default to the current Discord chat's bot or the first enabled configured bot.

```json
{"tool_name":"discord_send","tool_args":{"action":"send","channel_id":"123456789012345678","content":"Here is the requested summary.","reply_to":"234567890123456789"}}
```

```json
{"tool_name":"discord_send","tool_args":{"action":"react","channel_id":"123456789012345678","message_id":"234567890123456789","emoji":"✅"}}
```

An emoji can be a Unicode emoji or Discord custom emoji name:id. Posting requires the operator's authorization, bot credentials and channel permissions. Read-only bridge sessions cannot call discord_send.
