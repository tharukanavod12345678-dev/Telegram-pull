# app.py — Main Bot (Multi-User SaaS + Full Logic)
import asyncio
import builtins
import gc
import json
import logging
import os
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument
from telethon.tl.functions.channels import JoinChannelRequest, GetParticipantRequest
from telethon.errors import (
    FloodWaitError, AuthKeyUnregisteredError, SessionRevokedError, 
    AuthKeyDuplicatedError, ChatWriteForbiddenError
)
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

gc.set_threshold(20000, 25, 25)

API_ID    = int(os.environ.get("TG_API_ID", "30321244"))
API_HASH  = os.environ.get("TG_API_HASH", "4a877e997290766381a388f081cbefc9")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
ADMIN_ID  = int(os.environ.get("ADMIN_ID", "0"))

HOME_DIR = Path(__file__).resolve().parent
DB_FILE  = HOME_DIR / "users.db"
DL_DIR   = HOME_DIR / "_downloads"
DL_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ─── DATABASE ──────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, session TEXT, source TEXT, target INTEGER, last_id INTEGER DEFAULT 0, paused INTEGER DEFAULT 0, status TEXT DEFAULT 'idle')''')
    c.execute("UPDATE users SET status='idle', paused=0 WHERE status IN ('running', 'queued')")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def save_user(user_id, **kwargs):
    conn = sqlite3.connect(DB_FILE, timeout=15)
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
    if kwargs:
        set_clause = ", ".join([f"{k}=?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        c.execute(f"UPDATE users SET {set_clause} WHERE user_id=?", values)
    conn.commit()
    conn.close()

init_db()
task_queue = asyncio.Queue()

# ─── OTA UPDATE (Main Bot) ─────────────────────────────────
@dp.message(F.document & (F.from_user.id == ADMIN_ID))
async def handle_ota_update(message: types.Message):
    if not message.document.file_name.endswith(".zip"):
        return

    await message.reply("⬇️ Downloading update...")
    zip_path = HOME_DIR / "update.zip"
    await bot.download(message.document, destination=zip_path)

    if (HOME_DIR / "app.py").exists():
        shutil.copy(HOME_DIR / "app.py", HOME_DIR / "app.py.bak")

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.namelist():
                filename = os.path.basename(member)
                if not filename: continue
                source = zip_ref.open(member)
                target = open(HOME_DIR / filename, "wb")
                with source, target:
                    shutil.copyfileobj(source, target)
    except Exception as e:
        await message.reply(f"❌ Extract failed: {e}")
        return
    finally:
        try: zip_path.unlink()
        except: pass

    await message.reply("✅ Update applied. Restarting...")
    await asyncio.sleep(2)
    os._exit(1) 

# ─── BOT COMMANDS ──────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = get_user(message.from_user.id)
    if not user or not user["session"]:
        await message.reply("👋 **Welcome.**\n\nPlease login first:\n`/login 1BVts...`")
        return
    if user["status"] == "running":
        await message.reply("✅ **You are currently running.**\nCommands: /status /pause /resume /stop")
    elif user["status"] == "queued":
        await message.reply("⏳ **You are in the queue.** Please wait.")
    else:
        await message.reply("👋 **Ready.**\n\nTo start: `/pull <source> <target_id>`")

@dp.message(Command("login"))
async def cmd_login(message: types.Message):
    try:
        session_str = message.text.split(" ", 1)[1].strip()
        if not session_str.startswith("1BVts"):
            await message.reply("❌ Invalid format.")
            return
        
        await message.reply("🔄 Testing session...")
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            await message.reply("❌ Invalid session.")
            return
        me = await client.get_me()
        await client.disconnect()
        
        save_user(message.from_user.id, session=session_str, status="idle")
        await message.reply(f"✅ Logged in as {me.first_name}.")
    except Exception as e:
        await message.reply(f"❌ Error: `{e}`")

@dp.message(Command("pull"))
async def cmd_pull(message: types.Message):
    user = get_user(message.from_user.id)
    if not user or not user["session"]:
        await message.reply("❌ Login first.")
        return
    if user["status"] in ["running", "queued"]:
        await message.reply("⚠️ Task already running.")
        return
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.reply("Usage: `/pull <source> <target_id>`")
            return
        source = parts[1]
        target = int(parts[2])
        save_user(message.from_user.id, source=source, target=target, last_id=0, paused=0, status="queued")
        await message.reply("📥 Added to queue.")
        await task_queue.put(message.from_user.id)
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    user = get_user(message.from_user.id)
    if not user: return
    await message.reply(f"Status: **{user['status'].upper()}**\nResume ID: {user['last_id']}\nPaused: {user['paused']}")

@dp.message(Command("pause"))
async def cmd_pause(message: types.Message):
    user = get_user(message.from_user.id)
    if user and user["status"] == "running":
        save_user(message.from_user.id, paused=1)
        await message.reply("⏸ Paused.")

@dp.message(Command("resume"))
async def cmd_resume(message: types.Message):
    user = get_user(message.from_user.id)
    if user and user["status"] == "running":
        save_user(message.from_user.id, paused=0)
        await message.reply("▶️ Resumed.")

@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    user = get_user(message.from_user.id)
    if not user: return
    if user["status"] == "running":
        save_user(message.from_user.id, status="idle", paused=0)
        await message.reply("🛑 Stopping active task...")
    elif user["status"] == "queued":
        save_user(message.from_user.id, status="idle")
        await message.reply("🗑 Removed from queue.")

# ─── WORKER & SCAN LOGIC ───────────────────────────────────
async def worker():
    print("[Worker] Started...")
    while True:
        user_id = await task_queue.get()
        user = get_user(user_id)
        if not user or user["status"] != "queued":
            task_queue.task_done()
            continue

        save_user(user_id, status="running")
        await bot.send_message(user_id, "▶️ **Starting your task now...**")
        
        client = TelegramClient(StringSession(user["session"]), API_ID, API_HASH, connection_retries=5)
        
        try:
            await client.start()
            await run_scan(user_id, user, client)
        except Exception as e:
            await bot.send_message(user_id, f"❌ Task Error: `{e}`")
        finally:
            try: await client.disconnect()
            except: pass
            
            final_user = get_user(user_id)
            if final_user and final_user["status"] == "running":
                save_user(user_id, status="idle", paused=0)
                
            await bot.send_message(user_id, "✅ **Task finished.**")
            task_queue.task_done()

async def run_scan(user_id, user, client):
    source = user["source"]
    target = user["target"]
    last_id = user["last_id"]
    
    try:
        entity = await client.get_entity(source)
        target_entity = await client.get_entity(target)
        await client(GetParticipantRequest(target_entity, "me"))
        await client(JoinChannelRequest(entity))
    except ChatWriteForbiddenError:
        await bot.send_message(user_id, "❌ Write permission denied in target channel.")
        return
    except Exception as e:
        await bot.send_message(user_id, f"❌ Cannot resolve source/target: {e}")
        return

    await bot.send_message(user_id, f"🔍 Scanning: {getattr(entity, 'title', source)} from ID {last_id}...")
    iterator = client.iter_messages(entity, min_id=last_id, reverse=True)
    
    async for msg in iterator:
        u = get_user(user_id)
        if not u or u["status"] != "running":
            break
            
        if u["paused"]:
            await bot.send_message(user_id, "⏸ Paused. (Send /resume to continue)")
            while True:
                await asyncio.sleep(2)
                u_check = get_user(user_id)
                if not u_check or u_check["status"] != "running" or not u_check["paused"]:
                    break
            if not u_check or u_check["status"] != "running":
                break

        if isinstance(msg.media, MessageMediaDocument) and msg.media.document.mime_type.startswith("video/"):
            mb = msg.media.document.size // (1024*1024)
            if shutil.disk_usage(str(DL_DIR)).free // (1024*1024) < mb + 500:
                for f in DL_DIR.glob("*"):
                    try: f.unlink()
                    except: pass
            
            await bot.send_message(user_id, f"📥 Found video {msg.id} ({mb} MB). Downloading...")
            path = DL_DIR / f"{user_id}_{msg.id}.mp4"
            try:
                await client.download_media(msg, file=path)
                await bot.send_message(user_id, f"📤 Uploading...")
                await client.send_file(target, str(path), supports_streaming=True)
                
                u_check = get_user(user_id)
                if u_check and u_check["status"] == "running":
                    save_user(user_id, last_id=msg.id)
                    await bot.send_message(user_id, f"✅ Success ID: {msg.id}")
                
            except FloodWaitError as e:
                await bot.send_message(user_id, f"⏳ Flood wait {e.seconds}s")
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:
                await bot.send_message(user_id, f"❌ Failed ID {msg.id}: {e}")
            finally:
                try: path.unlink()
                except: pass
                gc.collect()

# ─── MAIN ──────────────────────────────────────────────────
async def main():
    print("[Bot] Starting Main Bot...")
    asyncio.create_task(worker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
