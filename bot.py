import os, re, sqlite3, logging, tempfile, requests
from pathlib import Path
from datetime import datetime
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# === CONFIG ===
BOT_TOKEN = os.getenv("8308640371:AAG4S29NebM6oZrfZClGvsCcPh4nj6xghho")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://thewallet-ai-t78i.onrender.com")

DB_PATH = Path("wallet.db")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === DATABASE ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        tg_id INTEGER UNIQUE,
        username TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS wallets (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        name TEXT,
        currency TEXT,
        balance REAL DEFAULT 0,
        created_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        wallet_id INTEGER,
        created_at TEXT,
        amount REAL,
        currency TEXT,
        category TEXT,
        description TEXT,
        source TEXT,
        raw_text TEXT
    )
    """)
    conn.commit()
    conn.close()


def add_user(tg_id, username):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users(tg_id, username) VALUES (?,?)", (tg_id, username))
    conn.commit()
    conn.close()


# === CURRENCY ===
def get_rate(from_cur: str, to_cur: str):
    if from_cur == to_cur:
        return 1.0
    url = f"https://api.exchangerate.host/convert?from={from_cur}&to={to_cur}"
    try:
        data = requests.get(url, timeout=5).json()
        return data.get("info", {}).get("rate", 1.0)
    except Exception as e:
        logger.warning(f"Rate fetch failed: {e}")
        return 1.0


# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username)
    webapp = WebAppInfo(url=WEBAPP_URL)
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("Открыть The Wallet", web_app=webapp)]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "👋 Добро пожаловать в The Wallet!\n"
        "Ты можешь вести неограниченное количество кошельков, "
        "в разных валютах, и переводить между ними 💱",
        reply_markup=kb
    )


async def add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /addwallet <название> <валюта>\nПример: /addwallet Карта USD")
        return
    name, currency = args[0], args[1].upper()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id=?", (update.effective_user.id,))
    user_id = cur.fetchone()[0]
    cur.execute("INSERT INTO wallets(user_id,name,currency,created_at) VALUES(?,?,?,?)",
                (user_id, name, currency, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Кошелёк '{name}' ({currency}) создан.")


async def show_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT w.name, w.currency, ROUND(w.balance,2)
        FROM wallets w
        JOIN users u ON u.id=w.user_id
        WHERE u.tg_id=?
    """, (update.effective_user.id,))
    wallets = cur.fetchall()
    conn.close()
    if not wallets:
        await update.message.reply_text("💼 Кошельков пока нет.\nСоздай: /addwallet Название Валюта")
        return
    text = "\n".join([f"💰 {n}: {b} {c}" for (n, c, b) in wallets])
    await update.message.reply_text(f"Твои кошельки:\n{text}")


async def transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Использование: /transfer <из> <в> <сумма>\nПример: /transfer Карта Наличные 100")
        return
    from_name, to_name, amount = args[0], args[1], float(args[2])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id,currency,balance FROM wallets WHERE name=? AND user_id=(SELECT id FROM users WHERE tg_id=?)",
                (from_name, update.effective_user.id))
    from_w = cur.fetchone()
    cur.execute("SELECT id,currency,balance FROM wallets WHERE name=? AND user_id=(SELECT id FROM users WHERE tg_id=?)",
                (to_name, update.effective_user.id))
    to_w = cur.fetchone()

    if not from_w or not to_w:
        await update.message.reply_text("❌ Один из кошельков не найден.")
        conn.close()
        return

    from_id, from_cur, from_bal = from_w
    to_id, to_cur, to_bal = to_w

    if from_bal < amount:
        await update.message.reply_text("Недостаточно средств.")
        conn.close()
        return

    rate = get_rate(from_cur, to_cur)
    converted = amount * rate

    new_from = from_bal - amount
    new_to = to_bal + converted
    cur.execute("UPDATE wallets SET balance=? WHERE id=?", (new_from, from_id))
    cur.execute("UPDATE wallets SET balance=? WHERE id=?", (new_to, to_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Перевод выполнен!\n"
        f"{amount} {from_cur} → {round(converted,2)} {to_cur}\n"
        f"Курс: {round(rate,2)}"
    )


def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addwallet", add_wallet))
    app.add_handler(CommandHandler("wallets", show_wallets))
    app.add_handler(CommandHandler("transfer", transfer))
    logger.info("🚀 The Wallet Bot запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
