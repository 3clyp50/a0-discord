"""Discord transport for the shared Agent Zero slash-command catalog."""
from __future__ import annotations

import io
import logging
import shlex
from copy import deepcopy

import discord
from agent import AgentContext
from helpers import integration_commands, plugins, projects, tool_policy
from helpers.persist_chat import save_tmp_chat
from plugins._commands.helpers import commands

logger = logging.getLogger(__name__)
PAGE_SIZE = 8


def _page(items, args):
    page = int(args or '1')
    if page < 1:
        raise ValueError('Page numbers start at 1.')
    pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages)
    return items[(page - 1) * PAGE_SIZE:page * PAGE_SIZE], f'Page {page}/{pages}'


class DiscordCommands:
    def __init__(self, bot, message):
        self.bot = bot
        self.message = message
        self.context = bot._get_bridge_context(str(message.channel.id), message)

    async def reply(self, context, text):
        # Command output must never ping users or roles, including script output.
        from usr.plugins.discord.helpers.discord_bot import _split_message
        for chunk in _split_message(text):
            await self.message.channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())

    async def handle(self, text):
        """Return rendered agent input, or None for a completed control command."""
        context = self.context
        invocation = commands.parse_slash_invocation(text)
        name, args = invocation['command_name'], invocation['raw_arguments']
        if not name:
            return text
        try:
            catalog = commands.list_context_commands(context)
            item = next((item for item in catalog if item['name'] == name), None)
            if not item:
                item = next((item for item in catalog if item['name'].replace('-', '_') == name), None)
            name = item['name'] if item else name
            custom = item and item.get('source_scope_key') != 'builtin'
            if not custom:
                if name in {'profile', 'agent', 'project', 'model', 'models', 'presets', 'config'} and args and context.is_running():
                    raise ValueError('Stop the active run before changing chat settings.')
                if name in {'commands', 'help'}:
                    await self.command_menu(context, catalog, args)
                    return None
                if name in {'sessions', 'session', 'chats'}:
                    await self.session_menu(context, args)
                    return None
                if name == 'chat':
                    target = AgentContext.get(args)
                    self.select_session(context, target)
                    await self.reply(context, f"Switched to {target.name or target.id}.")
                    return None
                if item and name in {'plugins', 'permissions'}:
                    await self.settings_menu(context, name, args)
                    return None
                if item and name == 'compact':
                    await self.compact(context, args)
                    return None
                if item and name == 'quit':
                    await self.reply(context, 'Use /stop to stop the active task. Close Discord to leave the conversation.')
                    return None
                alias = {'models': 'model', 'presets': 'model'}.get(name, name)
                # Preserve Discord controls and aliases; shared /queue supports item removal.
                if name not in {'new', 'queue', 'profile'} or not item:
                    result = integration_commands.try_handle_command(context, f"/{alias} {args}".rstrip(), integration='discord')
                    if result is not None:
                        await self.reply(context, result)
                        return None
            if not item:
                if text.lstrip().startswith('/'):
                    await self.reply(context, f"Unknown command: /{name}. Use /commands to see commands for this chat.")
                    return None
                return text
            resolution = await commands.resolve_command_invocation(
                path=item['path'], slash_text=f"/{name} {args}".rstrip(),
                project_name=projects.get_context_project_name(context) or '', context_id=context.id,
            )
            return await self.apply_result(context, name, resolution['result'])
        except ValueError as exc:
            await self.reply(context, str(exc))
            return None
        except Exception:
            logger.exception('Discord command /%s failed', name)
            await self.reply(context, f"/{name} failed. Check the Agent Zero logs.")
            return None

    async def apply_result(self, context, name, result):
        text = str(result.get('text') or '')
        notes = []
        for effect in result.get('effects') or []:
            if not isinstance(effect, dict):
                continue
            kind = str(effect.get('type') or '').lower()
            if kind in {'replace_input', 'send_message'}:
                text = str(effect.get('text') or (text if kind == 'send_message' else ''))
            elif kind == 'append_input':
                text = '\n'.join(filter(None, (text, str(effect.get('text') or ''))))
            elif kind in {'toast', 'show_markdown'}:
                notes.append(str(effect.get('message' if kind == 'toast' else 'content') or ''))
            elif kind == 'goal_changed':
                pass
            elif kind == 'new_chat':
                if context.is_running():
                    raise ValueError('Stop the active run before creating a new chat.')
                target = AgentContext(deepcopy(context.config), name='Discord: new chat')
                target.data.update({key: deepcopy(value) for key, value in context.data.items()
                                    if key in {'discord_bot_id', 'discord_channel_id', 'chat_model_override'}})
                project = projects.get_context_project_name(context)
                if project:
                    projects.activate_project(target.id, project)
                self._activate_session(target)
                notes.append(f'New chat: {target.id}.')
            elif kind == 'select_chat':
                self.select_session(context, AgentContext.get(str(effect.get('context_id') or '')))
            elif kind in {'pause_agent', 'nudge_agent', 'reset_chat', 'clear_transcript'}:
                action = ('nudge' if kind == 'nudge_agent' else
                          ('pause' if effect.get('paused') else 'resume') if kind == 'pause_agent' else 'clear')
                notes.append(integration_commands.try_handle_command(context, f'/{action}', integration='discord') or '')
            elif kind == 'compact_chat':
                await self.compact(context, '')
            elif kind == 'copy_transcript':
                await self.export_transcript(context)
            elif kind == 'attach_files':
                notes.append("Use Discord's attachment button to send images with an optional command in the message.")
            elif kind == 'computer_use':
                notes.append(str(effect.get('fallback') or 'Change host computer permissions in A0 Launcher or A0 CLI.'))
            elif kind == 'test_agent_profile':
                notes.append(integration_commands.try_handle_command(context, f"/agent {effect.get('profile_id', '')}", integration='discord') or '')
            elif kind == 'open_agent_editor' and effect.get('view') == 'manage':
                notes.append(integration_commands.try_handle_command(context, '/agent', integration='discord') or '')
            elif kind in {'open_modal', 'open_plugin_config', 'open_agent_editor'}:
                path = effect.get('path', '')
                if name in {'plugins', 'permissions'}:
                    await self.settings_menu(context, name, '')
                elif name in {'models', 'presets', 'project'}:
                    action = 'project' if name == 'project' else 'model'
                    notes.append(integration_commands.try_handle_command(context, f'/{action}', integration='discord') or '')
                elif path == '/plugins/_browser/webui/main.html':
                    notes.append('Browser: /browser status, /browser container, or /browser host.')
                else:
                    notes.append(f'/{name} opens settings in the Agent Zero WebUI. Open the WebUI to edit these settings.')
            else:
                notes.append(f"/{name}: the '{kind}' action requires the Agent Zero WebUI.")
        if notes:
            await self.reply(context, '\n\n'.join(filter(None, notes)))
        elif not text.strip() and not result.get('effects'):
            await self.reply(context, f'/{name} complete.')
        return text if text.strip() else None

    async def command_menu(self, context, catalog, args):
        items = {item['name']: (item.get('description', ''), item.get('argument_hint', '')) for item in catalog}
        for definition in integration_commands.COMMAND_REGISTRY:
            if integration_commands.resolve_command(definition.name, integration='discord'):
                items.setdefault(definition.name, (definition.description, definition.args_hint))
        items['sessions'] = ('List this Discord conversation\'s Agent Zero chats.', '[page]')
        if 'chats' in items:
            items['chats'] = items['sessions']
        for name, hint in {'plugins': '[page <number>|<name> on|off]',
                           'permissions': '[page <number>|<tool ID> allow|block|default|inherit]',
                           'compact': '[confirm <chat ID>]'}.items():
            item = next((item for item in catalog if item['name'] == name), None)
            if item and item.get('source_scope_key') == 'builtin':
                items[name] = (items[name][0], hint)
        rows, label = _page(sorted(items.items()), args)
        await self.reply(context, 'Commands for this chat\n\n' + '\n\n'.join(
            f"/{name}{' ' + hint if hint else ''} — {description}" for name, (description, hint) in rows
        ) + f'\n\n{label}. Use /commands <page> for another page.')

    def _sessions(self, context):
        return [item for item in AgentContext.all() if self._same_channel(context, item)]

    def _same_channel(self, context, target):
        return bool(target and context.data.get('discord_channel_id')
                    and target.data.get('discord_channel_id') == context.data['discord_channel_id']
                    and target.data.get('discord_bot_id') == self.bot.bot_id)

    async def session_menu(self, context, args):
        rows, label = _page(self._sessions(context), args)
        await self.reply(context, 'Chats for this Discord channel\n\n' + '\n'.join(
            f"{'Current: ' if item.id == context.id else ''}{item.name or item.id} — /chat {item.id}" for item in rows
        ) + f'\n\n{label}. Use /sessions <page>.')

    def select_session(self, context, target):
        if not self._same_channel(context, target):
            raise ValueError('Choose a chat from /sessions for this Discord channel and bot.')
        if context.is_running() or target.is_running():
            raise ValueError('Stop the active run before switching chats.')
        self._activate_session(target)

    def _activate_session(self, target):
        from usr.plugins.discord.helpers.discord_bot import set_context_id
        save_tmp_chat(target)
        set_context_id(str(self.message.channel.id), target.id, self.bot.bot_id)
        self.context = target

    async def settings_menu(self, context, name, args):
        parts = shlex.split(args)
        if name == 'plugins':
            names = sorted(plugins.get_plugins_list())
            if len(parts) == 2 and parts[1] in {'on', 'off'}:
                plugin = parts[0]
                meta = plugins.get_plugin_meta(plugin) if plugin in names else None
                if not meta or meta.always_enabled or plugin in {'_commands', 'discord'}:
                    raise ValueError('That plugin cannot be changed here.')
                if context.is_running():
                    raise ValueError('Stop the active run before changing plugins.')
                plugins.toggle_plugin(plugin, parts[1] == 'on')
                await self.reply(context, f'{meta.title}: {parts[1]}.')
                return
            rows, label = _page(names, parts[1] if len(parts) == 2 and parts[0] == 'page' else (args or '1'))
            await self.reply(context, 'Installed plugins (instance-wide)\n\n' + '\n'.join(
                f"{plugin}: {plugins.get_toggle_state(plugin)}" for plugin in rows
            ) + f'\n\n{label}. /plugins page <number>\nChange one with /plugins <name> on|off. Required plugins and this connection remain protected.')
            return
        if context.config.profile == 'default':
            raise ValueError('The Default utility profile has no editable permissions. Use /profile first.')
        policy = tool_policy.get_policy(context.agent0)
        catalog = tool_policy.get_tool_catalog(context.agent0)
        if parts and parts[0] not in {'page'}:
            if context.is_running():
                raise ValueError('Stop the active run before changing permissions.')
            if parts == ['inherit']:
                policy['mode'] = 'inherit'
            elif len(parts) == 2 and parts[0] in {'default', 'mcp_default'} and parts[1] in {'allow', 'block'}:
                policy.update(mode='custom')
                policy[parts[0]] = parts[1]
            elif len(parts) == 2 and parts[1] in {'allow', 'block', 'default'}:
                item = next((item for item in catalog if item['id'] == parts[0]), None)
                if not item:
                    raise ValueError('Use a canonical tool ID listed by /permissions.')
                policy['mode'] = 'custom'
                for field in ('allowed', 'blocked'):
                    policy[field] = [id for id in policy[field] if id != item['id']]
                if parts[1] != 'default':
                    policy['allowed' if parts[1] == 'allow' else 'blocked'].append(item['id'])
            else:
                raise ValueError('Use /permissions <tool ID> allow|block|default, /permissions default|mcp_default allow|block, or /permissions inherit.')
            from plugins._agent_editor.helpers import editor
            editor.apply_change_plan(editor.build_change_plan({'profile_id': context.config.profile, 'tool_policy': policy}, context))
            await self.reply(context, 'Tool permissions updated.')
            return
        rows, label = _page(catalog, parts[1] if len(parts) == 2 else '')
        await self.reply(context, f"Tool permissions: {context.config.profile}\nScope: {projects.get_context_project_name(context) or 'Global'}\n\n" + '\n'.join(
            f"{item['id']}: {'allow' if tool_policy.resolve_tool(context.agent0, item['name'], canonical_id=item['id'], _policy=policy).allowed else 'block'}" for item in rows
        ) + f'\n\n{label}. /permissions page <number>\n/permissions <tool ID> allow|block|default\n/permissions default|mcp_default allow|block\n/permissions inherit')

    async def compact(self, context, args):
        from plugins._chat_compaction.helpers.compactor import MIN_COMPACTION_TOKENS, get_compaction_stats
        if '_chat_compaction' not in plugins.get_enabled_plugins(context.agent0):
            raise ValueError('Chat Compaction is disabled for this chat.')
        if context.is_running():
            raise ValueError('Stop the active run before compacting.')
        stats = await get_compaction_stats(context)
        if stats['token_count'] < MIN_COMPACTION_TOKENS:
            raise ValueError(f'Not enough content to compact (minimum {MIN_COMPACTION_TOKENS:,} tokens).')
        if args == f'confirm {context.id}':
            await self.reply(context, 'Compacting chat…')
            await self._compact(context)
        elif not args:
            await self.reply(context, f"Compact {stats['message_count']} messages (~{stats['token_count']:,} tokens)? The original conversation will be backed up.\n\nConfirm with /compact confirm {context.id}")
        else:
            raise ValueError('Send /compact again to get a confirmation for the current chat.')

    async def _compact(self, context):
        from plugins._chat_compaction.helpers.compactor import run_compaction
        try:
            await context.run_task(run_compaction, context).result()
            await self.reply(context, 'Chat compacted. The original conversation was backed up.')
        except Exception:
            logger.exception('Discord compaction failed')
            await self.reply(context, 'Compaction failed. Check the Agent Zero logs.')


    async def export_transcript(self, context):
        from helpers.history import output_text
        text = output_text(context.agent0.history.output(), ai_label='assistant', human_label='user')
        if not text:
            await self.reply(context, 'This chat has no transcript yet.')
            return
        file = discord.File(io.BytesIO(text.encode('utf-8')), filename='transcript.txt')
        try:
            await self.message.channel.send(file=file, allowed_mentions=discord.AllowedMentions.none())
        finally:
            file.close()
