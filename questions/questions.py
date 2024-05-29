from __future__ import annotations

import asyncio
import copy
from datetime import datetime
from typing import TYPE_CHECKING, Union, Optional, cast

import discord
from discord.channel import CategoryChannel
from discord.ext import commands

from core import checks
from core.models import DummyMessage, PermissionLevel, getLogger

if TYPE_CHECKING:
    from bot import ModmailBot
    from core.thread import Thread

logger = getLogger(__name__)


class Questions(commands.Cog):
    """Reaction-based menu for threads"""

    def __init__(self, bot: ModmailBot):
        self.bot = bot
        self.db = self.bot.plugin_db.get_partition(self)

    async def wait_for_channel_response(self, channel: discord.TextChannel,
                                        member: discord.Member, *, timeout: int = 1800) -> discord.Message:
        return await self.bot.wait_for('message',
                                       check=lambda m: m.channel == channel and m.author == member,
                                       timeout=timeout)

    async def wait_for_dm_response(self, user: discord.User, *, timeout: int = 1800) -> discord.Message:
        return await self.bot.wait_for('message',
                                       check=lambda m: isinstance(m.channel, discord.DMChannel) and m.author == user,
                                       timeout=timeout)

    @commands.Cog.listener()
    async def on_thread_ready(self, thread: Thread,
                              creator: Union[discord.Member, discord.User, None],
                              category: Optional[discord.CategoryChannel],
                              initial_message: Optional[discord.Message]):
        """Sends out menu to user"""
        config = await self.db.find_one({'_id': 'config'}) or {}
        responses = {}

        if not config.get('questions'):  # no questions set up
            return

        q_message = cast(discord.Message, DummyMessage(copy.copy(initial_message)))
        q_message.author = self.bot.modmail_guild.me
        m = None

        if config.get('intro'):  # no intro set up
            q_message.content = config.get('intro')
            await thread.reply(q_message)

        for question in config['questions']:
            q_message.content = question
            await thread.reply(q_message)

            try:
                m = await self.wait_for_dm_response(thread.recipient, timeout=1800)  # 30m
            except asyncio.TimeoutError:
                await thread.close(closer=self.bot.modmail_guild.me,
                                   message='Closed due to inactivity and not responding to questions.')
                return
            else:
                answer = m.content if m.content.strip() else "<No Message Content>"
                if len(m.attachments) > 0:
                    answer += "\n"
                    for attachment in m.attachments:
                        answer += f"\n`{attachment.filename}`: {attachment.url}"

                responses[question] = answer

        await asyncio.sleep(1)
        embed = discord.Embed(color=self.bot.main_color, timestamp=datetime.utcnow())
        for k, v in responses.items():
            embed.add_field(name=k, value=v, inline=False)
        embed.set_author(name=m.author.name, icon_url=m.author.get("avatar", {}).url)
        message = await thread.channel.send(embed=embed)
        await message.pin()

        if config.get('outro'):  # no outro set up
            q_message.content = config.get('outro')
            await thread.reply(q_message)

        move_to = self.bot.get_channel(int(config['move_to']))
        if move_to is None:
            logger.warning("Move-to category does not exist. Not moving.")
        else:
            await thread.channel.edit(category=move_to, sync_permissions=True)

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @commands.command()
    async def configquestions(self, ctx, *, move_to: CategoryChannel):
        """Configures the questions plugin.

        `move_to` should be a category to move to after questions answered.
        Initial category should be defined in `main_category_id`.
        """
        questions = []
        await ctx.send('How many questions do you have?')
        try:
            m = await self.wait_for_channel_response(ctx.channel, ctx.author)
        except asyncio.TimeoutError:
            return await ctx.send('Timed out.')
        try:
            count = int(m.content)
        except ValueError:
            return await ctx.send('Invalid input.')

        for i in range(1, count + 1):
            await ctx.send(f"What's question #{i}?")
            try:
                m = await self.wait_for_channel_response(ctx.channel, ctx.author)
            except asyncio.TimeoutError:
                return await ctx.send('Timed out.')
            if not m.content:
                return await ctx.send('Question must be text-only.')
            questions.append(m.content)

        await self.db.find_one_and_update({'_id': 'config'},
                                          {'$set': {'questions': questions, 'move_to': str(move_to.id)}}, upsert=True)
        await ctx.send('Saved')

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @commands.command()
    async def configoutro(self, ctx, *, move_to: CategoryChannel):
        "Configures the outro."
        await ctx.send('Type the outro you want')
        try:
            m = await self.wait_for_channel_response(ctx.channel, ctx.author)
        except asyncio.TimeoutError:
            return await ctx.send('Timed out.')
        if not m.content:
            return await ctx.send('Outro must be text-only.')
        outro = m.content

        await self.db.find_one_and_update({'_id': 'config'},
                                          {'$set': {'outro': outro, 'move_to': str(move_to.id)}}, upsert=True)
        await ctx.send('Saved')

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @commands.command()
    async def configintro(self, ctx, *, move_to: CategoryChannel):
        "Configures the intro."
        await ctx.send('Type the intro you want')
        try:
            m = await self.wait_for_channel_response(ctx.channel, ctx.author)
        except asyncio.TimeoutError:
            return await ctx.send('Timed out.')
        if not m.content:
            return await ctx.send('Intro must be text-only.')
        intro = m.content

        await self.db.find_one_and_update({'_id': 'config'},
                                          {'$set': {'intro': intro, 'move_to': str(move_to.id)}}, upsert=True)
        await ctx.send('Saved')

async def setup(bot: ModmailBot) -> None:
    await bot.add_cog(Questions(bot))
