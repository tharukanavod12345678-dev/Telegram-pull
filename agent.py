# agent.py — Failsafe Update Agent (Runs only if app.py crashes 3 times)
import os
import subprocess
import zipfile
import shutil
import asyncio
import py_compile
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F

BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
ADMIN_ID  = int(os.environ.get("ADMIN_ID", "0"))
HOME_DIR  = Path(__file__).resolve().parent

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(F.from_user.id == ADMIN_ID)
async def handle_failsafe(message: types.Message):
    if not message.document or not message.document.file_name.endswith(".zip"):
        return

    await message.reply("🚑 **[FAILSAFE]** Downloading update...")
    zip_path = HOME_DIR / "failsafe.zip"
    await bot.download(message.document, destination=zip_path)

    temp_dir = HOME_DIR / "_temp_agent"
    if temp_dir.exists(): shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.namelist():
                filename = os.path.basename(member)
                if not filename: continue
                source = zip_ref.open(member)
                target = open(temp_dir / filename, "wb")
                with source, target:
                    shutil.copyfileobj(source, target)
    except Exception as e:
        await message.reply(f"🚑 **[FAILSAFE]** Extract failed: `{e}`")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return
    finally:
        try: zip_path.unlink()
        except: pass

    # Check Syntax before applying
    new_app = temp_dir / "app.py"
    if new_app.exists():
        try:
            py_compile.compile(str(new_app), doraise=True)
        except py_compile.PyCompileError as e:
            await message.reply(f"🚑 **[FAILSAFE]** Syntax Error:\n`{e}`\nAborting.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return

    # Apply Update
    for f in temp_dir.glob("*"):
        shutil.move(str(f), str(HOME_DIR / f.name))
    shutil.rmtree(temp_dir, ignore_errors=True)

    await message.reply("🚑 **[FAILSAFE]** Restarting Main Bot...")
    
    # FIX: Spawn a background process to stop Agent and Start Main Bot
    # Using a slight delay (sleep 2) to allow Telegram message to send
    subprocess.Popen(
        ["bash", "-c", "sleep 2 && sudo systemctl stop tgagent && sudo systemctl start tgpull"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )

async def main():
    print("[AGENT] Failsafe Agent started.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
