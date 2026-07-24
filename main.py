import threading
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ApplicationBuilder

# 导入 handlers 模块
from handlers import start, button_click, handle_message, btn_type_callback, kb_type_callback, handle_message_after, monitor_loop, run_flask
from config import BOT_TOKEN

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_click))  # 这是最重要的部分
    application.add_handler(CallbackQueryHandler(btn_type_callback, pattern="^btn_type_"))
    application.add_handler(CallbackQueryHandler(kb_type_callback, pattern="^kb_type_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message_after))

    logging.info("✅ 宫水编辑器（精简版）已上线！")
    application.run_polling()

if __name__ == "__main__":
    main()
