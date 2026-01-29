# ================= IMPORT =================
import asyncio, json, hashlib, hmac, threading, requests, random
import aiosqlite
from fastapi import FastAPI, Request
import uvicorn
from openpyxl import Workbook
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= CONFIG =================

TOKEN = "7840725448:AAF8bHPcIfbz_Hvo_dT58pyFOIbFd9XeP8U"
BOT_USERNAME = "CTY_MIMEDIA_BOT"
ADMINS = [7316498621]

PAYOS_CLIENT_ID = "4ed853ef-465c-4178-816e-2e3a786a45bb"
PAYOS_API_KEY = "119da978-0fce-4b01-b1c4-c9c7061604a7"
PAYOS_CHECKSUM_KEY = "1850b45ed1dbc9672e6609550563a6aacd33b9866fa842918cd730fa993b30f6"

# ================= INIT =================

bot = Bot(TOKEN)
dp = Dispatcher()
app = FastAPI()

# user steps (withdraw input)
USER_STEP = {}   # {user_id: "withdraw"}

# admin steps (manage user input)
ADMIN_STEP = {}  # {admin_id: {"mode":"await_uid"/"add_amount"/"del_amount", "target": int}}

SPIN_ENABLE = False

# ================= DATABASE =================

async def init_db():
    async with aiosqlite.connect("data.db") as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT,
            vnd INTEGER DEFAULT 0,
            ref_count INTEGER DEFAULT 0,
            vip INTEGER DEFAULT 0,
            total_deposit INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS withdraw(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            status TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS withdraw_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            status TEXT,
            time TEXT
        )
        """)
        # log cộng/trừ
        await db.execute("""
        CREATE TABLE IF NOT EXISTS money_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            user_id INTEGER,
            amount INTEGER,
            action TEXT,
            time TEXT
        )
        """)
        await db.commit()

async def add_user(uid, name, username):
    async with aiosqlite.connect("data.db") as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id,name,username) VALUES(?,?,?)",
            (uid, name, username)
        )
        # cập nhật lại name/username mỗi lần /start (cho đúng nếu user đổi tên)
        await db.execute(
            "UPDATE users SET name=?, username=? WHERE user_id=?",
            (name, username, uid)
        )
        await db.commit()

async def get_user(uid):
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        return await cur.fetchone()

async def add_money(uid, amount):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("UPDATE users SET vnd=vnd+? WHERE user_id=?", (amount, uid))
        await db.commit()

async def del_money(uid, amount):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("UPDATE users SET vnd=vnd-? WHERE user_id=?", (amount, uid))
        await db.commit()

async def set_ban(uid, banned: int):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("UPDATE users SET banned=? WHERE user_id=?", (banned, uid))
        await db.commit()

async def reset_ref(uid):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("UPDATE users SET ref_count=0 WHERE user_id=?", (uid,))
        await db.commit()

async def log_money(admin_id, user_id, amount, action):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("""
        INSERT INTO money_logs(admin_id,user_id,amount,action,time)
        VALUES(?,?,?,?,?)
        """, (admin_id, user_id, amount, action, str(datetime.now())))
        await db.commit()

async def create_withdraw(uid, amount):
    async with aiosqlite.connect("data.db") as db:
        await db.execute(
            "INSERT INTO withdraw(user_id,amount,status) VALUES(?,?,?)",
            (uid, amount, "pending")
        )
        await db.execute(
            "INSERT INTO withdraw_logs(user_id,amount,status,time) VALUES(?,?,?,?)",
            (uid, amount, "pending", str(datetime.now()))
        )
        await db.commit()

# ================= PAYOS =================

def create_payos_payment(order_id, amount):
    data = {
        "orderCode": order_id,
        "amount": amount,
        "description": "Xac minh danh tinh rut tien"
    }
    raw = json.dumps(data, separators=(",", ":"))
    sign = hmac.new(PAYOS_CHECKSUM_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()

    headers = {
        "x-client-id": PAYOS_CLIENT_ID,
        "x-api-key": PAYOS_API_KEY,
        "x-signature": sign,
        "Content-Type": "application/json"
    }
    r = requests.post(
        "https://api-merchant.payos.vn/v2/payment-requests",
        headers=headers,
        data=raw
    )
    return r.json()

@app.post("/payos")
async def payos_webhook(req: Request):
    data = await req.json()
    if data.get("status") == "PAID":
        uid = int(data["orderCode"])
        amount = int(data["amount"])

        # VIP = 100k
        if amount == 100000:
            async with aiosqlite.connect("data.db") as db:
                await db.execute("UPDATE users SET vip=1 WHERE user_id=?", (uid,))
                await db.commit()
            await bot.send_message(uid, "⭐ Bạn đã kích hoạt VIP")
        else:
            async with aiosqlite.connect("data.db") as db:
                await db.execute("""
                UPDATE users 
                SET vnd=vnd+?, total_deposit=total_deposit+?
                WHERE user_id=?
                """, (amount, amount, uid))
                await db.commit()
            await bot.send_message(uid, f"✅ Nạp {amount:,}đ thành công")
    return {"ok": True}

# ================= MENUS =================

def user_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Mời bạn", callback_data="ref")],
        [InlineKeyboardButton(text="⭐ Mua VIP", callback_data="vip")],
        [InlineKeyboardButton(text="🎁 Quay thưởng", callback_data="spin")],
        [InlineKeyboardButton(text="💰 Số dư", callback_data="bal")],
        [InlineKeyboardButton(text="💸 Rút tiền", callback_data="wd")]
    ])

def admin_menu():
    # nút toggle quay thưởng
    spin_txt = "🎁 Quay: ĐANG BẬT" if SPIN_ENABLE else "🎁 Quay: ĐANG TẮT"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Yêu cầu rút", callback_data="admin_withdraw")],
        [InlineKeyboardButton(text="👤 Quản lý user", callback_data="admin_manage")],
        [InlineKeyboardButton(text=spin_txt, callback_data="admin_spin_toggle")],
        [InlineKeyboardButton(text="📊 Thống kê user", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📤 Xuất Excel", callback_data="admin_export")]
    ])

def admin_manage_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Cộng tiền", callback_data="adm_add")],
        [InlineKeyboardButton(text="➖ Trừ tiền", callback_data="adm_del")],
        [InlineKeyboardButton(text="🚫 Khoá user", callback_data="adm_ban"),
         InlineKeyboardButton(text="🔓 Mở khoá", callback_data="adm_unban")],
        [InlineKeyboardButton(text="♻ Reset lượt mời", callback_data="adm_resetref")],
        [InlineKeyboardButton(text="📜 Lịch sử cộng/trừ", callback_data="adm_logs")],
        [InlineKeyboardButton(text="⬅️ Quay lại Admin", callback_data="admin_back")]
    ])

# ================= HELPERS =================

def fmt_user(u):
    # u = (user_id, name, username, vnd, ref_count, vip, total_deposit, banned)
    username = f"@{u[2]}" if u[2] else "(không có username)"
    vip = "Có" if u[5] == 1 else "Không"
    ban = "🚫 BỊ KHOÁ" if u[7] == 1 else "✅ Hoạt động"
    return (
        f"👤 {u[1]}\n"
        f"🆔 {u[0]}\n"
        f"🔗 {username}\n"
        f"💰 Số dư: {u[3]:,}đ\n"
        f"👥 Lượt mời: {u[4]}\n"
        f"⭐ VIP: {vip}\n"
        f"💳 Tổng nạp: {u[6]:,}đ\n"
        f"{ban}"
    )

# ================= START =================

@dp.message(Command("start"))
async def start(m: types.Message):
    await add_user(m.from_user.id, m.from_user.full_name, m.from_user.username)
    u = await get_user(m.from_user.id)

    # nếu bị khoá
    if u and u[7] == 1 and m.from_user.id not in ADMINS:
        await m.answer("🚫 Tài khoản của bạn đã bị khoá.")
        return

    # referral
    if len(m.text.split()) > 1:
        try:
            ref = int(m.text.split()[1])
        except:
            ref = None

        if ref and ref != m.from_user.id:
            # thưởng theo VIP của người mời
            async with aiosqlite.connect("data.db") as db:
                cur = await db.execute("SELECT vip FROM users WHERE user_id=?", (ref,))
                row = await cur.fetchone()
                vip = row[0] if row else 0
                reward = 100000 if vip == 1 else 50000

                await db.execute("""
                UPDATE users SET vnd=vnd+?, ref_count=ref_count+1
                WHERE user_id=?
                """, (reward, ref))
                await db.commit()

    if m.from_user.id in ADMINS:
        await m.answer("👑 ADMIN PANEL", reply_markup=admin_menu())
    else:
        await m.answer("🤖 BOT KIẾM TIỀN", reply_markup=user_menu())

# ================= CALLBACK =================

@dp.callback_query()
async def call(c: types.CallbackQuery):
    uid = c.from_user.id
    u = await get_user(uid)

    # chặn user bị khoá (trừ admin)
    if u and u[7] == 1 and uid not in ADMINS:
        await c.message.answer("🚫 Tài khoản đã bị khoá.")
        return

    # ===== USER =====

    if c.data == "ref":
        link = f"https://t.me/{BOT_USERNAME}?start={uid}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Sao chép link", callback_data="copy_ref")],
            [InlineKeyboardButton(text="🧾 Lấy QR", callback_data="qr_ref")]
        ])
        await c.message.edit_text(
            f"👥 LINK MỜI\n{link}\n+50.000đ / người (VIP: 100.000đ/người)",
            reply_markup=kb
        )

    if c.data == "copy_ref":
        await c.message.answer(f"https://t.me/{BOT_USERNAME}?start={uid}")

    if c.data == "qr_ref":
        link = f"https://t.me/{BOT_USERNAME}?start={uid}"
        qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={link}"
        await c.message.answer_photo(qr, caption="🧾 QR mời bạn")

    if c.data == "bal":
        # u index: 3=vnd, 4=ref_count, 5=vip, 6=total_deposit
        await c.message.edit_text(
            f"💰 {u[3]:,}đ\n"
            f"👥 Đã mời: {u[4]} người\n"
            f"⭐ VIP: {'Có' if u[5]==1 else 'Không'}\n"
            f"💳 Tổng nạp: {u[6]:,}đ"
        )

    if c.data == "vip":
        pay = create_payos_payment(uid, 100000)
        url = pay.get("data", {}).get("checkoutUrl")
        if not url:
            await c.message.answer("❌ Lỗi tạo link VIP (PayOS).")
        else:
            await c.message.edit_text(
                f"⭐ VIP 100.000đ\n"
                f"Quyền lợi: mời 1 người = 100.000đ\n\n{url}"
            )

    if c.data == "spin":
        global SPIN_ENABLE
        if not SPIN_ENABLE:
            await c.message.answer("🎁 Quay thưởng chưa mở.")
        else:
            prize = random.choice([5000, 10000, 20000, 30000, 50000])
            await add_money(uid, prize)
            await c.message.answer(f"🎉 Bạn trúng {prize:,}đ")

    if c.data == "wd":
        await c.message.edit_text("💸 Nhập số tiền muốn rút:")
        USER_STEP[uid] = "withdraw"

    # ===== ADMIN =====

    if uid in ADMINS and c.data == "admin_back":
        await c.message.edit_text("👑 ADMIN PANEL", reply_markup=admin_menu())

    if uid in ADMINS and c.data == "admin_spin_toggle":
        SPIN_ENABLE = not SPIN_ENABLE
        await c.message.edit_text("👑 ADMIN PANEL", reply_markup=admin_menu())

    if uid in ADMINS and c.data == "admin_manage":
        ADMIN_STEP[uid] = {"mode": "await_uid"}
        await c.message.edit_text("👤 Nhập ID user cần quản lý:")

    if uid in ADMINS and c.data == "admin_withdraw":
        async with aiosqlite.connect("data.db") as db:
            cur = await db.execute("SELECT * FROM withdraw WHERE status='pending'")
            rows = await cur.fetchall()

        if not rows:
            await c.message.edit_text("✅ Không có yêu cầu rút.")
            return

        await c.message.edit_text(f"📥 Có {len(rows)} yêu cầu rút (đã gửi ra chat).")
        for wid, u2, amt, st in rows:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Duyệt", callback_data=f"ok_{wid}"),
                 InlineKeyboardButton(text="❌ Từ chối", callback_data=f"no_{wid}")]
            ])
            await bot.send_message(
                uid,
                f"#{wid} | User {u2} | {amt:,}đ",
                reply_markup=kb
            )

    if uid in ADMINS and c.data.startswith("ok_"):
        wid = int(c.data.split("_")[1])
        async with aiosqlite.connect("data.db") as db:
            await db.execute("UPDATE withdraw SET status='approved' WHERE id=?", (wid,))
            await db.execute("""
            UPDATE withdraw_logs SET status=?, time=?
            WHERE id = (SELECT id FROM withdraw_logs ORDER BY id DESC LIMIT 1)
            """, ("approved", str(datetime.now())))
            await db.commit()
        await c.message.edit_text("✅ Đã duyệt.")

    if uid in ADMINS and c.data.startswith("no_"):
        wid = int(c.data.split("_")[1])
        async with aiosqlite.connect("data.db") as db:
            await db.execute("UPDATE withdraw SET status='rejected' WHERE id=?", (wid,))
            await db.execute("""
            UPDATE withdraw_logs SET status=?, time=?
            WHERE id = (SELECT id FROM withdraw_logs ORDER BY id DESC LIMIT 1)
            """, ("rejected", str(datetime.now())))
            await db.commit()
        await c.message.edit_text("❌ Đã từ chối.")

    if uid in ADMINS and c.data == "admin_stats":
        async with aiosqlite.connect("data.db") as db:
            cur = await db.execute("""
            SELECT user_id,name,username,vnd,ref_count,vip,total_deposit,banned
            FROM users ORDER BY vnd DESC LIMIT 15
            """)
            rows = await cur.fetchall()

        text = "📊 TOP USER\n\n"
        for r in rows:
            username = f"@{r[2]}" if r[2] else "-"
            text += f"{r[1]} ({username})\nID:{r[0]}\n💰{r[3]:,}đ | 👥{r[4]} | VIP:{'Y' if r[5]==1 else 'N'} | Nạp:{r[6]:,}đ\n\n"
        await c.message.edit_text(text)

    if uid in ADMINS and c.data == "admin_export":
        wb = Workbook()
        ws = wb.active
        ws.append(["ID","Name","Username","Money","Ref","VIP","TotalDeposit","Banned"])
        async with aiosqlite.connect("data.db") as db:
            cur = await db.execute("""
            SELECT user_id,name,username,vnd,ref_count,vip,total_deposit,banned FROM users
            """)
            rows = await cur.fetchall()
        for r in rows:
            ws.append(list(r))
        path = "users.xlsx"
        wb.save(path)
        await bot.send_document(uid, types.FSInputFile(path))

    # admin manage actions
    if uid in ADMINS and c.data in ["adm_add","adm_del","adm_ban","adm_unban","adm_resetref","adm_logs"]:
        st = ADMIN_STEP.get(uid)
        if not st or "target" not in st:
            await c.message.answer("⚠️ Chưa chọn user. Bấm 'Quản lý user' và nhập ID trước.")
            return

        target = st["target"]
        tu = await get_user(target)
        if not tu:
            await c.message.answer("❌ User không tồn tại trong DB.")
            return

        if c.data == "adm_add":
            ADMIN_STEP[uid]["mode"] = "add_amount"
            await c.message.edit_text(f"{fmt_user(tu)}\n\n➕ Nhập số tiền cần CỘNG:")

        if c.data == "adm_del":
            ADMIN_STEP[uid]["mode"] = "del_amount"
            await c.message.edit_text(f"{fmt_user(tu)}\n\n➖ Nhập số tiền cần TRỪ:")

        if c.data == "adm_ban":
            await set_ban(target, 1)
            await c.message.edit_text("🚫 Đã khoá user.")

        if c.data == "adm_unban":
            await set_ban(target, 0)
            await c.message.edit_text("🔓 Đã mở khoá user.")

        if c.data == "adm_resetref":
            await reset_ref(target)
            await c.message.edit_text("♻ Đã reset lượt mời.")

        if c.data == "adm_logs":
            async with aiosqlite.connect("data.db") as db:
                cur = await db.execute("""
                SELECT amount,action,time,admin_id
                FROM money_logs
                WHERE user_id=?
                ORDER BY id DESC LIMIT 20
                """, (target,))
                rows = await cur.fetchall()
            if not rows:
                await c.message.edit_text("📜 Không có lịch sử cộng/trừ.")
            else:
                txt = "📜 Lịch sử cộng/trừ (20 dòng gần nhất)\n\n"
                for amt, act, t, ad in rows:
                    txt += f"{t} | {act} {amt:,}đ | admin:{ad}\n"
                await c.message.edit_text(txt)

# ================= MESSAGE =================

@dp.message()
async def steps(m: types.Message):
    uid = m.from_user.id

    # chặn user bị khoá
    u = await get_user(uid)
    if u and u[7] == 1 and uid not in ADMINS:
        return

    # ===== USER withdraw input =====
    if uid in USER_STEP and USER_STEP[uid] == "withdraw":
        if not m.text.isdigit():
            await m.answer("Nhập số hợp lệ.")
            return

        amount = int(m.text)
        u = await get_user(uid)

        # điều kiện rút: đã nạp tối thiểu 50k + đủ số dư
        if u[6] < 50000:
            await m.answer("❌ Cần nạp tối thiểu 50.000đ mới được rút.")
            return
        if u[3] < amount:
            await m.answer("❌ Số dư không đủ.")
            return

        await create_withdraw(uid, amount)
        for ad in ADMINS:
            await bot.send_message(ad, f"💸 User {uid} yêu cầu rút {amount:,}đ")
        await m.answer("⏳ Đã gửi yêu cầu rút, chờ admin duyệt.")
        USER_STEP.pop(uid, None)
        return

    # ===== ADMIN manage flow =====
    if uid in ADMINS and uid in ADMIN_STEP:
        st = ADMIN_STEP[uid]
        mode = st.get("mode")

        # nhập user id
        if mode == "await_uid":
            if not m.text.isdigit():
                await m.answer("Nhập ID số hợp lệ.")
                return
            target = int(m.text)
            tu = await get_user(target)
            if not tu:
                await m.answer("❌ User chưa có trong DB (user phải /start trước).")
                return

            ADMIN_STEP[uid] = {"mode": "choose_action", "target": target}
            await m.answer(f"{fmt_user(tu)}\n\nChọn hành động:", reply_markup=admin_manage_menu())
            return

        # cộng tiền
        if mode == "add_amount":
            if not m.text.isdigit():
                await m.answer("Nhập số tiền hợp lệ.")
                return
            amount = int(m.text)
            target = st["target"]

            await add_money(target, amount)
            await log_money(uid, target, amount, "ADD")
            await m.answer(f"✅ Đã cộng {amount:,}đ cho user {target}.")
            try:
                await bot.send_message(target, f"💰 Bạn được admin cộng {amount:,}đ")
            except:
                pass
            ADMIN_STEP.pop(uid, None)
            return

        # trừ tiền
        if mode == "del_amount":
            if not m.text.isdigit():
                await m.answer("Nhập số tiền hợp lệ.")
                return
            amount = int(m.text)
            target = st["target"]

            await del_money(target, amount)
            await log_money(uid, target, amount, "DEL")
            await m.answer(f"✅ Đã trừ {amount:,}đ của user {target}.")
            try:
                await bot.send_message(target, f"⚠️ Bạn bị admin trừ {amount:,}đ")
            except:
                pass
            ADMIN_STEP.pop(uid, None)
            return

# ================= RUN =================

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=8000)

async def main():
    await init_db()
    threading.Thread(target=run_api).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
