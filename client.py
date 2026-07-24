import os
import sys
import logging
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder

from config import DATABASE_URL

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    # 客户端需要确保表存在，所以也跑一遍初始化
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bots (id SERIAL PRIMARY KEY, token TEXT UNIQUE NOT NULL, owner_id TEXT NOT NULL, welcome_text TEXT DEFAULT '欢迎使用！', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS buttons (id SERIAL PRIMARY KEY, bot_token TEXT REFERENCES bots(token) ON DELETE CASCADE, label TEXT NOT NULL, action_type TEXT NOT NULL, action_data TEXT NOT NULL, position INTEGER DEFAULT 0)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reply_keyboards (id SERIAL PRIMARY KEY, bot_token TEXT REFERENCES bots(token) ON DELETE CASCADE, label TEXT NOT NULL, action_type TEXT NOT NULL, action_data TEXT NOT NULL, position INTEGER DEFAULT 0)
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

def load_bot_config(token):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT welcome_text FROM bots WHERE token = %s", (token,))
    row = cur.fetchone()
    welcome = row[0] if row else "欢迎使用！"
    
    cur.execute("SELECT id, label FROM buttons WHERE bot_token = %s ORDER BY position", (token,))
    btn_rows = cur.fetchall()
    
    cur.execute("SELECT label, action_type, action_data FROM reply_keyboards WHERE bot_token = %s ORDER BY position", (token,))
    kb_rows = cur.fetchall()
    cur.close(); conn.close()
    return welcome, btn_rows, kb_rows

async def client_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    CLIENT_TOKEN = context.bot.token
    welcome, btn_rows, kb_rows = load_bot_config(CLIENT_TOKEN)
    keyboard = [[InlineKeyboardButton(label, callback_data=str(bid))] for bid, label in btn_rows]
    reply_kb = ReplyKeyboardMarkup([[r[0]] for r in kb_rows], resize_keyboard=True) if kb_rows else None
    await update.message.reply_text(welcome, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
    if reply_kb: await update.message.reply_text("🟢 底部菜单已加载", reply_markup=reply_kb)

async def client_reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    CLIENT_TOKEN = context.bot.token
    welcome, btn_rows, kb_rows = load_bot_config(CLIENT_TOKEN)
    keyboard = [[InlineKeyboardButton(label, callback_data=str(bid))] for bid, label in btn_rows]
    reply_kb = ReplyKeyboardMarkup([[r[0]] for r in kb_rows], resize_keyboard=True) if kb_rows else None
    await update.message.reply_text("✅ 配置已重新加载！", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
    if reply_kb: await update.message.reply_text("🟢 底部菜单已刷新", reply_markup=reply_kb)

async def client_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bid = int(query.data)
    CLIENT_TOKEN = context.bot.token
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT action_type, action_data FROM buttons WHERE bot_token = %s AND id = %s", (CLIENT_TOKEN, bid))
    row = cur.fetchone(); cur.close(); conn.close()
    if row:
        a_type, a_data = row
        if a_type == "reply_text": await query.edit_message_text(a_data)
        elif a_type == "url": await query.edit_message_text(f"🔗 点击跳转：{a_data}")

async def client_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    CLIENT_TOKEN = context.bot.token
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT action_type, action_data FROM reply_keyboards WHERE bot_token = %s AND label = %s", (CLIENT_TOKEN, user_text))
    row = cur.fetchone(); cur.close(); conn.close()
    if row:
        a_type, a_data = row
        if a_type == "reply_text": await update.message.reply_text(a_data)
        elif a_type == "url": await update.message.reply_text(f"🔗 点击打开：{a_data}")

def main():
    if len(sys.argv) < 2:
        return
    CLIENT_TOKEN = sys.argv[1]
    print(f"🟢 子进程启动，托管客户机器人: {CLIENT_TOKEN[:10]}...")
    application = ApplicationBuilder().token(CLIENT_TOKEN).build()
    application.add_handler(CommandHandler("start", client_start))
    application.add_handler(CommandHandler("reload", client_reload))
    application.add_handler(CallbackQueryHandler(client_button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, client_message))
    application.run_polling()

if __name__ == "__main__":
    main()
