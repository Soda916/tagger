"""直接對話訊息 (Message Listener & Regex Matcher) Cog。"""

from __future__ import annotations

import logging
import re
import discord
from discord.ext import commands

from cogs.tagger.core import TagRuntime

LOGGER = logging.getLogger(__name__)

# 正則表達式匹配模式：
# 1. !tag 名稱 顏色  或  標籤 名稱 顏色
# 2. 標籤：名稱 顏色：顏色
PATTERN_NAMED = re.compile(
    r"^(?:!|/)?(?:tag|標籤)\s+(?:名稱[：:])?\s*(?P<name>[^\s:#]+)\s+(?:顏色[：:])?\s*(?P<color>#[0-9a-fA-F]{3,6}|0x[0-9a-fA-F]{6}|[a-zA-Z0-9]+)$",
    re.IGNORECASE,
)

# 支援顏色在前或在後 (例如: 標籤 #FF5733 我的身份組)
PATTERN_COLOR_FIRST = re.compile(
    r"^(?:!|/)?(?:tag|標籤)\s+(?P<color>#[0-9a-fA-F]{3,6}|0x[0-9a-fA-F]{6})\s+(?P<name>[^\s:#]+)$",
    re.IGNORECASE,
)


class TaggerMessageCog(commands.Cog):
    """處理聊天頻道直接輸入指令的 Message Listener。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # 忽略 Bot 本身或私訊
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return

        content = message.content.strip()
        if not content:
            return

        role_name: str | None = None
        color_input: str | None = None

        match_named = PATTERN_NAMED.match(content)
        if match_named:
            role_name = match_named.group("name")
            color_input = match_named.group("color")
        else:
            match_color = PATTERN_COLOR_FIRST.match(content)
            if match_color:
                role_name = match_color.group("name")
                color_input = match_color.group("color")

        if role_name and color_input:
            async with message.channel.typing():
                success, response_msg, _ = await TagRuntime.apply_tag(
                    guild=message.guild,
                    member=message.author,
                    role_name=role_name,
                    color_input=color_input,
                )
                try:
                    await message.reply(response_msg, mention_author=True)
                except discord.HTTPException:
                    await message.channel.send(response_msg)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TaggerMessageCog(bot))
