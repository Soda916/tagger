"""Discord Modal 表單與 View 按鈕介面。"""

from __future__ import annotations

import logging
import discord
from discord import ui

from cogs.tagger.core import TagRuntime

LOGGER = logging.getLogger(__name__)


class TagModal(ui.Modal, title="自訂標籤身份組"):
    """彈出表單包含「身份組名稱」與「顏色」兩個欄位。"""

    role_name = ui.TextInput(
        label="身份組名稱",
        placeholder="請輸入身份組名稱（最多 32 字）",
        min_length=1,
        max_length=32,
        required=True,
    )

    role_color = ui.TextInput(
        label="顏色 (HEX 或 色碼名稱)",
        placeholder="例如：#FF5733、0x00FF00 或 blue",
        min_length=1,
        max_length=20,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ 此功能僅限在伺服器（Guild）中使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        success, msg, _ = await TagRuntime.apply_tag(
            guild=interaction.guild,
            member=interaction.user,
            role_name=self.role_name.value,
            color_input=self.role_color.value,
        )

        await interaction.followup.send(msg, ephemeral=True)


class TagButtonView(ui.View):
    """持久性（Persistent）按鈕 View，允許使用者點擊後開啟 Modal 表單或刪除標籤。"""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="🏷️ 設定標籤身份組",
        style=discord.ButtonStyle.primary,
        custom_id="tagger:set_tag_btn",
    )
    async def set_tag_btn(
        self,
        interaction: discord.Interaction,
        _: ui.Button,
    ) -> None:
        await interaction.response.send_modal(TagModal())

    @ui.button(
        label="🗑️ 移除標籤身份組",
        style=discord.ButtonStyle.danger,
        custom_id="tagger:remove_tag_btn",
    )
    async def remove_tag_btn(
        self,
        interaction: discord.Interaction,
        _: ui.Button,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ 此功能僅限在伺服器（Guild）中使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        success, msg = await TagRuntime.remove_tag(interaction.guild, interaction.user)
        await interaction.followup.send(msg, ephemeral=True)
