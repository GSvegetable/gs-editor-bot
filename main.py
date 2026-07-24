import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 获取用户信息
    user = update.effective_user
    name = user.full_name  # 获取用户的姓和名
    user_id = user.id      # 纯数字ID

    # 严格遵循排版：无冒号、无蓝色字体、留有空格
    text = (
        f"欢迎 {name} 使用gsbot\n"
        f"您的ID {user_id}\n"
        "\n"
        "专注Telegram Bot 全功能开发与系统集成\n"
        "覆盖 Bot API 全部能力域 免费定制一切功能\n"
        "已累计制作60＋企业级多功能机器人\n"
        "输入 /help 进入首页"
    )

    # 按钮布局：两行，每行两个（纯纯的按钮，无实际功能）
    keyboard = [
        [InlineKeyboardButton("定制机器人", callback_data='custom'), InlineKeyboardButton("b", callback_data='b')],
        [InlineKeyboardButton("c", callback_data='c'), InlineKeyboardButton("d", callback_data='d')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # 就地发送新消息，不带任何多余推送气泡
    await update.message.reply_text(text, reply_markup=reply_markup)

# 占位符处理，保证这四个按钮点了没有任何效果（也不会报错崩溃）
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # 只做静默响应

def main():
    # 启动机器人
    app = Application.builder().token(BOT_TOKEN).build()

    # 注册命令与按钮回调
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))

    print("Bot started...")
    app.run_polling()

if __name__ == '__main__':
    main()
