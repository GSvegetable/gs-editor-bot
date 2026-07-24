import sys
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

if __name__ == "__main__":
    if len(sys.argv) < 5:
        logging.error("❌ 参数不足，无法启动")
        sys.exit(0)

    CLIENT_TOKEN = sys.argv[1]
    WELCOME = sys.argv[2]
    BUTTONS_JSON = sys.argv[3]
    KEYBOARD_JSON = sys.argv[4]

    try:
        buttons_data = json.loads(BUTTONS_JSON)
        keyboard_data = json.loads(KEYBOARD_JSON)
    except:
        buttons_data = []
        keyboard_data = []

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [[InlineKeyboardButton(b["label"], callback_data=str(i))] for i, b in enumerate(buttons_data)]
        reply_kb = ReplyKeyboardMarkup([[k["label"]] for k in keyboard_data], resize_keyboard=True) if keyboard_data else None
        await update.message.reply_text(WELCOME, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
        if reply_kb:
            await update.message.reply_text("🟢 底部菜单已加载", reply_markup=reply_kb)

    async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        bid = int(query.data)
        if 0 <= bid < len(buttons_data):
            await query.edit_message_text(buttons_data[bid]["reply"])

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_text = update.message.text
        for item in keyboard_data:
            if item["label"] == user_text:
                await update.message.reply_text(item["reply"])
                return

    app = ApplicationBuilder().token(CLIENT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info(f"✅ 客户机器人启动成功，配置已带：{WELCOME}")
    app.run_polling()
