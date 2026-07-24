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

import db
from config import BOT_TOKEN

# ================= 全局变量与保活 =================
active_processes = {}
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

app = Flask(__name__)
@app.route('/')
def home():
    return "Editor Running"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# ================= 管理子进程（启动、监控、停止） =================
def start_client_bot(token):
    try:
        cmd = [sys.executable, "client.py", token]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        active_processes[token] = proc
        logging.info(f"✅ 子进程已启动: {token[:10]}...")
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
            conn = db.get_db()
            cur = conn.cursor()
            cur.execute("SELECT token FROM bots")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            for (token,) in rows:
                if token not in active_processes or active_processes[token].poll() is not None:
                    if token in active_processes:
                        del active_processes[token]
                    start_client_bot(token)
        except Exception as e:
            logging.error(f"监控线程出错: {e}")
        time.sleep(60)

# ================= 主控界面 UI =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    full_name = user.full_name if user.full_name else (user.first_name or "未命名")
    welcome_text = (
        f"欢迎使用宫水编辑器\n"
        f"帮您高度自定义电报机器人\n\n"
        f"您的名字 {full_name}\n"
        f"您的ID <code>{user.id}</code>"
    )
    keyboard = [
        [InlineKeyboardButton("机器人列表", callback_data="list_bots")],
        [InlineKeyboardButton("联系开发者", url="https://t.me/gsyxyc"),
         InlineKeyboardButton("机器人数据", callback_data="fetch_data")]
    ]
    await update.message.reply_text(welcome_text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def show_bot_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = db.get_user_bots(str(user_id))
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
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
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
    elif data == "fetch_data":
        await query.edit_message_text("🔧 功能开发中，请期待后续版本。")

# ================= 处理文字输入 =================
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
            bname = bot_data.get("first_name", "未命名")
            busername = bot_data.get("username", "无用户名")
        except:
            await update.message.reply_text(
                "添加失败",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("重新添加", callback_data="add_bot_from_list")]
                ])
            )
            context.user_data.pop('state')
            return
        
        db.insert_bot(token, str(user_id), bname, busername)
        start_client_bot(token)
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
        token = db.get_bot_token_by_id(bid_int)
        if not token:
            await update.message.reply_text("未找到该 ID 的机器人。")
            return
        stop_client_bot(token)
        db.delete_bot_by_id(bid_int)
        context.user_data.pop('state')
        await update.message.reply_text("✅ 机器人已删除。")
        await show_bot_list(update, context)

# ================= 启动主程序 =================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_click))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("✅ 宫水编辑器（5文件平衡版）已上线！")
    application.run_polling()

if __name__ == "__main__":
    main()
