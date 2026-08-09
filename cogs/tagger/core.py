"""Tagger Core Runtime & Database Manager per Guild."""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import discord

LOGGER = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def get_guild_db_path(guild_id: int) -> Path:
    """取得特定 Guild 的 SQLite 資料庫檔案路徑。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f"{guild_id}.db"


class GuildTagDB:
    """單一 Guild 的 SQLite 資料庫管理器。"""

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        self.db_path = get_guild_db_path(guild_id)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_tags (
                    user_id INTEGER PRIMARY KEY,
                    role_id INTEGER NOT NULL,
                    role_name TEXT NOT NULL,
                    color_hex TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM guild_settings WHERE key = ?",
                (key,),
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO guild_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )
            conn.commit()

    def get_config(self) -> dict:
        channel_id = self.get_setting("tag_channel_id")
        trigger_mode = self.get_setting("trigger_mode", "all")
        return {
            "tag_channel_id": int(channel_id) if channel_id and channel_id.isdigit() else None,
            "trigger_mode": trigger_mode,
        }

    def get_user_tag(self, user_id: int) -> Optional[dict]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT user_id, role_id, role_name, color_hex, created_at, updated_at FROM user_tags WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None

    def set_user_tag(self, user_id: int, role_id: int, role_name: str, color_hex: str) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO user_tags (user_id, role_id, role_name, color_hex, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    role_id = excluded.role_id,
                    role_name = excluded.role_name,
                    color_hex = excluded.color_hex,
                    updated_at = excluded.updated_at
                """,
                (user_id, role_id, role_name, color_hex, now_str, now_str),
            )
            conn.commit()

    def delete_user_tag(self, user_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM user_tags WHERE user_id = ?", (user_id,))
            conn.commit()


def parse_color(color_input: str) -> Tuple[Optional[discord.Color], str]:
    """解析色碼字串（支援 #RRGGBB, RRGGBB, 0xRRGGBB 或英文顏色名稱）。"""
    cleaned = color_input.strip()
    
    # 十六進位色碼匹配
    match = re.search(r"(?:#|0x)?([0-9a-fA-F]{6})", cleaned)
    if match:
        hex_val = match.group(1)
        int_val = int(hex_val, 16)
        return discord.Color(int_val), f"#{hex_val.upper()}"

    # 簡單的 3 位數 hex (#RGB)
    match_short = re.search(r"#?([0-9a-fA-F]{3})$", cleaned)
    if match_short:
        hex_short = match_short.group(1)
        full_hex = "".join([c * 2 for c in hex_short])
        int_val = int(full_hex, 16)
        return discord.Color(int_val), f"#{full_hex.upper()}"

    # discord.Color 內建名稱支援
    color_map = {
        "red": discord.Color.red(),
        "blue": discord.Color.blue(),
        "green": discord.Color.green(),
        "yellow": discord.Color.gold(),
        "orange": discord.Color.orange(),
        "purple": discord.Color.purple(),
        "magenta": discord.Color.magenta(),
        "teal": discord.Color.teal(),
        "pink": discord.Color.from_rgb(255, 192, 203),
        "black": discord.Color.default(),
        "white": discord.Color.from_rgb(255, 255, 255),
        "cyan": discord.Color.from_rgb(0, 255, 255),
    }

    lower_name = cleaned.lower()
    if lower_name in color_map:
        c = color_map[lower_name]
        hex_str = f"#{c.value:06X}"
        return c, hex_str

    return None, ""


class TagRuntime:
    """處理核心標籤邏輯：向此服務丟入 (member, role_name, color)，負責 DB 管理與身份組變更。"""

    @staticmethod
    async def apply_tag(
        guild: discord.Guild,
        member: discord.Member,
        role_name: str,
        color_input: str,
    ) -> Tuple[bool, str, Optional[discord.Role]]:
        """向標籤機核心丟入請求，並傳回 (成功與否, 提示訊息, 身份組物件)。"""
        if not guild.me.guild_permissions.manage_roles:
            return False, "❌ 機器人缺乏「管理身份組」權限，無法調整標籤。", None

        color, hex_str = parse_color(color_input)
        if color is None:
            return False, f"❌ 無法的色彩格式：`{color_input}`。請輸入 HEX 色碼（例如：`#FF5733` 或 `FF5733`）。", None

        clean_role_name = role_name.strip()
        if not clean_role_name or len(clean_role_name) > 32:
            return False, "❌ 身份組名稱長度必須介於 1 到 32 個字元之間。", None

        db = GuildTagDB(guild.id)
        user_record = db.get_user_tag(member.id)
        target_role: Optional[discord.Role] = None

        try:
            if user_record:
                old_role_id = user_record["role_id"]
                existing_role = guild.get_role(old_role_id)

                if existing_role:
                    # 檢查機器人身分組階層是否能夠編輯該身分組
                    if existing_role >= guild.me.top_role:
                        return False, "❌ 機器人的身分組階層過低，無法編輯目標身分組。", None
                    
                    # 編輯現有身分組名稱與顏色
                    await existing_role.edit(
                        name=clean_role_name,
                        color=color,
                        reason=f"Tag update requested by {member.display_name} ({member.id})"
                    )
                    target_role = existing_role

                    if target_role not in member.roles:
                        await member.add_roles(target_role)
                else:
                    # 舊身分組已被刪除，重新建立
                    target_role = await guild.create_role(
                        name=clean_role_name,
                        color=color,
                        reason=f"Tag recreate requested by {member.display_name} ({member.id})"
                    )
                    await member.add_roles(target_role)
            else:
                # 建立新身分組
                target_role = await guild.create_role(
                    name=clean_role_name,
                    color=color,
                    reason=f"Tag create requested by {member.display_name} ({member.id})"
                )
                await member.add_roles(target_role)

            # 更新 DB 紀錄
            db.set_user_tag(member.id, target_role.id, clean_role_name, hex_str)
            return True, f"✅ 成功設置標籤身份組 **{clean_role_name}** ({hex_str})！", target_role

        except discord.Forbidden:
            return False, "❌ 權限不足：機器人權限階層過低或無法編輯該身份組。", None
        except discord.HTTPException as exc:
            LOGGER.exception("Failed to update role for user %s", member.id)
            return False, f"❌ 處理身份組時發生錯誤：{exc.message}", None
        except Exception as exc:
            LOGGER.exception("Unexpected error in apply_tag for user %s", member.id)
            return False, f"❌ 系統錯誤：{exc}", None

    @staticmethod
    async def remove_tag(
        guild: discord.Guild,
        member: discord.Member,
    ) -> Tuple[bool, str]:
        """移除使用者的專屬標籤身份組並清理 DB 紀錄。"""
        db = GuildTagDB(guild.id)
        user_record = db.get_user_tag(member.id)

        if not user_record:
            return False, "⚠️ 您目前沒有設定任何標籤身份組。"

        old_role_id = user_record["role_id"]
        existing_role = guild.get_role(old_role_id)

        try:
            if existing_role:
                if existing_role >= guild.me.top_role:
                    return False, "❌ 機器人的身分組階層過低，無法刪除該身分組。"
                await existing_role.delete(reason=f"Tag remove requested by {member.display_name}")

            db.delete_user_tag(member.id)
            return True, "✅ 已成功移除您的標籤身份組與資料紀錄。"
        except discord.Forbidden:
            return False, "❌ 權限不足，無法刪除標籤身份组。"
        except Exception as exc:
            LOGGER.exception("Failed to remove tag for user %s", member.id)
            return False, f"❌ 移除身份組時發生錯誤：{exc}"
