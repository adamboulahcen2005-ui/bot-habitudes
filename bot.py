# -*- coding: utf-8 -*-
"""
Bot Telegram - Suivi quotidien d'habitudes avec système de points
===================================================================
Fonctionnalités :
- Inscription des participants (/start)
- Rappel automatique chaque soir à 21h00 (heure Maroc) avec bouton pour voter
- Sondage interactif en 4 étapes : Sobh, Salawat, Qiyam, Wird
- Anti-doublon : impossible de voter deux fois le même jour
- Classement du jour (/classement) et de la semaine (/classement_semaine)
- Export Excel à la demande, réservé aux admins (/export)
- Toutes les données sont stockées de façon persistante dans SQLite (habitudes.db)
"""

import asyncio
import logging
import sqlite3
from datetime import datetime, date, timedelta, time as dt_time
from zoneinfo import ZoneInfo

import pandas as pd
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# CONFIGURATION - à personnaliser avant de lancer le bot
# ---------------------------------------------------------------------------
BOT_TOKEN = "8010071360:AAEWLgFMK7xQ2ZUlruwKjmTWQ6RivaVFD74"

# Liste des identifiants Telegram (numériques) des administrateurs,
# qui seuls peuvent utiliser /export. Pour connaître ton ID, écris à
# @userinfobot sur Telegram.
ADMIN_IDS = [6863295439]

TIMEZONE = ZoneInfo("Africa/Casablanca")
DB_PATH = "habitudes.db"
HEURE_RAPPEL = dt_time(hour=21, minute=0, tzinfo=TIMEZONE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# États de la conversation du sondage quotidien
SOBH, SALAWAT, QIYAM, WIRD = range(4)

# ---------------------------------------------------------------------------
# BARÈME DE POINTS (repris exactement de ton modèle)
# ---------------------------------------------------------------------------
BAREME = {
    "sobh": {
        "sobh_jamaa": ("في الجماعة (+10)", 10),
        "sobh_waqt": ("في الوقت (-5)", -5),
        "sobh_kharij": ("خارج الوقت (-10)", -10),
    },
    "salawat": {
        "sal_4": ("4 صلوات (+10)", 10),
        "sal_3": ("3 صلوات (+5)", 5),
        "sal_2": ("صلاتان (0)", 0),
        "sal_1": ("صلاة واحدة (-5)", -5),
        "sal_0": ("ولا صلاة (-10)", -10),
    },
    "qiyam": {
        "qiyam_20p": ("أكثر من 20 دقيقة (+20)", 20),
        "qiyam_15": ("15-20 دقيقة (+15)", 15),
        "qiyam_10": ("10-15 دقيقة (+10)", 10),
        "qiyam_5": ("5-10 دقائق (+5)", 5),
        "qiyam_0": ("لم أقم (-10)", -10),
    },
    "wird": {
        "wird_plus": ("أكثر من حزب (+20)", 20),
        "wird_hizb": ("حزب (+10)", 10),
        "wird_half": ("نصف حزب (+5)", 5),
        "wird_0": ("لم أقرأ (-10)", -10),
    },
}

LABELS = {
    "sobh": "🕌 صلاة الفجر",
    "salawat": "🕋 الصلوات في جماعة",
    "qiyam": "🌙 القيام",
    "wird": "📖 ورد القرآن",
}

# ---------------------------------------------------------------------------
# BASE DE DONNÉES
# ---------------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            registered_at TEXT NOT NULL
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            sobh_key TEXT, sobh_pts INTEGER,
            salawat_key TEXT, salawat_pts INTEGER,
            qiyam_key TEXT, qiyam_pts INTEGER,
            wird_key TEXT, wird_pts INTEGER,
            total INTEGER,
            UNIQUE(user_id, date)
        )"""
    )
    conn.commit()
    conn.close()


def today_str():
    return datetime.now(TIMEZONE).date().isoformat()


def has_voted_today(user_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM responses WHERE user_id=? AND date=?",
        (user_id, today_str()),
    ).fetchone()
    conn.close()
    return row is not None


def save_response(user_id, data):
    total = data["sobh_pts"] + data["salawat_pts"] + data["qiyam_pts"] + data["wird_pts"]
    conn = get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO responses
        (user_id, date, sobh_key, sobh_pts, salawat_key, salawat_pts,
         qiyam_key, qiyam_pts, wird_key, wird_pts, total)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            user_id,
            today_str(),
            data["sobh_key"], data["sobh_pts"],
            data["salawat_key"], data["salawat_pts"],
            data["qiyam_key"], data["qiyam_pts"],
            data["wird_key"], data["wird_pts"],
            total,
        ),
    )
    conn.commit()
    conn.close()
    return total


def register_user(user_id, name):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO users (user_id, name, registered_at) VALUES (?,?,?)",
        (user_id, name, datetime.now(TIMEZONE).isoformat()),
    )
    conn.commit()
    conn.close()


def get_all_users():
    conn = get_conn()
    rows = conn.execute("SELECT user_id, name FROM users").fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# MENUS (claviers inline)
# ---------------------------------------------------------------------------
def build_menu(step_key):
    keyboard = [
        [InlineKeyboardButton(label, callback_data=key)]
        for key, (label, pts) in BAREME[step_key].items()
    ]
    return InlineKeyboardMarkup(keyboard)


# ---------------------------------------------------------------------------
# INSCRIPTION
# ---------------------------------------------------------------------------
ASK_NAME = 100


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_conn()
    row = conn.execute("SELECT name FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if row:
        await update.message.reply_text(
            f"مرحبا بعودتك {row['name']} 👋\nاستعمل /vote للتصويت اليومي أو /aide لعرض الأوامر."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "مرحبا بك 👋 من فضلك أرسل اسمك الكامل حتى نسجلك في اللائحة:"
    )
    return ASK_NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    register_user(update.effective_user.id, name)
    await update.message.reply_text(
        f"تم تسجيلك بنجاح، {name} ✅\n\n"
        "الأوامر المتاحة:\n"
        "/vote - للتصويت اليومي\n"
        "/classement - ترتيب اليوم\n"
        "/classement_semaine - ترتيب الأسبوع\n"
        "/aide - عرض هذه القائمة"
    )
    return ConversationHandler.END


async def aide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "الأوامر المتاحة:\n"
        "/start - التسجيل\n"
        "/vote - التصويت اليومي\n"
        "/classement - ترتيب اليوم\n"
        "/classement_semaine - ترتيب الأسبوع\n"
        + ("/export - تصدير Excel (للمشرفين)\n" if True else "")
    )


# ---------------------------------------------------------------------------
# SONDAGE QUOTIDIEN (ConversationHandler)
# ---------------------------------------------------------------------------
async def vote_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Point d'entrée via la commande /vote OU via le bouton du rappel automatique."""
    query = update.callback_query
    user_id = update.effective_user.id

    conn = get_conn()
    is_registered = conn.execute(
        "SELECT 1 FROM users WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()

    if not is_registered:
        text = "من فضلك سجل نفسك أولا عبر /start"
        if query:
            await query.answer()
            await query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    if has_voted_today(user_id):
        text = "لقد سجلت إجابتك اليوم بالفعل ✅ عد غدا إن شاء الله."
        if query:
            await query.answer()
            await query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    context.user_data["reponses"] = {}

    text = f"{LABELS['sobh']} - اختر حالتك اليوم:"
    markup = build_menu("sobh")
    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)
    return SOBH


