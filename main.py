import os
import sys
import threading
import subprocess
import time
import logging
import requests
import psycopg2
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder

from config import BOT_TOKEN, DATABASE_URL

# ================= 数据库初始化 =================
def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bots (
            id SERIAL PRIMARY KEY,
            token TEXT UNIQUE NOT NULL,
            owner_id TEXT NOT NULL,
            welcome_text TEXT DEFAULT '欢迎使用！',
            bot_name TEXT,
            bot_username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS bot_name TEXT")
    cur.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS bot_username TEXT")
    conn.commit()
    cur.close()
    conn.close()
    logging.info("✅ 数据库初始化成功")

init_db()

# ================= 子进程管理（客户机器人在后台跑） =================
active_processes = {}

def start_client_bot(token, bot_name, bot_username):
    try:
        cmd = [sys.executable, "client.py", token]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        active_processes[token] = proc
        logging.info(f"✅ 子进程启动: {token[:10]} ({bot_name})")
        def log_output():
            for line in proc.stdout:
                logging.info(f"[Client] {line.strip()}")
        threading.Thread(target=log_output, daemon=True).start()
    except Exception as e:
        logging.error(f"❌ 启动子进程失败: {e}")

def stop_client_bot(token):
    if token in active_processes:
        try:
            active_processes[token].terminate()
            time.sleep(1)
            active_processes[token].kill()
        except Exception:
            pass
        del active_processes[token]
        logging.info(f"🛑 子进程已停止: {token[:10]}")

def monitor_loop():
    while True:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT token, bot_name, bot_username FROM bots")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            for token, bname, busername in rows:
                if token not in active_processes or active_processes[token].poll() is not None:
                    if token in active_processes:
                        del active_processes[token]
                    start_client_bot(token, bname, busername)
        except Exception as e:
            logging.error(f"监控线程出错: {e}")
        time.sleep(60)

# ================= Flask 保活网页 =================
app = Flask(__name__)
@app.route('/')
def home():
    return "Editor Running"
def run_flask():
    app.run(host="0.0.0.0", port=8080)

# ================= 首页 /start =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    full_name = user.full_name if user.full_name else (user.first_name or "未命名")
    welcome_text = (
        f"欢迎使用宫水编辑器\n"
        f"帮您高度自定义电报机器人\n\n"
        f"您的名字 {full_name}\n"
        f"您的ID <code>{user_id}</code>"
    )
    keyboard = [
        [InlineKeyboardButton("机器人列表", callback_data="list_bots")],
        [InlineKeyboardButton("联系开发者", url="https://t.me/gsyxyc"),
         InlineKeyboardButton("机器人数据", callback_data="fetch_data")]
    ]
    await update.message.reply_text(
        welcome_text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= 机器人列表 =================
async def show_bot_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("📋 正在显示机器人列表")
    user_id = update.effective_user.id
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, token, bot_name, bot_username FROM bots WHERE owner_id = %s", (str(user_id),))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await update.callback_query.edit_message_text(
            "我管理的机器人\n\n您还未添加机器人",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("添加", callback_data="add_bot_from_list")],
                [InlineKeyboardButton("返回首页", callback_data="home")]
            ])
        )
        return

    msg = "我管理的机器人\n\n"
    for bid, token, bname, busername in rows:
        msg += f"{bname} (@{busername or '无用户名'}) ID：{bid}\n"
    keyboard = [
        [InlineKeyboardButton("添加", callback_data="add_bot_from_list")],
        [InlineKeyboardButton("删除", callback_data="del_bot_enter_id")],
        [InlineKeyboardButton("返回首页", callback_data="home")]
    ]
    await update.callback_query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= 按钮回调处理 =================
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    logging.info(f"🟢 收到回调: {data}")

    if data == "home":
        await start(update, context)
    elif data == "list_bots":
        await show_bot_list(update, context)
    elif data == "add_bot_from_list":
        context.user_data['state'] = 'waiting_token'
        await update.message.reply_text(
            "请发送机器人的API",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("返回列表", callback_data="list_bots")]
            ])
        )
    elif data == "del_bot_enter_id":
        context.user_data['state'] = 'waiting_del_id'
        await update.message.reply_text(
            "请发送机器人ID",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("取消", callback_data="list_bots")]
            ])
        )
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
        bid = int(data.split("_")[2])
        context.user_data['state'] = 'add_btn_label'
        context.user_data['add_btn_bid'] = bid
        await query.edit_message_text("🔘 请输入按钮上的文字（如：立即咨询）：")
    elif data.startswith("add_kb_"):
        bid = int(data.split("_")[2])
        context.user_data['state'] = 'add_kb_label'
        context.user_data['add_kb_bid'] = bid
        await query.edit_message_text("⌨️ 请输入底部键盘的按钮文字：")
    elif data.startswith("welcome_"):
        bid = int(data.split("_")[1])
        context.user_data['state'] = 'edit_welcome'
        context.user_data['edit_welcome_bid'] = bid
        await query.edit_message_text("📝 请输入新的欢迎语文字：")
    elif data.startswith("del_bot_"):
        bid = int(data.split("_")[2])
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT token FROM bots WHERE id = %s", (bid,))
        row = cur.fetchone()
        if row:
            token = row[0]
            stop_client_bot(token)
            cur.execute("DELETE FROM bots WHERE id = %s", (bid,))
            conn.commit()
        cur.close()
        conn.close()
        await query.edit_message_text("✅ 机器人已删除。")
        await show_bot_list(update, context)
    elif data == "fetch_data":
        await query.edit_message_text("🔧 功能开发中，请期待后续版本。")

