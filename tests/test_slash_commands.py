"""Run with framework Python: -m usr.plugins.discord.tests.test_slash_commands."""
import asyncio
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from agent import AgentContext
from helpers import persist_chat
from plugins._commands.helpers import commands
from usr.plugins.discord.helpers import discord_bot as bridge
from usr.plugins.discord.helpers.slash_commands import DiscordCommands


async def main():
    bot = bridge.ChatBridgeBot('test-token', 'support')
    bot._connection.user = SimpleNamespace(id=123)
    config = {'bot': {'enabled': True}, 'servers': [789], 'chat_bridge': {
        'allowed_users': [456], 'default_agent_profile': 'developer'}}
    channel = SimpleNamespace(id=101, name='slash-test', typing=nullcontext, send=AsyncMock())
    message = SimpleNamespace(id=1, content='<@123> /goal status', channel=channel,
        guild=SimpleNamespace(id=789), reference=None, attachments=[],
        author=SimpleNamespace(id=456, bot=False, name='Tester', display_name='Tester'))
    existing = {ctx.id for ctx in AgentContext.all()}
    try:
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(bridge, '_get_state_path', return_value=Path(tmp) / 'state.json'), \
             patch.object(persist_chat, 'CHATS_FOLDER', tmp), \
             patch.object(bot, '_get_config', return_value=config), \
             patch.object(bot, '_get_agent_response', new_callable=AsyncMock) as restricted, \
             patch.object(bot, '_get_full_agent_response', new_callable=AsyncMock, return_value='done') as agent:
            # Even native commands and custom scripts must pass existing access checks.
            with patch.object(commands, 'resolve_command_invocation', new_callable=AsyncMock) as resolve:
                await bot.on_message(message)
                resolve.assert_not_awaited()
                assert 'Web UI approval' in channel.send.call_args.args[0]
                bridge.set_access_approval('support', '789:456:101', 'approve', config, duration=0)
                message.author.id = 999
                message.id += 1
                await bot.on_message(message, command_invocation=True)
                resolve.assert_not_awaited()
                message.author.id = 456
                message.guild.id = 999
                await bot.on_message(message, command_invocation=True)
                resolve.assert_not_awaited()
                message.guild.id = 789
            message.id += 1
            ctx = bot._get_bridge_context('101', message)
            adapter = DiscordCommands(bot, message)
            assert ctx.data['discord_bot_id'] == 'support' and ctx.data['discord_channel_id'] == '101'

            async def send(text):
                message.id += 1
                message.content = '<@123> ' + text
                bot._rate_limits.clear()
                channel.send.reset_mock()
                await bot.on_message(message)
                return '\n'.join(str(call.args[0]) for call in channel.send.call_args_list if call.args)

            assert 'Commands for this chat' in await send('/commands')
            assert 'Unknown command' in await send('/not-a-real-command')
            assert 'Unknown command' in await send('/')
            with patch.object(ctx, 'is_running', return_value=True):
                assert 'Stop the active run' in await send('/profile New instructions')
            assert 'goal' in (await send('/goal status')).lower()
            restricted.assert_not_awaited()
            agent.assert_not_awaited()
            # /stop is processed while a normal model turn owns the channel lock.
            lock = bot._channel_locks.setdefault('101', asyncio.Lock())
            await lock.acquire()
            try:
                output = await asyncio.wait_for(send('/stop'), 5)
                assert output
            finally:
                lock.release()
            await send('/new')
            new_id = bridge.get_context_id('101', 'support')
            assert new_id != ctx.id and bridge.get_context_id('101', 'default') is None
            assert ctx.id in await send('/sessions')
            other = AgentContext(ctx.config, name='Other channel')
            other.data.update(discord_bot_id='support', discord_channel_id='202')
            assert 'Choose a chat' in await send('/chat ' + other.id)
            other.data.update(discord_bot_id='another-bot', discord_channel_id='101')
            assert 'Choose a chat' in await send('/chat ' + other.id)
            await send('/chat ' + ctx.id)
            assert bridge.get_context_id('101', 'support') == ctx.id

            # Project/plugin overrides win, preserve postfix arguments, and execute once.
            custom = {'name': 'status', 'path': '/test/status.md', 'source_scope_key': 'project'}
            with patch.object(commands, 'list_context_commands', return_value=[custom]), \
                 patch.object(commands, 'resolve_command_invocation', new_callable=AsyncMock,
                              return_value={'result': {'text': '/goal status', 'effects': []}}) as resolve:
                await send('details /status')
                assert resolve.call_args.kwargs['slash_text'] == '/status details'
                assert resolve.call_args.kwargs['context_id'] == ctx.id
                assert agent.call_args.kwargs['resolved_command'] is True
                await bot.on_message(message)
                assert resolve.await_count == 1, 'Duplicate delivery repeated a script'
                custom['name'] = 'commands'
                await send('/commands')
                assert resolve.await_count == 2, 'Custom help was shadowed by built-in menu'

            # Rendered local prompts remain intact and cannot resolve at either edge again.
            task = SimpleNamespace(result=AsyncMock(return_value='ok'))
            with patch.object(AgentContext, 'communicate', return_value=task) as communicate, \
                 patch('helpers.message_queue.log_user_message'):
                raw = '/goal create ' + ('long prompt ' * 1000) + '\n/status'
                await bridge.ChatBridgeBot._get_full_agent_response(bot, '101', raw, message,
                                                                resolved_command=True, context=ctx)
                forwarded = communicate.call_args.args[0].message
                assert raw in forwarded
                assert not commands.parse_slash_invocation(forwarded)['command_name']

            # Menus/effects use Discord-safe output and canonical settings writers.
            channel.send.reset_mock()
            await adapter.apply_result(ctx, 'custom', {'effects': [{'type': 'toast', 'message': '@everyone'}]})
            assert not channel.send.call_args.kwargs['allowed_mentions'].everyone
            await adapter.apply_result(ctx, 'attach', {'effects': [{'type': 'attach_files'}]})
            await adapter.apply_result(ctx, 'copy', {'effects': [{'type': 'copy_transcript'}]})
            assert channel.send.call_args.kwargs.get('file') or 'transcript' in channel.send.call_args.args[0]
            with patch('helpers.plugins.toggle_plugin') as toggle:
                for name in ('discord', '_commands'):
                    try:
                        await adapter.settings_menu(ctx, 'plugins', name + ' off')
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('Connection and commands must stay protected')
                toggle.assert_not_called()

            # Register only /a0, leaving any other application commands intact.
            with patch.object(bot.http, 'upsert_global_command', new_callable=AsyncMock) as upsert:
                await bot.setup_hook()
                assert bot.commands_registered
                payload = upsert.call_args.kwargs['payload']
                assert payload['name'] == 'a0' and payload['options'][0]['autocomplete']
            interaction = SimpleNamespace(id=9999, channel_id=101, channel=channel,
                user=message.author, guild=message.guild,
                response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            native = bot.command_tree.get_command('a0')
            bot._rate_limits.clear()
            await native.callback(interaction, 'goal status')
            interaction.response.defer.assert_awaited_once_with(thinking=True, ephemeral=True)
            assert interaction.followup.send.await_count
            assert interaction.followup.send.call_args.kwargs['ephemeral']
            choices = await native._params['command'].autocomplete(interaction, 'goal')
            assert any(item.value == 'goal' for item in choices)
            interaction.user.id = 999
            assert await native._params['command'].autocomplete(interaction, '') == []
            await native.callback(interaction, 'stop')
            interaction.response.send_message.assert_awaited_once()
            restricted.assert_not_awaited()
    finally:
        for context in AgentContext.all():
            if context.id not in existing:
                AgentContext.remove(context.id)
    print('PASS: Discord commands, approval, stop, overrides, deduplication, session isolation, effects and native autocomplete')


if __name__ == '__main__':
    asyncio.run(main())
