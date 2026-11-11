"""
NOVA 24/7 Cloud Brain Controller.
Runs continuously on the cloud server and routes desktop tasks via Supabase.
"""
import os
import asyncio
import threading
import http.server
import socketserver
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

# ক্রেডেনশিয়ালস
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
            return "কমান্ড ডেটাবেসে পাঠাতে সমস্যা হয়েছে।"

        cmd_id = insert_res.data[0]["id"]

        for _ in range(timeout * 2):
            await asyncio.sleep(0.5)
            check = supabase.table("nova_commands").select("*").eq("id", cmd_id).execute()
            if check.data:
                row = check.data[0]
                if row.get("status") == "completed":
                    return row.get("result_text") or "কাজটি সম্পন্ন হয়েছে বস।"
                elif row.get("status") == "failed":
                    return row.get("result_text") or "কাজটি সম্পন্ন করতে ত্রুটি হয়েছে।"

        return "পিসি থেকে সময়মতো কোনো সাড়া পাওয়া যায়নি বস।"
    except Exception as e:
        return f"কমান্ড ব্রিজ এরর: {e}"

# টেলিগ্রাম হ্যান্ডলার
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    online = check_pc_online()
    status_str = "🟢 পিসি অনলাইন" if online else "🔴 পিসি অফলাইন (ক্লাউড সক্রিয়)"
    await update.message.reply_text(
        f"🤖 **নোভা ২৪/৭ ক্লাউড অ্যাসিস্ট্যান্ট অনলাইন!**\n\n"
        f"• স্ট্যাটাস: `{status_str}`\n"
        f"• পিসি বন্ধ থাকলেও যেকোনো প্রশ্নের উত্তর পাবেন।\n"
        f"• পিসি কন্ট্রোল প্যানেলের জন্য `/panel` চাপুন।",
        parse_mode="Markdown"
    )

async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    keyboard = [
        [InlineKeyboardButton("🖥️ স্ক্রিনশট", callback_data="cmd_screenshot"), InlineKeyboardButton("🩺 পিসি হেলথ", callback_data="cmd_pc_status")],
        [InlineKeyboardButton("📊 চলতি অ্যাপস", callback_data="cmd_running_apps"), InlineKeyboardButton("🔄 ট্যাব বন্ধ", callback_data="cmd_close_tab")],
        [InlineKeyboardButton("🔒 পিসি লক", callback_data="cmd_lock_pc"), InlineKeyboardButton("📁 ডাউনলোডস", callback_data="cmd_downloads")]
    ]
    await update.message.reply_text("🎛️ **নোভা কন্ট্রোল প্যানেল:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(query.from_user.id):
        await query.answer("অননুমোদিত ইউজার", show_alert=True)
        return

    await query.answer("নির্দেশ গ্রহণ করা হয়েছে...", show_alert=False)
    data = query.data.replace("cmd_", "")

    if not check_pc_online():
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⚠️ **বস, পিসি বর্তমানে বন্ধ (অফলাইন) রয়েছে!**\nপিসি অন করলেই ডেস্কটপ কমান্ড কাজ করবে।",
            parse_mode="Markdown"
        )
        return

    status_msg = await context.bot.send_message(chat_id=query.message.chat_id, text=f"⏳ পিসিতে `{data}` নির্দেশ পাঠানো হচ্ছে...")
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
                "⚠️ **বস, আপনার পিসি বন্ধ রয়েছে।**\nপিসি চালু করলে আমি কাজ সম্পন্ন করব। পড়াশোনা বা অন্য যেকোনো তথ্য লাগলে বলুন, আমি উত্তর দিচ্ছি!",
                parse_mode="Markdown"
            )
        
        await update.message.reply_text("⏳ পিসিতে নির্দেশ পাঠানো হচ্ছে...")
        res = await route_pc_command(text)
        return await update.message.reply_text(res, parse_mode="Markdown")

    if not gemini_client:
        return await update.message.reply_text("জেমিনাই এপিআই সংযুক্ত নেই।")

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
        await update.message.reply_text(resp.text or "আদেশ বুঝতে পারিনি বস।")
    except asyncio.TimeoutError:
        await update.message.reply_text("⚠️ এআই রেসপন্স তৈরিতে অতিরিক্ত সময় নিয়েছে। অনুগ্রহ করে আবার মেসেজ করুন।")
    except Exception as e:
        print(f"[!] Gemini Error: {e}")
        await update.message.reply_text(f"⚠️ এআই উত্তর তৈরিতে সমস্যা: {e}")

# রেন্ডার ওয়েব সার্ভিসের পোর্ট স্ক্যান সফল করার ডামি সার্ভার
def start_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    class DummyHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"NOVA Cloud Bot is Running 24/7!")
        def log_message(self, format, *args):
            return

    try:
        with socketserver.TCPServer(("0.0.0.0", port), DummyHandler) as httpd:
            print(f"[*] Web server listening on port {port}...")
            httpd.serve_forever()
    except Exception as e:
        print(f"[!] Web server error: {e}")

def main():
    # ব্যাকগ্রাউন্ড থ্রেডে পোর্ট লিসেনার চালু রাখা
    t = threading.Thread(target=start_dummy_server, daemon=True)
    t.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("panel", panel_cmd))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^cmd_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("[*] NOVA 24/7 Cloud Bot চালু হয়েছে...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
