"""Discord 斜線指令 (Slash Commands) Cog。"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.tagger.core import GuildTagDB, TagRuntime
from cogs.tagger.modal import TagButtonView

LOGGER = logging.getLogger(__name__)


class TaggerSlashCog(commands.Cog):
    """提供標籤機相關斜線指令。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="tag_setup", description="設定標籤機觸發頻道與觸發模式（管理員權限）")
    @app_commands.rename(channel="專屬頻道", mode="觸發模式")
    @app_commands.describe(
        channel="設定標籤機服務專屬頻道",
        mode="選擇觸發方式（直接對話/Modal表單按鈕/斜線指令/全部）",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="💬 直接對話模式 (於頻道免打關鍵字，直接輸入名稱與顏色)", value="message"),
            app_commands.Choice(name="📋 Modal 表單面板模式 (按鈕跳出表單)", value="modal"),
            app_commands.Choice(name="⚡ 斜線指令模式 (/tag 指令)", value="slash"),
            app_commands.Choice(name="🌟 全部啟用 (支援對話、表單與斜線指令)", value="all"),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def tag_setup_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        mode: app_commands.Choice[str],
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ 此指令僅限在伺服器中使用。", ephemeral=True)
            return

        is_admin = (
            interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.manage_roles
        )
        if not is_admin:
            await interaction.response.send_message("❌ 您需要管理員權限或管理身份組權限才能設定標籤機。", ephemeral=True)
            return

        db = GuildTagDB(interaction.guild.id)
        db.set_setting("tag_channel_id", str(channel.id))
        db.set_setting("trigger_mode", mode.value)

        mode_names = {
            "message": "💬 直接對話模式（於專屬頻道輸入 `身份組名稱 顏色` 即可自動設定）",
            "modal": "📋 Modal 表單按鈕模式",
            "slash": "⚡ 斜線指令模式",
            "all": "🌟 全部模式（支援直接對話、Modal 按鈕與斜線指令）",
        }

        mode_text = mode_names.get(mode.value, mode.value)

        # 根據選取的模式於目標頻道發送說明的 Embed / 按鈕面板
        if mode.value in ("modal", "all"):
            embed = discord.Embed(
                title="🏷️ 自訂標籤身份組面板",
                description=(
                    "點擊下方按鈕即可跳出表單自訂您的專屬標籤身份組名稱與顏色！\n\n"
                    "- 每人於本伺服器限擁有一個標籤身份組。\n"
                    "- 重複輸入將自動更新您現有的標籤。\n"
                    f"- 直接在頻道輸入 `名稱 顏色`（例如 `#FF5733 VIP`）亦可發動設定。" if mode.value == "all" else ""
                ),
                color=discord.Color.blue(),
            )
            embed.set_footer(text="Tagger Bot • 標籤機服務")
            view = TagButtonView()
            await channel.send(embed=embed, view=view)

        elif mode.value == "message":
            embed = discord.Embed(
                title="🏷️ 標籤身份組專屬頻道",
                description=(
                    "本頻道為標籤身份組專屬頻道！\n\n"
                    "直接在頻道中傳送：\n"
                    "👉 **`身份組名稱 顏色`** （例如：`VIP #FF5733` 或 `黑金組 red`）\n"
                    "👉 **`顏色 身份組名稱`** （例如：`#FF5733 VIP`）\n\n"
                    "無需輸入「標籤」或前綴指令，即可自動為您設定專屬身份組與顏色！"
                ),
                color=discord.Color.green(),
            )
            embed.set_footer(text="Tagger Bot • 標籤機服務")
            await channel.send(embed=embed)

        await interaction.response.send_message(
            f"✅ **標籤機設定成功！**\n"
            f"- **專屬頻道**: {channel.mention}\n"
            f"- **觸發模式**: {mode_text}",
            ephemeral=True,
        )

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

        db = GuildTagDB(interaction.guild.id)
        cfg = db.get_config()

        # 檢查頻道限制
        if cfg["tag_channel_id"] and interaction.channel_id != cfg["tag_channel_id"]:
            target_chan = interaction.guild.get_channel(cfg["tag_channel_id"])
            chan_mention = target_chan.mention if target_chan else f"<#{cfg['tag_channel_id']}>"
            await interaction.response.send_message(
                f"⚠️ 請至指定的標籤頻道 {chan_mention} 使用標籤服務。",
                ephemeral=True,
            )
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

    @app_commands.command(name="tag_panel", description="手動發送標籤設定按鈕面板（需要管理權限）")
    @app_commands.default_permissions(manage_roles=True)
    async def tag_panel_cmd(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ 此指令僅限在伺服器中使用。", ephemeral=True)
            return

        is_admin = (
            interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.manage_roles
        )
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
