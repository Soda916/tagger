"""Hot deploy 指令：在私訊執行 git pull 並重載 cogs。"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Iterable, List

import discord
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
COGS_DIR = BASE_DIR / "cogs"


class Deploy(commands.Cog):
    """提供 /hotdeploy 指令，讓 bot owner 遠端更新與重載專案。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.owner_id = int(os.getenv("OWNER_ID", "0"))
        self.deploy_hash = os.getenv("DEPLOY_HASH", "")
        self._lock = asyncio.Lock()

    def _is_owner(self, user_id: int) -> bool:
        return self.owner_id > 0 and user_id == self.owner_id

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(BASE_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode().strip(), stderr.decode().strip()

    async def _reload_extensions(self, extensions: Iterable[str]) -> List[str]:
        reloaded: List[str] = []
        for ext in extensions:
            if ext in self.bot.extensions:
                await self.bot.reload_extension(ext)
            else:
                await self.bot.load_extension(ext)
            reloaded.append(ext)
        return reloaded

    @app_commands.command(name="hotdeploy", description="git pull 並重新載入 cogs (限私訊與 Bot Owner)")
    @app_commands.rename(hash_value="雜湊")
    @app_commands.describe(hash_value="部署密碼雜湊")
    async def deploy(self, interaction: discord.Interaction, hash_value: str) -> None:
        if interaction.user is None or not self._is_owner(interaction.user.id):
            await interaction.response.send_message("只有 bot owner 可以使用這個指令。", ephemeral=True)
            return

        if interaction.guild is not None:
            await interaction.response.send_message("這個指令只允許在私訊中使用。", ephemeral=True)
            return

        if not self.deploy_hash:
            await interaction.response.send_message("`DEPLOY_HASH` 尚未設定在 .env，無法執行部署。", ephemeral=True)
            return

        if hash_value != self.deploy_hash:
            await interaction.response.send_message("雜湊驗證失敗。", ephemeral=True)
            return

        async with self._lock:
            await interaction.response.send_message(
                "🚀 開始更新：執行 `git pull --ff-only` 並重新載入 cogs...",
                ephemeral=True,
            )

            old_code, old_rev, old_err = await self._run_git("rev-parse", "HEAD")
            if old_code != 0:
                await interaction.followup.send(f"❌ `git rev-parse HEAD` 失敗：```text\n{old_err or old_rev}\n```", ephemeral=True)
                return

            pull_code, pull_out, pull_err = await self._run_git("pull", "--ff-only")
            if pull_code != 0:
                await interaction.followup.send(f"❌ `git pull --ff-only` 失敗：```text\n{pull_err or pull_out}\n```", ephemeral=True)
                return

            new_code, new_rev, new_err = await self._run_git("rev-parse", "HEAD")

            # 重新載入所有 cogs
            modules = []

            def find_extensions(directory: Path):
                for path in sorted(directory.iterdir()):
                    if path.name.startswith("_") or path.name.startswith("."):
                        continue
                    if path.is_dir():
                        if (path / "__init__.py").exists():
                            rel_path = path.relative_to(COGS_DIR.parent)
                            modules.append(".".join(rel_path.parts))
                        else:
                            find_extensions(path)
                    elif path.is_file() and path.suffix == ".py":
                        if path.stem == "__init__":
                            continue
                        rel_path = path.with_suffix("").relative_to(COGS_DIR.parent)
                        modules.append(".".join(rel_path.parts))

            find_extensions(COGS_DIR)
            reloaded = await self._reload_extensions(modules)
            await self.bot.tree.sync()

            msg = (
                f"✅ **部署成功！**\n"
                f"- **舊 Commit**: `{old_rev[:7]}`\n"
                f"- **新 Commit**: `{new_rev[:7]}`\n"
                f"- **已重新載入模組**: {', '.join(reloaded)}"
            )
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Deploy(bot))
