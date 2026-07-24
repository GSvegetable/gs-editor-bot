import os
import sys
import json
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
    
    # ===== ✨ 新增修复：给旧数据库手动补上缺失的列 =====
    try:
        # 给 reply_keyboards 表加上 action_type 和 action_data 列（如果不存在的话）
        cur.execute("ALTER TABLE reply_keyboards ADD COLUMN IF NOT EXISTS action_type TEXT DEFAULT 'reply_text'")
        cur.execute("ALTER TABLE reply_keyboards ADD COLUMN IF NOT EXISTS action_data TEXT DEFAULT ''")
        conn.commit()
        logging.info("✅ 数据库表结构修复成功！")
    except Exception as e:
        logging.warning(f"⚠️ 表结构更新提示: {e}")
    # ==================================================

    conn.commit(); cur.close(); conn.close()

init_db()
app = Flask(__name__)
@app.route('/') 
def home(): return "Editor Running"
def run_flask(): app.run(host="0.0.0.0", port=8080)

active_processes = {}

def start_client_bot(token):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT welcome_text FROM bots WHERE token = %s", (token,))
        row = cur.fetchone()
        welcome = row[0] if row else "欢迎使用！"

        cur.execute("SELECT label, action_type, action_data FROM buttons WHERE bot_token = %s ORDER BY position", (token,))
        btns = cur.fetchall()
        buttons = [{"label": b[0], "reply": b[2]} for b in btns if b[1] == "reply_text"]

        cur.execute("SELECT label, action_type, action_data FROM reply_keyboards WHERE bot_token = %s ORDER BY position", (token,))
        kbs = cur.fetchall()
        keyboards = [{"label": k[0], "reply": k[2]} for k in kbs if k[1] == "reply_text"]

        cur.close(); conn.close()

        buttons_json = json.dumps(buttons)
        keyboards_json = json.dumps(keyboards)

        cmd = [sys.executable, "client.py", token, welcome, buttons_json, keyboards_json]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        active_processes[token] = proc
        logging.info(f"✅ 子进程启动，配置已直传")
        def log_output():
            for line in proc.stdout:
                logging.info(f"[Client] {line.strip()}")
        threading.Thread(target=log_output, daemon=True).start()
    except Exception as e:
        logging.error(f"❌ 启动子进程失败: {e}")

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
        await query.edit_message_text("🔘 请输入按钮上的文字：")
    elif data.startswith("add_kb_"):
        bid = int(data.split("_")[2]); context.user_data['state'] = 'add_kb_label'; context.user_data['add_kb_bid'] = bid
        await query.edit_message_text("⌨️ 请输入底部键盘的文字：")
    elif data.startswith("welcome_"):
        bid = int(data.split("_")[1]); context.user_data['state'] = 'edit_welcome'; context.user_data['edit_welcome_bid'] = bid
        await query.edit_message_text("📝 请输入新的欢迎语：")
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
    如果数据==请求。得到(f"https://api.telegram.org/bot{ token }/getMe"，timeout=10)
            如果RESP.status_code!=200: 等候更新。消息.回复文本(_T)("❌ Token无效"); 返回
        除……之外: 等候更新。消息.回复文本(_T)("❌ 网络错误"); 返回
Conn=get_db()；cur=conn.光标()
cur.执行("插入到bots(令牌，owner_id)值(%s，%s)冲突时，不执行任何操作", (令牌，str(user_id)))
Conn.犯罪()；cur.关闭()；conn.关闭()
        start_client_bot(令牌)；上下文。user_data.流行音乐('状态')
        等候更新。消息.回复文本(_T)(f"✅ 机器人已绑定并启动！")
    Elif状态=='添加btn标签':
bid=上下文。user_data.得到('Add_btn_bid')；label=文本。带()
语境。user_data['添加btn标签']=标签；上下文。user_data['状态']='添加btn类型'
键盘=[[InlineKeyboardButton("💬 回复文字"，callback_data="btn_type_reply")], [InlineKeyboardButton("🔗 跳转链接"，callback_data="btn_type_url")]]
        等候更新。消息.回复文本(_T)(F"按钮名：{标签}\n点击后做什么？"，reply_markup=InlineKeyboardMarkup(键盘))
    Elif状态=='Add_kb_label':
