"""
NOVA 24/7 Cloud Brain Controller.
Runs continuously on the cloud server and routes desktop tasks via Supabase.
"""
import os
import asyncio
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from supabase import create_client, Client
from google import genai
from google.genai import types
from aiohttp import web

# Credentials
BOT_TOKEN = "9136618745:AAExjjVIl1MLrQ2Cr_UAdKhPE0IQ7GCOKGM"
ALLOWED_USER_ID = "8665437254"
GEMINI_API_KEY = "AQ.Ab8RN6K-0I58WxWH8bHcWuGs2vjlw96UxXYWVRpbrTXBhdoUdw"
GEMINI_MODEL = "gemini-3.8-flash"

SUPABASE_URL = "https://eazlampzfzunofqnerka.supabase.co"
SUPABASE_KEY = "sb_publishable_Pbwhlc6Vx5t4TmzuRRqLAQ_EuiWdbvw"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def is_authorized(user_id) -> bool:
    return str(user_id).strip() == ALLOWED_USER_ID

def check_pc_online() -> bool:
    try:
        res = supabase.table("pc_status").select("*").eq("id", 1).execute()
        if not res.data:
            return False
        row = res.data[0]
        if not row.get("is_online"):
            return False
        
        last_ping_str = row.get("last_ping")
        if not last_ping_str:
            return False

        last_ping = datetime.fromisoformat(last_ping_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - last_ping).total_seconds() < 45
    except Exception as e:
        print(f"[!] Status check error: {e}")
        return False

async def route_pc_command(command_text: str, timeout: int = 15) -> str:
    try:
        insert_res = supabase.table("nova_commands").insert({
            "command_text": command_text,
            "status": "pending"
        }).execute()
        if not insert_res.data:
            return "Command database-e pathate somossya hoyeche."

        cmd_id = insert_res.data[0]["id"]

        for _ in range(timeout * 2):
            await asyncio.sleep(0.5)
            check = supabase.table("nova_commands").select("*").eq("id", cmd_id).execute()
            if check.data:
                row = check.data[0]
                if row.get("status") == "completed":
                    return row.get("result_text") or "Kajti shompurno hoyeche boss."
                elif row.get("status") == "failed":
                    return row.get("result_text") or "Kajti korte truti hoyeche."

        return "PC theke shomoymoto kono shada paowa jayni boss."
    except Exception as e:
        return f"Command bridge error: {e}"

# Telegram Command Handlers
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    online = check_pc_online()
    status_str = "🟢 PC Online" if online else "🔴 PC Offline (Cloud shokriyo)"
    await update.message.reply_text(
        f"🤖 **NOVA 24/7 Cloud Assistant Online!**\n\n"
        f"• Status: `{status_str}`\n"
        f"• PC bondho thakleo jekono proshner uttor paben.\n"
        f"• PC control panel-er jonno `/panel` chapun.",
        parse_mode="Markdown"
    )

async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    keyboard = [
        [InlineKeyboardButton("🖥️ Screenshot", callback_data="cmd_screenshot"), InlineKeyboardButton("🩺 PC Health", callback_data="cmd_pc_status")],
        [InlineKeyboardButton("📊 Cholti Apps", callback_data="cmd_running_apps"), InlineKeyboardButton("🔄 Tab Bondho", callback_data="cmd_close_tab")],
        [InlineKeyboardButton("🔒 PC Lock", callback_data="cmd_lock_pc"), InlineKeyboardButton("📁 Downloads", callback_data="cmd_downloads")]
    ]
    await update.message.reply_text("🎛️ **NOVA Control Panel:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(query.from_user.id):
        await query.answer("Unauthorized user", show_alert=True)
        return

    await query.answer("Nirdesh grohon kora hoyeche...", show_alert=False)
    data = query.data.replace("cmd_", "")

    if not check_pc_online():
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⚠️ **Boss, PC bortomane bondho (Offline) ache!**\nPC on thakle desktop command kaj korbe.",
            parse_mode="Markdown"
        )
        return

    status_msg = await context.bot.send_message(chat_id=query.message.chat_id, text=f"⏳ PC-te `{data}` nirdesh pathano hocche...")
    result = await route_pc_command(data)
    await status_msg.edit_text(result, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    text = update.message.text.strip()
    low_text = text.lower()

    pc_keywords = ["open", "close", "tab", "ট্যাব", "running apps", "চলতি অ্যাপস", "screenshot", "স্ক্রিনশট", "পিসি হেলথ", "লক", "find ", "ফাইল "]
    is_pc_action = any(k in low_text for k in pc_keywords)

    if is_pc_action:
        if not check_pc_online():
            return await update.message.reply_text(
                "⚠️ **Boss, apnar PC bondho ache.**\nPC chalu korle ami kaj shompurno korbo. Podashona ba onyo jekono tothyo lagle bolun, ami uttor dicchi!",
                parse_mode="Markdown"
            )
        
        await update.message.reply_text("⏳ PC-te nirdesh pathano hocche...")
        res = await route_pc_command(text)
        return await update.message.reply_text(res, parse_mode="Markdown")

    if not gemini_client:
        return await update.message.reply_text("Gemini API connected nei.")

    try:
        chat = gemini_client.chats.create(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction="You are NOVA, a smart, polite and witty desktop AI assistant developed by Joydeep. Answer clearly, accurately and conversationally in Bengali."
            )
        )
        resp = await asyncio.wait_for(
            asyncio.to_thread(chat.send_message, text),
            timeout=20.0
        )
        await update.message.reply_text(resp.text or "Adesh bujhte parini boss.")
    except asyncio.TimeoutError:
        await update.message.reply_text("⚠️ AI response toirite odhik shomoy niyeche. Onugroho kore abar message korun.")
    except Exception as e:
        print(f"[!] Gemini Error: {e}")
        await update.message.reply_text(f"⚠️ AI uttor toirite somossya: {e}")

async def dummy_web_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="NOVA Cloud Bot is Running 24/7!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("panel", panel_cmd))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^cmd_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    try:
        loop = asyncio.get_event_loop()
        loop.create_task(dummy_web_server())
    except Exception as e:
        print(f"[!] Web server start error: {e}")

    print("[*] NOVA 24/7 Cloud Bot chalu hoyeche...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
