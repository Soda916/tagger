import os
import asyncio
import logging
from pathlib import Path
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# 自動抓取 main.py 檔案所在目錄下的 .env 絕對路徑
env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN 沒有設定在 .env")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger(__name__)

STATE_KEY_LOG_RELAY_CHANNEL_ID = "log_relay_channel_id"
DEFAULT_LOG_RELAY_CHANNEL_ID = int(os.getenv("LOG_RELAY_CHANNEL_ID", "0") or "0")


def get_log_relay_channel_id() -> int:
    try:
        db_path = Path(__file__).resolve().parent / "data" / "bot_state.db"
        if not db_path.exists():
            return DEFAULT_LOG_RELAY_CHANNEL_ID
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key = ?",
                (STATE_KEY_LOG_RELAY_CHANNEL_ID,),
            ).fetchone()
            if row and row["value"]:
                return int(row["value"])
    except Exception:
        pass
    return DEFAULT_LOG_RELAY_CHANNEL_ID


intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class DiscordLogRelayHandler(logging.Handler):
    def __init__(self, bot: commands.Bot, channel_id: int) -> None:
        super().__init__(level=logging.INFO)
        self.bot = bot
        self.channel_id = channel_id
        self._sending = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.INFO or self.channel_id <= 0 or self._sending:
            return

        try:
            message = self.format(record)
            self.bot.loop.call_soon_threadsafe(
                self.bot.loop.create_task,
                self._send(message),
            )
        except Exception:
            pass

    async def _resolve_channel(self) -> Optional[discord.abc.Messageable]:
        if self.channel_id <= 0:
            return None
        channel = self.bot.get_channel(self.channel_id)
        if channel is not None:
            return channel
        try:
            fetched = await self.bot.fetch_channel(self.channel_id)
            if isinstance(fetched, discord.abc.Messageable):
                return fetched
        except Exception:
            return None
        return None

    async def _send(self, text: str) -> None:
        if not self.bot.is_ready():
            return

        channel = await self._resolve_channel()
        if channel is None:
            return

        payload = text[:1900]
        try:
            self._sending = True
            await channel.send(f"```log\n{payload}\n```")
        except Exception:
            pass
        finally:
            self._sending = False


class TaggerBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_relay_handler: Optional[DiscordLogRelayHandler] = None

    async def setup_hook(self):
        # 註冊 Persistent View (使得重新啟動後按鈕仍然有效)
        from cogs.tagger.modal import TagButtonView
        self.add_view(TagButtonView())

        # 動態載入 cogs 模組
        modules = []
        cogs_dir = Path("cogs")

        def find_extensions(directory: Path):
            for path in sorted(directory.iterdir()):
                if path.name.startswith("_") or path.name.startswith("."):
                    continue
                if path.is_dir():
                    if (path / "__init__.py").exists():
                        rel_path = path.relative_to(cogs_dir.parent)
                        modules.append(".".join(rel_path.parts))
                    else:
                        find_extensions(path)
                elif path.is_file() and path.suffix == ".py":
                    if path.stem == "__init__":
                        continue
                    rel_path = path.with_suffix("").relative_to(cogs_dir.parent)
                    modules.append(".".join(rel_path.parts))

        if cogs_dir.exists():
            find_extensions(cogs_dir)

        for module in modules:
            try:
                await self.load_extension(module)
                LOGGER.info("Loaded extension: %s", module)
            except Exception:
                LOGGER.exception("Failed to load extension: %s", module)

        await self.tree.sync()


bot = TaggerBot(
    command_prefix="!",
    intents=intents,
    owner_id=int(OWNER_ID) if OWNER_ID else None
)


@bot.tree.command(name="set_log_channel", description="設定系統 Log 日誌轉發頻道（需要管理權限）")
@app_commands.describe(channel="目標日誌頻道（若不填則預設為當前頻道）")
async def set_log_channel(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel] = None,
) -> None:
    is_owner = OWNER_ID and str(interaction.user.id) == str(OWNER_ID)
    is_admin = interaction.user.guild_permissions.administrator if interaction.guild else False
    if not (is_owner or is_admin):
        await interaction.response.send_message("❌ 你沒有權限設定日誌頻道。", ephemeral=True)
        return

    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("❌ 請選擇有效的文字頻道。", ephemeral=True)
        return

    try:
        data_dir = Path(__file__).resolve().parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "bot_state.db"
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                """
                INSERT INTO bot_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (STATE_KEY_LOG_RELAY_CHANNEL_ID, str(target_channel.id)),
            )
            conn.commit()
    except Exception as exc:
        await interaction.response.send_message(f"❌ 儲存頻道設定失敗：{exc}", ephemeral=True)
        return

    if bot.log_relay_handler is not None:
        bot.log_relay_handler.channel_id = target_channel.id

    await interaction.response.send_message(
        f"✅ 已成功將系統日誌轉發頻道設定為：{target_channel.mention}",
        ephemeral=True,
    )


@bot.event
async def on_ready():
    if bot.log_relay_handler is None:
        relay_channel_id = get_log_relay_channel_id()
        if relay_channel_id > 0:
            relay_handler = DiscordLogRelayHandler(bot, relay_channel_id)
            relay_handler.setFormatter(
                logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
            )
            logging.getLogger().addHandler(relay_handler)
            bot.log_relay_handler = relay_handler
    LOGGER.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)


async def main():
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