bid=上下文。user_data.得到('Add_kb_bid')；label=文本。带()
语境。user_data['Add_kb_label']=标签；上下文。user_data['状态']='Add_kb_type'
键盘=[[InlineKeyboardButton("💬 回复文字"，callback_data="kb_type_reply")], [InlineKeyboardButton("🔗 跳转链接"，callback_data="kb_type_url")]]
        等候更新。消息.回复文本(_T)(F"底部按钮：{标签}\n点击后做什么？"，reply_markup=InlineKeyboardMarkup(键盘))
Elif'Edit_welcome':
Conn=get_db()；cur=conn.光标()
    main
importelif状态==cur.执行("更新僵尸设置welcome_text=%s WHERE id=%s"，(新欢迎，出价(_W)))；conn.犯罪()("更新僵尸设置welcome_text=%s WHERE id=%s", (新欢迎，出价(_W)))；conn.犯罪()
cur.关闭()；conn.关闭()；上下文。user_data。流行音乐('状态')关闭()；conn.关闭()；上下文。user_data.流行音乐('状态')
        等候更新。消息.回复文本(_T)("✅ 欢迎语已更新！")回复文本(_T)("✅ 欢迎语已更新！")

主要的主要的))(尝试        (_P)：)：BTN_type_callback(更新：更新，上下文：ContextTypes。default_TYPE):
查询=更新。callback_query；等候查询。回答()等候查询。回答()
data=查询。数据
如果数据=="BTN_type_reply”：上下文。user_data['状态']='添加BTN_data'；上下文。user_data['btn_type']='reply_text'；等候查询。编辑消息文本("📝 请输入点击后回复的文字：")"btn_type_reply"：上下文。user_data['状态']='添加btn_data'；上下文。user_data['btn_type']='reply_text'; 等候查询。编辑消息文本("📝 请输入点击后回复的文字：")
Elif数据=="BTN_type_url"：上下文。user_data['状态']='添加BTN_data'；上下文。user_data['btn_type']='url'；等候查询。编辑消息文本("🔗 请输入跳转链接：")"btn_type_url"：上下文。user_data['状态']='添加btn_data'；上下文。user_data['btn_type']='url'; 等候查询。编辑消息文本("🔗 请输入跳转链接：")

异步定义KB_type_callback(更新：更新，上下文：ContextTypes.default_TYPE)：KB_type_callback(更新：更新，上下文：ContextTypes。default_TYPE):
查询=更新。callback_query；等候查询。回答()等候查询。回答()
data=查询。数据
如果数据=="KB_type_reply“”：上下文。user_data['状态']='add_kb_data'；上下文。user_data['kb_type']='reply_text'；等候查询。编辑消息文本("📝 请输入点击后回复的文字：")"kb_type_reply"：上下文。user_data['状态']='Add_kb_data'；上下文。user_data['kb_type']='reply_text'; 等候查询。编辑消息文本("📝 请输入点击后回复的文字：")
Elif数据=="KB_type_url"：上下文。user_data['状态']='add_kb_data'；上下文。user_data['kb_type']='url'；等候查询。编辑消息文本("🔗 请输入跳转链接：")"kb_type_url"：上下文。user_data['状态']='Add_kb_data'；上下文。user_data['kb_type']='url'; 等候查询。编辑消息文本("🔗 请输入跳转链接：")

异步定义handle_message_after(更新：更新，上下文：ContextTypes.default_TYPE)：handle_message_after(更新：更新，上下文：ContextTypes。default_TYPE):
状态=上下文。user_data。得到('状态')得到('状态')
如果状态=='添加BTN_data'：'添加btn_data':
bid=上下文.User_data。得到('Add_btn_bid')；label=上下文。user_data.得到('添加btn标签')得到('Add_btn_bid')；label=上下文。user_data.得到('添加btn标签')
BTN_type=上下文。user_data。得到('btn_type')；数据=更新。消息.文本.带()得到('btn_type')；data=update。消息.文本.带()
Conn=get_db()；cur=conn.光标()get_db()；cur=conn.光标()()
cur.执行("从bots中选择标记，ID=%s"，(出价，))执行("从bots中选择标记，ID=%s", (出价，))
row=cur.取酮()取酮()
        如果行：
