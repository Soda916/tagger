"""直接對話訊息 (Message Listener & Prefix-less Matcher) Cog。"""

from __future__ import annotations

import logging
import re
import discord
from discord.ext import commands

from cogs.tagger.core import GuildTagDB, TagRuntime, parse_color

LOGGER = logging.getLogger(__name__)

# 支援前綴的傳統格式（如 !tag VIP #FF5733 或 標籤 VIP red）
PATTERN_PREFIX = re.compile(
    r"^(?:!|/)?(?:tag|標籤)\s+(?:名稱[：:])?\s*(?P<rest>.+)$",
    re.IGNORECASE,
)


def extract_name_and_color(text: str) -> tuple[str | None, str | None]:
    """從對話文字中解析「身份組名稱」與「顏色」（支援免前綴、顏色在前後、多字名稱）。"""
    cleaned = text.strip()
    if not cleaned:
        return None, None

    # 處理 Key-Value 格式（例如 名稱:VIP 顏色:#FF5733 或 標籤 名稱:管理員 顏色:blue）
    kv_match = re.search(r"名稱[：:]\s*([^\s]+).*?顏色[：:]\s*([^\s]+)", cleaned)
    if kv_match:
        return kv_match.group(1), kv_match.group(2)

    # 檢查是否有標籤前綴 (!tag 或 標籤)
    prefix_match = PATTERN_PREFIX.match(cleaned)
    if prefix_match:
        cleaned = prefix_match.group("rest").strip()

    parts = cleaned.split()
    if len(parts) < 2:
        return None, None

    # 情況 1：最後一個詞為顏色（例如 "VIP #FF5733" 或 "超級 貴賓組 red"）
    last_word = parts[-1]
    color_obj, _ = parse_color(last_word)
    if color_obj is not None:
        role_name = " ".join(parts[:-1])
        return role_name, last_word

    # 情況 2：第一個詞為顏色（例如 "#FF5733 VIP" 或 "red 超級 貴賓組"）
    first_word = parts[0]
    color_obj, _ = parse_color(first_word)
    if color_obj is not None:
        role_name = " ".join(parts[1:])
        return role_name, first_word

    return None, None


class TaggerMessageCog(commands.Cog):
    """處理專屬頻道直接輸入「名稱 顏色」的 Message Listener。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # 忽略 Bot 本身或私訊
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return

        db = GuildTagDB(message.guild.id)
        cfg = db.get_config()

        target_channel_id = cfg["tag_channel_id"]
        trigger_mode = cfg["trigger_mode"]

        # 1. 若伺服器已指定標籤專屬頻道，僅在此頻道內響應對話
        if target_channel_id and message.channel.id != target_channel_id:
            return

        # 2. 檢查觸發模式是否允許對話觸發 (message 或 all)
        if trigger_mode not in ("message", "all") and target_channel_id:
            return

        role_name, color_input = extract_name_and_color(message.content)
        if not role_name or not color_input:
            return

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
