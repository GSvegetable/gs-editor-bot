import os
import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

def main():
    # 从环境变量读取 Token
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logging.error("❌ 未设置 BOT_TOKEN 环境变量！")
        return

    # 从环境变量读取配置
    # 1. 欢迎语
    WELCOME_TEXT = os.getenv("WELCOME_TEXT", "欢迎使用！")
    
    # 2. 内联按钮配置 (格式: [{"label": "按钮1", "reply": "回复内容1"}, {"label": "按钮2", "reply": "回复内容2"}])
    BUTTONS_JSON = os.getenv("BUTTONS_JSON", "[]")
    try:
        buttons_data = json.loads(BUTTONS_JSON)
    except:
        buttons_data = []

    # 3. 底部键盘配置 (格式: [{"label": "菜单1", "reply": "回复1"}, {"label": "菜单2", "reply": "回复2"}])
    KEYBOARD_JSON = os.getenv("KEYBOARD_JSON", "[]")
    try:
        keyboard_data = json.loads(KEYBOARD_JSON)
    except:
        keyboard_data = []

    logging.info(f"✅ 加载欢迎语: {WELCOME_TEXT}")
    logging.info(f"✅ 加载按钮: {len(buttons_data)} 个")
    logging.info(f"✅ 加载底部键盘: {len(keyboard_data)} 个")

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # 构建内联按钮
        keyboard = [[InlineKeyboardButton(b["label"], callback_data=str(i))] for i, b in enumerate(buttons_data)]
        
        # 构建底部键盘
        reply_kb = ReplyKeyboardMarkup([[k["label"]] for k in keyboard_data], resize_keyboard=True) if keyboard_data else None
        
        await update.message.reply_text(WELCOME_TEXT, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
        if reply_kb:
            await update.message.reply_text("🟢 底部菜单已加载", reply_markup=reply_kb)

    async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        bid = int(query.data)
        if 0 <= bid < len(buttons_data):
            await query.edit_message_text(buttons_data[bid]["reply"])

    async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_text = update.message.text
        for item in keyboard_data:
            if item["label"] == user_text:
                await update.message.reply_text(item["reply"])
                return

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))

    logging.info("✅ 客户机器人已启动，等待指令...")
    application.run_polling()

if __name__ == "__main__":
    main()