# ================= 处理用户输入（添加/删除API） =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get('state')

    if state == 'waiting_token':
        token = text.strip()
        try:
            resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            if resp.status_code != 200:
                raise Exception("Invalid Token")
            bot_data = resp.json()
            bot_name = bot_data.get("first_name", "未命名")
            bot_username = bot_data.get("username", "无用户名")
        except:
            await update.message.reply_text(
                "添加失败",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("重新添加", callback_data="add_bot_from_list")]])
            )
            context.user_data.pop('state')
            return

        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO bots (token, owner_id, bot_name, bot_username) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (token, str(user_id), bot_name, bot_username))
        conn.commit()
        cur.close()
        conn.close()
        start_client_bot(token, bot_name, bot_username)
        context.user_data.pop('state')
        await update.message.reply_text("机器人添加成功 点击主菜单我的机器人查看")
        await show_bot_list(update, context)
    elif state == 'waiting_del_id':
        bid = text.strip()
        try:
            bid_int = int(bid)
        except:
            await update.message.reply_text("ID 格式错误，请输入纯数字 ID。")
            return
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT token FROM bots WHERE id = %s AND owner_id = %s", (bid_int, str(user_id)))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("未找到该 ID 的机器人。")
            cur.close()
            conn.close()
            return
        token = row[0]
        stop_client_bot(token)
        cur.execute("DELETE FROM bots WHERE id = %s", (bid_int,))
        conn.commit()
        cur.close()
        conn.close()
        context.user_data.pop('state')
        await update.message.reply_text("✅ 机器人已删除。")
        await show_bot_list(update, context)

    # ===== 内联按钮/底部键盘配置流程 =====
    elif state == 'add_btn_label':
        bid = context.user_data.get('add_btn_bid')
        label = text.strip()
        context.user_data['add_btn_label'] = label
        context.user_data['state'] = 'add_btn_type'
        keyboard = [[InlineKeyboardButton("💬 回复文字", callback_data="btn_type_reply")], [InlineKeyboardButton("🔗 跳转链接", callback_data="btn_type_url")]]
        await update.message.reply_text(f"按钮名称：{label}\n点击后要做什么？", reply_markup=InlineKeyboardMarkup(keyboard))
    elif state == 'add_kb_label':
        bid = context.user_data.get('add_kb_bid')
        label = text.strip()
        context.user_data['add_kb_label'] = label
        context.user_data['state'] = 'add_kb_type'
        keyboard = [[InlineKeyboardButton("💬 回复文字", callback_data="kb_type_reply")], [InlineKeyboardButton("🔗 跳转链接", callback_data="kb_type_url")]]
        await update.message.reply_text(f"底部按钮：{label}\n点击后要做什么？", reply_markup=InlineKeyboardMarkup(keyboard))
    elif state == 'edit_welcome':
        bid = context.user_data.get('edit_welcome_bid')
        new_welcome = text.strip()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE bots SET welcome_text = %s WHERE id = %s", (new_welcome, bid))
        conn.commit()
        cur.close()
        conn.close()
        context.user_data.pop('state')
        await update.message.reply_text("✅ 欢迎语已更新！")

# ================= 配置类型的回调处理 =================
async def btn_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "btn_type_reply":
        context.user_data['state'] = 'add_btn_data'
        context.user_data['btn_type'] = 'reply_text'
        await query.edit_message_text("📝 请输入点击按钮后要回复的文字：")
    elif data == "btn_type_url":
        context.user_data['state'] = 'add_btn_data'
        context.user_data['btn_type'] = 'url'
        await query.edit_message_text("🔗 请输入跳转链接：")

async def kb_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "kb_type_reply":
        context.user_data['state'] = 'add_kb_data'
        context.user_data['kb_type'] = 'reply_text'
        await query.edit_message_text("📝 请输入点击后要回复的文字：")
    elif data == "kb_type_url":
        context.user_data['state'] = 'add_kb_data'
        context.user_data['kb_type'] = 'url'
        await query.edit_message_text("🔗 请输入跳转链接：")

async def handle_message_after(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')
    if state == 'add_btn_data':
        bid = context.user_data.get('add_btn_bid')
        label = context.user_data.get('add_btn_label')
        btn_type = context.user_data.get('btn_type')
        data = update.message.text.strip()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT token FROM bots WHERE id = %s", (bid,))
        row = cur.fetchone()
        if row:
            token = row[0]
            cur.execute("INSERT INTO buttons (bot_token, label, action_type, action_data) VALUES (%s, %s, %s, %s)", (token, label, btn_type, data))
            conn.commit()
        cur.close()
        conn.close()
        context.user_data.pop('state')
        await update.message.reply_text(f"✅ 按钮[{label}]已添加！")
    elif state == 'add_kb_data':
        bid = context.user_data.get('add_kb_bid')
        label = context.user_data.get('add_kb_label')
        kb_type = context.user_data.get('kb_type')
        data = update.message.text.strip()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT token FROM bots WHERE id = %s", (bid,))
        row = cur.fetchone()
        if row:
            token = row[0]
            cur.execute("INSERT INTO reply_keyboards (bot_token, label, action_type, action_data) VALUES (%s, %s, %s, %s)", (token, label, kb_type, data))
            conn.commit()
        cur.close()
        conn.close()
        context.user_data.pop('state')
        await update.message.reply_text(f"✅ 底部键盘[{label}]已添加！")

# ================= 启动入口 =================
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
    logging.info("✅ 宫水编辑器（合并在单一文件）已上线！")
    application.run_polling()

if __name__ == "__main__":
    main()
