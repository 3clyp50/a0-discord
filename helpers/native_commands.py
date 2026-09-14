"""A native /a0 entry backed by the current chat's command catalog."""
from contextlib import nullcontext
from types import SimpleNamespace

import discord
from discord import app_commands


class InteractionChannel:
    def __init__(self, interaction):
        self.interaction = interaction
        self.id = interaction.channel_id
        self.name = getattr(interaction.channel, 'name', str(self.id))

    def typing(self):
        return nullcontext()

    async def send(self, content=None, **kwargs):
        kwargs.pop('reference', None)
        kwargs['allowed_mentions'] = discord.AllowedMentions.none()
        return await self.interaction.followup.send(content, ephemeral=True, wait=True, **kwargs)


def create_tree(bot):
    tree = app_commands.CommandTree(bot)

    @tree.command(name='a0', description='Run an Agent Zero command in this channel')
    @app_commands.describe(command='Command and arguments, for example: goal status or commands')
    async def a0(interaction: discord.Interaction, command: str):
        if not bot._allows_user(interaction.user, interaction.guild):
            await interaction.response.send_message('This bot is not enabled for you here.', ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        text = command.strip() or 'commands'
        message = SimpleNamespace(
            id=interaction.id, content=text if text.startswith('/') else '/' + text,
            author=interaction.user, guild=interaction.guild,
            channel=InteractionChannel(interaction), reference=None, attachments=[],
        )
        await bot.on_message(message, command_invocation=True)

    @a0.autocomplete('command')
    async def autocomplete(interaction: discord.Interaction, current: str):
        if not bot._allows_user(interaction.user, interaction.guild):
            return []
        if not bot._is_elevated(str(interaction.user.id), str(interaction.channel_id)):
            return [app_commands.Choice(name='commands — Help and authentication', value='commands')]
        from agent import AgentContext
        from helpers import integration_commands
        from plugins._commands.helpers import commands
        from usr.plugins.discord.helpers.discord_bot import get_context_id
        context = AgentContext.get(get_context_id(str(interaction.channel_id), bot.bot_id) or '')
        names = {item['name']: item.get('description', '') for item in commands.list_context_commands(context)}
        for item in integration_commands.COMMAND_REGISTRY:
            if integration_commands.resolve_command(item.name, integration='discord'):
                names.setdefault(item.name, item.description)
        names.update(sessions='Chats for this channel', chat='Select a chat from /sessions')
        query = current.lstrip('/').lower()
        return [app_commands.Choice(name=f'{name} — {description}'[:100], value=name)
                for name, description in sorted(names.items()) if query in name][:25]

    return tree
