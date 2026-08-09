"""Discord 斜線指令 (Slash Commands) Cog。"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.tagger.core import TagRuntime
from cogs.tagger.modal import TagButtonView

LOGGER = logging.getLogger(__name__)


class TaggerSlashCog(commands.Cog):
    """提供標籤機相關斜線指令。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="tag", description="直接透過斜線指令設定專屬標籤身份組")
    @app_commands.rename(name="身份組名稱", color="顏色")
    @app_commands.describe(
        name="身份組名稱（最多 32 字）",
        color="顏色 HEX 色碼（例如：#FF5733、0x00FF00 或 blue）",
    )
    async def tag_cmd(
        self,
        interaction: discord.Interaction,
        name: str,
        color: str,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ 此指令僅限在伺服器中使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        success, msg, _ = await TagRuntime.apply_tag(
            guild=interaction.guild,
            member=interaction.user,
            role_name=name,
            color_input=color,
        )

        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="untag", description="移除您的專屬標籤身份組")
    async def untag_cmd(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ 此指令僅限在伺服器中使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        success, msg = await TagRuntime.remove_tag(interaction.guild, interaction.user)
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="tag_panel", description="發送標籤設定按鈕面板（需要管理權限）")
    @app_commands.default_permissions(manage_roles=True)
    async def tag_panel_cmd(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ 此指令僅限在伺服器中使用。", ephemeral=True)
            return

        is_admin = interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_roles
        if not is_admin:
            await interaction.response.send_message("❌ 您需要管理權限或管理身份組權限才能發送面板。", ephemeral=True)
            return

        embed = discord.Embed(
            title="🏷️ 自訂標籤身份組面板",
            description="點擊下方按鈕即可跳出表單自訂您的專屬標籤身份組名稱與顏色！\n\n- 每人於本伺服器限擁有一個標籤身份組。\n- 重複輸入將自動更新您現有的標籤。",
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Tagger Bot • 標籤機服務")

        view = TagButtonView()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ 已成功發送標籤按鈕面板！", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TaggerSlashCog(bot))