token=row[0][0]
cur.执行("插入按钮(bot_token，标签，action_type，action_data)值(%s，%s，%s)"，(标记、标签、BTN_type、数据))；Conn.犯罪()执行("INSERT INTO按钮(bot_token，标签，action_type，action_data)值(%s，%s，%s)", (标记、标签、btn_type、数据))；conn.犯罪()
cur.关闭()；conn.关闭()；上下文。user_data。流行音乐('状态')关闭()；conn.关闭()；上下文。user_data.流行音乐('状态')
等候更新。消息.回复文本(_T)(f"✅ 按钮[{标签}]已添加！")回复文本(_T)(f"✅ 按钮[{标签}]已添加！")
Elif状态=='Add_kb_data'：'Add_kb_data':
bid=上下文.得到('Add_kb_bid')；label=上下文.user_data.得到('Add_kb_label')得到('Add_kb_bid')；label=上下文。user_data.得到('Add_kb_label')
KB_type=上下文。user_data。得到('kb_type')；数据=更新。消息.文本.带()得到('kb_type')；data=update。消息.文本.带()
Conn=get_db()；cur=conn.光标()get_db()；cur=conn.光标()
cur.执行("从bots中选择标记，ID=%s"，(出价，))执行("从bots中选择标记，ID=%s", (出价，))
row=cur.取酮()取酮()
        如果行：
token=row[0][0]
cur.执行("插入应答键盘(bot_token，标签，action_type，action_data)值(%s，%s，%s)"，(标记、标签、KB_type、数据))；Conn.犯罪()执行("INSERT INTO应答键盘(bot_token，标签，action_type，action_data)值(%s，%s，%s)", (标记、标签、kb_type、数据))；conn.犯罪()
cur.关闭()；conn.关闭()；上下文。user_data。流行音乐('状态')关闭()；conn.关闭()；上下文。user_data.流行音乐('状态')
        等候更新。消息.回复文本(_T)(f"✅ 底部键盘[{标签}]已添加！")回复文本(_T)(f"✅ 底部键盘[{标签}]已添加！")

定义 主要的():主要的():
穿线。线(目标=运行Blask(_B)，守护程序=正确).开始()(目标=run_blask，守护程序=正确).开始()
穿线。线(目标=监视循环，守护程序=正确).开始()(目标=监视循环，守护程序=正确).开始()
应用程序=ApplicationBuilder().令牌(bot_TOKEN)。建立()ApplicationBuilder().令牌(bot_TOKEN).建立()
应用。add_handler(CommandHandler)("开始"，开始))(CommandHandler("开始"，开始))
应用。add_handler(CallbackQueryHandler(button_click))(CallbackQueryHandler(button_click))
应用。add_handler(CallbackQueryHandler(BTN_type_callback，模式="^btn_type_"))(CallbackQueryHandler(BTN_type_callback，模式="^btn_type_"))
应用。add_handler(CallbackQueryHandler(KB_type_callback，模式="^kb_type_"))(CallbackQueryHandler(KB_type_callback，模式="^kb_type_"))
应用。添加处理程序(MessageHandler)(_H)(过滤器。文本筛选器(&~F).命令，句柄消息(_message)))(MessageHandler(过滤器。文本筛选器(&~F)。命令，句柄消息(_message)))
应用。添加处理程序(MessageHandler)(_H)(过滤器。文本筛选器(&~F).命令，handle_message_after))(MessageHandler(过滤器。文本筛选器(&~F)。命令，handle_message_after))
采运作业。信息("✅ 宫水编辑器（直传版）已上线！")("✅ 宫水编辑器（直传版）已上线！")
应用。运行轮询(_P)()(_P)()

如果__名称__=="__main__"："__main__":
主要的主要的)
