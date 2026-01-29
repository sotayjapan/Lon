import asyncio, random
import aiosqlite
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from openpyxl import Workbook

# ================= CONFIG =================

TOKEN = "7840725448:AAF8bHPcIfbz_Hvo_dT58pyFOIbFd9XeP8U"
BOT_USERNAME = "CTY_MIMEDIA_BOT"
ADMINS = [7316498621]

VIP_QR = "https://raw.githubusercontent.com/sotayjapan/Lon/main/qr.jpg"
VIP_NOTE = "VIP RUT TIEN M&I"

VIP_REWARD = {
    1:15999000,
    2:8999000,
    3:3999000,
    4:1888000,
    5:888000,
    6:377000,
    7:170000,
    8:70000
}

SPIN_ENABLE = False

bot = Bot(TOKEN)
dp = Dispatcher()

USER_STEP = {}
ADMIN_STEP = {}

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
            vip_level INTEGER DEFAULT 0,
            vip_time TEXT,
            banned INTEGER DEFAULT 0
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS withdraw_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            time TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS vip_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            vip_level INTEGER,
            time TEXT
        )
        """)
        await db.commit()

# ================= MENUS =================

def user_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Mua VIP",callback_data="vip")],
        [InlineKeyboardButton(text="👥 Mời bạn",callback_data="ref")],
        [InlineKeyboardButton(text="🎁 Quay thưởng",callback_data="spin")],
        [InlineKeyboardButton(text="💰 Số dư",callback_data="bal")],
        [InlineKeyboardButton(text="💸 Rút tiền",callback_data="wd")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Duyệt VIP",callback_data="admin_vip")],
        [InlineKeyboardButton(text="📥 Duyệt rút",callback_data="admin_wd")],
        [InlineKeyboardButton(text="🎁 Bật/Tắt quay",callback_data="admin_spin")],
        [InlineKeyboardButton(text="📤 Xuất Excel",callback_data="admin_export")]
    ])

# ================= START =================

@dp.message(Command("start"))
async def start(m):
    async with aiosqlite.connect("data.db") as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id,name,username) VALUES(?,?,?)",
            (m.from_user.id,m.from_user.full_name,m.from_user.username)
        )
        await db.commit()

    if m.from_user.id in ADMINS:
        await m.answer("👑 ADMIN PANEL",reply_markup=admin_menu())
    else:
        await m.answer("🤖 BOT KIẾM TIỀN",reply_markup=user_menu())

# ================= CALLBACK =================

@dp.callback_query()
async def call(c):
    uid=c.from_user.id

    # ===== VIP =====
    if c.data=="vip":
        await c.message.answer_photo(
            VIP_QR,
            caption=f"Quét QR mua VIP\nNội dung: {VIP_NOTE}\nSau khi chuyển bấm: Tôi đã chuyển",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Tôi đã chuyển",callback_data="vip_done")]]
            )
        )

    if c.data=="vip_done":
        for ad in ADMINS:
            await bot.send_message(ad,f"User {uid} báo đã nạp VIP")
        await c.message.answer("⏳ Đã gửi admin duyệt")

    # ===== BAL =====
    if c.data=="bal":
        async with aiosqlite.connect("data.db") as db:
            cur=await db.execute("SELECT vnd,vip,vip_level FROM users WHERE user_id=?", (uid,))
            vnd,vip,vl=await cur.fetchone()
        await c.message.edit_text(
            f"💰 Số dư: {vnd:,}đ\n⭐ VIP: {'VIP'+str(vl) if vip else 'Không'}"
        )

    # ===== REF =====
    if c.data=="ref":
        link=f"https://t.me/{BOT_USERNAME}?start={uid}"
        await c.message.edit_text(f"👥 Link mời:\n{link}\n+50.000đ / người")

    # ===== SPIN =====
    if c.data=="spin":
        if not SPIN_ENABLE:
            await c.message.answer("Quay chưa mở")
        else:
            prize=random.choice([5000,10000,20000,50000])
            async with aiosqlite.connect("data.db") as db:
                await db.execute("UPDATE users SET vnd=vnd+? WHERE user_id=?", (prize,uid))
                await db.commit()
            await c.message.answer(f"🎉 Trúng {prize:,}đ")

    # ===== WITHDRAW =====
    if c.data=="wd":
        async with aiosqlite.connect("data.db") as db:
            cur=await db.execute("SELECT vip FROM users WHERE user_id=?", (uid,))
            vip=await cur.fetchone()
        if vip[0]==0:
            await c.message.answer("❌ Phải có VIP mới rút được")
            return
        USER_STEP[uid]="wd"
        await c.message.answer("Nhập số tiền muốn rút")

    # ===== ADMIN =====
    if uid in ADMINS and c.data=="admin_vip":
        USER_STEP[uid]="admin_vip_uid"
        await c.message.answer("Nhập ID user cần cấp VIP")

    if uid in ADMINS and c.data=="admin_spin":
        global SPIN_ENABLE
        SPIN_ENABLE=not SPIN_ENABLE
        await c.message.answer("Đã đổi trạng thái quay")

    if uid in ADMINS and c.data=="admin_wd":
        await c.message.answer("Xem lịch sử rút trong database")

    if uid in ADMINS and c.data=="admin_export":
        wb=Workbook()
        ws=wb.active
        ws.append(["ID","Name","Username","Money","VIP","Level"])
        async with aiosqlite.connect("data.db") as db:
            cur=await db.execute("SELECT user_id,name,username,vnd,vip,vip_level FROM users")
            rows=await cur.fetchall()
        for r in rows:
            ws.append(r)
        wb.save("users.xlsx")
        await bot.send_document(uid,types.FSInputFile("users.xlsx"))

# ================= MESSAGE =================

@dp.message()
async def steps(m):
    uid=m.from_user.id

    # USER WITHDRAW
    if USER_STEP.get(uid)=="wd":
        amount=int(m.text)
        async with aiosqlite.connect("data.db") as db:
            await db.execute(
                "INSERT INTO withdraw_logs(user_id,amount,time) VALUES(?,?,?)",
                (uid,amount,str(datetime.now()))
            )
            await db.commit()
        for ad in ADMINS:
            await bot.send_message(ad,f"💸 User {uid} yêu cầu rút {amount:,}đ")
        await m.answer("⏳ Đã gửi yêu cầu rút")
        USER_STEP.pop(uid)

    # ADMIN VIP
    if USER_STEP.get(uid)=="admin_vip_uid":
        target=int(m.text)
        USER_STEP[uid]="admin_vip_level"
        ADMIN_STEP[uid]=target
        await m.answer("Nhập cấp VIP (1-8)")

    if USER_STEP.get(uid)=="admin_vip_level":
        level=int(m.text)
        reward=VIP_REWARD.get(level,0)
        async with aiosqlite.connect("data.db") as db:
            await db.execute("""
            UPDATE users 
            SET vip=1,vip_level=?,vnd=vnd+?,vip_time=?
            WHERE user_id=?
            """,(level,reward,str(datetime.now()),ADMIN_STEP[uid]))
            await db.execute(
                "INSERT INTO vip_logs(user_id,vip_level,time) VALUES(?,?,?)",
                (ADMIN_STEP[uid],level,str(datetime.now()))
            )
            await db.commit()
        await m.answer(f"✅ Đã cấp VIP{level} + thưởng {reward:,}đ")
        USER_STEP.pop(uid)
        ADMIN_STEP.pop(uid)

# ================= RUN =================

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
