import os
import sys
import threading
import subprocess
import time
import logging
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder

from config import BOT_TOKEN, DATABASE_URL
import psycopg2

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bots (id SERIAL PRIMARY KEY, token TEXT UNIQUE NOT NULL, owner_id TEXT NOT NULL, welcome_text TEXT DEFAULT '欢迎使用！', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS buttons (id SERIAL PRIMARY KEY, bot_token TEXT REFERENCES bots(token) ON DELETE CASCADE, label TEXT NOT NULL, action_type TEXT NOT NULL, action_data TEXT NOT NULL, position INTEGER DEFAULT 0)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reply_keyboards (id SERIAL PRIMARY KEY, bot_token TEXT REFERENCES bots(token) ON DELETE CASCADE, label TEXT NOT NULL, action_type TEXT NOT NULL, action_data TEXT NOT NULL, position INTEGER DEFAULT 0)
    """)
    conn.commit(); cur.close(); conn.close()

init_db()

app = Flask(__name__)
@app.route('/') 
def home(): return "Editor Running"
def run_flask(): app.run(host="0.0.0.0", port=8080)

active_processes = {}

def start_client_bot(token):
    # 👇 关键变化：现在调用的是新拆出来的 client.py
    cmd = [sys.executable, "client.py", token]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    active_processes[token] = proc
    print(f"✅ 子进程已启动: {token[:10]}...")

def monitor_loop():
    while True:
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT token FROM bots")
            rows = cur.fetchall(); cur.close(); conn.close()
            for (token,) in rows:
                if token not in active_processes:
                    start_client_bot(token)
        except Exception as e:
            logging.error(f"监控线程出错: {e}")
        time.sleep(60)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("➕ 添加新机器人", callback_data="add_bot")], [InlineKeyboardButton("📋 我的机器人列表", callback_data="list_bots")]]
    await update.message.reply_text("👋 欢迎使用宫水编辑器！", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    if data == "add_bot":
        context.user_data['state'] = 'waiting_token'; await query.edit_message_text("📨 请发送客户机器人的 API Token：")
    elif data == "list_bots":
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, token, welcome_text FROM bots")
        rows = cur.fetchall(); cur.close(); conn.close()
        if not rows: await query.edit_message_text("📭 暂时还没有添加任何机器人。")
        else:
            keyboard = [[InlineKeyboardButton(f"机器人 #{bid} ({token[:8]}...)", callback_data=f"config_{bid}")] for bid, token, _ in rows]
            await query.edit_message_text("📋 已绑定的机器人列表：", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("config_"):
        bid = int(data.split("_")[1])
        context.user_data['config_bid'] = bid
        keyboard = [
            [InlineKeyboardButton("➕ 添加按钮", callback_data=f"add_btn_{bid}")],
            [InlineKeyboardButton("🧱 添加底部键盘", callback_data=f"add_kb_{bid}")],
            [InlineKeyboardButton("✏️ 修改欢迎语", callback_data=f"welcome_{bid}")],
            [InlineKeyboardButton("🗑️ 删除机器人", callback_data=f"del_bot_{bid}")],
            [InlineKeyboardButton("⬅️ 返回列表", callback_data="list_bots")]
        ]
        await query.edit_message_text(f"⚙️ 配置机器人 #{bid}：", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("add_btn_"):
        bid = int(data.split("_")[2]); context.user_data['state'] = 'add_btn_label'; context.user_data['add_btn_bid'] = bid
        await query.edit_message_text("🔘 请输入按钮上的文字（如：立即咨询）：")
    elif data.startswith("add_kb_"):
        bid = int(data.split("_")[2]); context.user_data['state'] = 'add_kb_label'; context.user_data['add_kb_bid'] = bid
        await query.edit_message_text("⌨️ 请输入底部键盘的按钮文字：")
    elif data.startswith("welcome_"):
        bid = int(data.split("_")[1]); context.user_data['state'] = 'edit_welcome'; context.user_data['edit_welcome_bid'] = bid
        await query.edit_message_text("📝 请输入新的欢迎语文字：")
    elif data.startswith("del_bot_"):
        bid = int(data.split("_")[2])
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT token FROM bots WHERE id = %s", (bid,))
        row = cur.fetchone()
        if row:
            token = row[0]
            if token in active_processes: active_processes[token].terminate()
            cur.execute("DELETE FROM bots WHERE id = %s", (bid,)); conn.commit()
        cur.close(); conn.close()
        await query.edit_message_text("✅ 机器人已删除。")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; text = update.message.text; state = context.user_data.get('state')
    if state == 'waiting_token':
        token = text.strip()
        try:
            resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            if resp.status_code != 200: await update.message.reply_text("❌ Token无效，请检查后重试。"); return
        except: await update.message.reply_text("❌ 网络错误，无法验证Token。"); return
        conn = get_db(); cur = conn.cursor()
        cur.execute("INSERT INTO bots (token, owner_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (token, str(user_id)))
        conn.commit(); cur.close(); conn.close()
        start_client_bot(token); context.user_data.pop('state')
        await update.message.reply_text(f"✅ 机器人已绑定并启动！")
    elif state == 'add_btn_label':
        bid = context.user_data.get('add_btn_bid'); label = text.strip()
        context.user_data['add_btn_label'] = label; context.user_data['state'] = 'add_btn_type'
        keyboard = [[InlineKeyboardButton("💬 回复文字", callback_data="btn_type_reply")], [InlineKeyboardButton("🔗 跳转链接", callback_data="btn_type_url")]]
        await update.message.reply_text(f"按钮名称：{label}\n点击后要做什么？", reply_markup=InlineKeyboardMarkup(keyboard))
    elif state == 'add_kb_label':
        bid = context.user_data.get('add_kb_bid'); label = text.strip()
        context.user_data['add_kb_label'] = label; context.user_data['state'] = 'add_kb_type'
        keyboard = [[InlineKeyboardButton("💬 回复文字", callback_data="kb_type_reply")], [InlineKeyboardButton("🔗 跳转链接", callback_data="kb_type_url")]]
        await update.message.reply_text(f"底部按钮：{label}\n点击后要做什么？", reply_markup=InlineKeyboardMarkup(keyboard))
    elif state == 'edit_welcome':
        bid = context.user_data.get('edit_welcome_bid'); new_welcome = text.strip()
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE bots SET welcome_text = %s WHERE id = %s", (new_welcome, bid)); conn.commit()
        cur.close(); conn.close(); context.user_data.pop('state')
        await update.message.reply_text("✅ 欢迎语已更新！")

async def btn_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    if data == "btn_type_reply": context.user_data['state'] = 'add_btn_data'; context.user_data['btn_type'] = 'reply_text'; await query.edit_message_text("📝 请输入点击按钮后要回复的文字：")
    elif data == "btn_type_url": context.user_data['state'] = 'add_btn_data'; context.user_data['btn_type'] = 'url'; await query.edit_message_text("🔗 请输入跳转链接：")

async def kb_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data
    if data == "kb_type_reply": context.user_data['state'] = 'add_kb_data'; context.user_data['kb_type'] = 'reply_text'; await query.edit_message_text("📝 请输入点击后要回复的文字：")
    elif data == "kb_type_url": context.user_data['state'] = 'add_kb_data'; context.user_data['kb_type'] = 'url'; await query.edit_message_text("🔗 请输入跳转链接：")

async def handle_message_after(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')
    if state == 'add_btn_data':
        bid = context.user_data.get('add_btn_bid'); label = context.user_data.get('add_btn_label')
        btn_type = context.user_data.get('btn_type'); data = update.message.text.strip()
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT token FROM bots WHERE id = %s", (bid,))
        row = cur.fetchone()
        if row:
            token = row[0]
            cur.execute("INSERT INTO buttons (bot_token, label, action_type, action_data) VALUES (%s, %s, %s, %s)", (token, label, btn_type, data)); conn.commit()
        cur.close(); conn.close(); context.user_data.pop('state')
        await update.message.reply_text(f"✅ 按钮[{label}]已添加！")
    elif state == 'add_kb_data':
        bid = context.user_data.get('add_kb_bid'); label = context.user_data.get('add_kb_label')
        kb_type = context.user_data.get('kb_type'); data = update.message.text.strip()
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT token FROM bots WHERE id = %s", (bid,))
        row = cur.fetchone()
        if row:
            token = row[0]
            cur.execute("INSERT INTO reply_keyboards (bot_token, label, action_type, action_data) VALUES (%s, %s, %s, %s)", (token, label, kb_type, data)); conn.commit()
        cur.close(); conn.close(); context.user_data.pop('state')
        await update.message.reply_text(f"✅ 底部键盘[{label}]已添加！")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_click))
    application.add_handler(CallbackQueryHandler(btn_type_callback, pattern="^btn_type_"))
    application.add_handler(CallbackQueryHandler(kb_type_callback, pattern="^kb_type_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message_after))
    logging.info("✅ 宫水编辑器（双文件拆分版）已上线！")
    application.run_polling()

if __name__ == "__main__":
    main()