async def handle_sobh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data
    label, pts = BAREME["sobh"][key]
    context.user_data["reponses"]["sobh_key"] = key
    context.user_data["reponses"]["sobh_pts"] = pts

    await query.edit_message_text(
        f"{LABELS['salawat']} - اختر حالتك اليوم:",
        reply_markup=build_menu("salawat"),
    )
    return SALAWAT


async def handle_salawat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data
    label, pts = BAREME["salawat"][key]
    context.user_data["reponses"]["salawat_key"] = key
    context.user_data["reponses"]["salawat_pts"] = pts

    await query.edit_message_text(
        f"{LABELS['qiyam']} - اختر حالتك اليوم:",
        reply_markup=build_menu("qiyam"),
    )
    return QIYAM


async def handle_qiyam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data
    label, pts = BAREME["qiyam"][key]
    context.user_data["reponses"]["qiyam_key"] = key
    context.user_data["reponses"]["qiyam_pts"] = pts

    await query.edit_message_text(
        f"{LABELS['wird']} - اختر حالتك اليوم:",
        reply_markup=build_menu("wird"),
    )
    return WIRD


async def handle_wird(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data
    label, pts = BAREME["wird"][key]
    context.user_data["reponses"]["wird_key"] = key
    context.user_data["reponses"]["wird_pts"] = pts

    total = save_response(update.effective_user.id, context.user_data["reponses"])

    await query.edit_message_text(
        f"✅ تم تسجيل إجاباتك لهذا اليوم.\nمجموع نقاط اليوم: {total}\n\n"
        "بارك الله فيك، إلى الغد بإذن الله."
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.")
    context.user_data.clear()
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# RAPPEL AUTOMATIQUE QUOTIDIEN
# ---------------------------------------------------------------------------
async def envoyer_rappel(context: ContextTypes.DEFAULT_TYPE):
    """Envoie le rappel du soir à tous les inscrits, en espaçant les envois
    pour rester sous la limite de débit de Telegram (~30 messages/seconde),
    quel que soit le nombre de participants (30, 300, ou plus)."""
    users = get_all_users()
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🗳️ ابدأ التصويت اليومي", callback_data="__start_vote__")]]
    )
    DELAI_ENTRE_ENVOIS = 0.05  # 20 messages/seconde -> marge de sécurité sous la limite Telegram

    envoyes, echecs = 0, 0
    for u in users:
        if has_voted_today(u["user_id"]):
            continue
        try:
            await context.bot.send_message(
                chat_id=u["user_id"],
                text=f"🌙 السلام عليكم {u['name']}، حان وقت تسجيل يومك:",
                reply_markup=keyboard,
            )
            envoyes += 1
        except Exception as e:
            echecs += 1
            logger.warning("Impossible d'envoyer le rappel à %s : %s", u["user_id"], e)
        await asyncio.sleep(DELAI_ENTRE_ENVOIS)

    logger.info("Rappel quotidien : %s envoyés, %s échecs sur %s inscrits", envoyes, echecs, len(users))


# ---------------------------------------------------------------------------
# CLASSEMENTS
# ---------------------------------------------------------------------------
async def classement_jour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    rows = conn.execute(
        """SELECT u.name, r.total FROM responses r
           JOIN users u ON u.user_id = r.user_id
           WHERE r.date = ? ORDER BY r.total DESC""",
        (today_str(),),
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("لا توجد إجابات مسجلة اليوم بعد.")
        return

    lignes = [f"{i+1}. {r['name']} — {r['total']} نقطة" for i, r in enumerate(rows)]
    await update.message.reply_text("🏆 ترتيب اليوم:\n\n" + "\n".join(lignes))


async def classement_semaine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_debut = (datetime.now(TIMEZONE).date() - timedelta(days=6)).isoformat()
    conn = get_conn()
    rows = conn.execute(
        """SELECT u.name, SUM(r.total) as total FROM responses r
           JOIN users u ON u.user_id = r.user_id
           WHERE r.date >= ?
           GROUP BY u.name ORDER BY total DESC""",
        (date_debut,),
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("لا توجد إجابات مسجلة هذا الأسبوع بعد.")
        return

    lignes = [f"{i+1}. {r['name']} — {r['total']} نقطة" for i, r in enumerate(rows)]
    await update.message.reply_text("🏆 ترتيب الأسبوع:\n\n" + "\n".join(lignes))


# ---------------------------------------------------------------------------
# EXPORT EXCEL (admins uniquement)
# ---------------------------------------------------------------------------
async def export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("هذا الأمر مخصص للمشرفين فقط.")
        return

    conn = get_conn()
    df = pd.read_sql_query(
        """SELECT u.name AS Nom, r.date AS Date,
                  r.sobh_pts AS Sobh, r.salawat_pts AS Salawat,
                  r.qiyam_pts AS Qiyam, r.wird_pts AS Wird, r.total AS Total
           FROM responses r JOIN users u ON u.user_id = r.user_id
           ORDER BY r.date, u.name""",
        conn,
    )
    conn.close()

    if df.empty:
        await update.message.reply_text("لا توجد بيانات للتصدير بعد.")
        return

    fichier = f"Classement_{today_str()}.xlsx"
    with pd.ExcelWriter(fichier, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Détail quotidien", index=False)
        resume = df.groupby("Nom")["Total"].sum().sort_values(ascending=False).reset_index()
        resume.to_excel(writer, sheet_name="Classement total", index=False)

    await update.message.reply_document(document=open(fichier, "rb"), filename=fichier)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Inscription
    reg_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Sondage quotidien (déclenché par /vote OU par le bouton du rappel)
    vote_handler = ConversationHandler(
        entry_points=[
            CommandHandler("vote", vote_entry),
            CallbackQueryHandler(vote_entry, pattern="^__start_vote__$"),
        ],
        states={
            SOBH: [CallbackQueryHandler(handle_sobh, pattern="^sobh_")],
            SALAWAT: [CallbackQueryHandler(handle_salawat, pattern="^sal_")],
            QIYAM: [CallbackQueryHandler(handle_qiyam, pattern="^qiyam_")],
            WIRD: [CallbackQueryHandler(handle_wird, pattern="^wird_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(reg_handler)
    app.add_handler(vote_handler)
    app.add_handler(CommandHandler("aide", aide))
    app.add_handler(CommandHandler("classement", classement_jour))
    app.add_handler(CommandHandler("classement_semaine", classement_semaine))
    app.add_handler(CommandHandler("export", export_excel))

    # Rappel automatique chaque soir à 21h00 (heure Maroc)
    app.job_queue.run_daily(envoyer_rappel, time=HEURE_RAPPEL)

    logger.info("Bot démarré, en attente...")
    app.run_polling()


if __name__ == "__main__":
    main()
