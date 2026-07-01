"""
Sentio Test Group Bot
----------------------
Регистрирует участниц тестовой группы, ежедневно присылает анкету
(вопросы взяты из Google Form "Відгук по використанню продуктів Sentio"),
напоминает тем, кто не ответил, и позволяет админу (Anna) выгрузить
все ответы в Excel.

Запуск: см. README.md
"""

import logging
import os
import sqlite3
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ["BOT_TOKEN"]  # обязателен
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
TIMEZONE = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Kyiv"))
REMINDER_HOUR = int(os.environ.get("REMINDER_HOUR", "20"))
REMINDER_MINUTE = int(os.environ.get("REMINDER_MINUTE", "0"))
DB_PATH = os.environ.get("DB_PATH", "sentio.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            email TEXT,
            phone TEXT,
            age_group TEXT,
            rollon TEXT,
            registered_at TEXT
        );

        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            response_date TEXT,
            state_change TEXT,
            feelings TEXT,
            effect_time TEXT,
            aroma_rating TEXT,
            usage_freq TEXT,
            experience_text TEXT,
            will_continue TEXT,
            consent TEXT,
            instagram TEXT,
            created_at TEXT,
            FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
        );
        """
    )
    conn.commit()
    conn.close()


def user_exists(telegram_id: int) -> bool:
    conn = db()
    row = conn.execute(
        "SELECT 1 FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row is not None


def save_user(data: dict):
    conn = db()
    conn.execute(
        """INSERT OR REPLACE INTO users
           (telegram_id, username, name, email, phone, age_group, rollon, registered_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["telegram_id"],
            data.get("username", ""),
            data["name"],
            data["email"],
            data["phone"],
            data["age_group"],
            data["rollon"],
            datetime.now(TIMEZONE).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def all_user_ids():
    conn = db()
    rows = conn.execute("SELECT telegram_id FROM users").fetchall()
    conn.close()
    return [r[0] for r in rows]


def already_responded_today(telegram_id: int) -> bool:
    today = datetime.now(TIMEZONE).date().isoformat()
    conn = db()
    row = conn.execute(
        "SELECT 1 FROM responses WHERE telegram_id = ? AND response_date = ?",
        (telegram_id, today),
    ).fetchone()
    conn.close()
    return row is not None


def save_response(telegram_id: int, answers: dict):
    conn = db()
    today = datetime.now(TIMEZONE).date().isoformat()
    conn.execute(
        """INSERT INTO responses
           (telegram_id, response_date, state_change, feelings, effect_time,
            aroma_rating, usage_freq, experience_text, will_continue, consent,
            instagram, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            telegram_id,
            today,
            answers.get("state_change", ""),
            answers.get("feelings", ""),
            answers.get("effect_time", ""),
            answers.get("aroma_rating", ""),
            answers.get("usage_freq", ""),
            answers.get("experience_text", ""),
            answers.get("will_continue", ""),
            answers.get("consent", ""),
            answers.get("instagram", ""),
            datetime.now(TIMEZONE).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Регистрация — состояния
# ---------------------------------------------------------------------------

REG_NAME, REG_EMAIL, REG_PHONE, REG_AGE, REG_ROLLON = range(5)

AGE_OPTIONS = ["до 25", "25–34", "35–44", "45+"]
ROLLON_OPTIONS = [
    "Всі три",
    "Reset - no panic (анти-тривога)",
    "Rise - no noise / morning (фокус / ясність)",
    "Rest - no rush (сон / розслаблення)",
]


def kb(options, prefix):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(o, callback_data=f"{prefix}:{o}")] for o in options]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    if user_exists(tg_id):
        await update.message.reply_text(
            "Ти вже зареєстрована в тестовій групі Sentio 🤍\n"
            "Щодня о 20:00 я нагадаю заповнити анкету. "
            "Хочеш заповнити зараз? Напиши /survey"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Привіт! 🤍 Це тестова група Sentio.\n"
        "Давай зареєструємось — це займе хвилину.\n\n"
        "Як тебе звати?",
        reply_markup=ReplyKeyboardRemove(),
    )
    return REG_NAME


async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Твій e-mail?")
    return REG_EMAIL


async def reg_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["email"] = update.message.text.strip()
    await update.message.reply_text("Твій телефон?")
    return REG_PHONE


async def reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("Твій вік?", reply_markup=kb(AGE_OPTIONS, "age"))
    return REG_AGE


async def reg_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["age_group"] = q.data.split(":", 1)[1]
    await q.edit_message_text(f"Вік: {context.user_data['age_group']}")
    await q.message.reply_text(
        "Який рол-он ти тестуєш?", reply_markup=kb(ROLLON_OPTIONS, "rollon")
    )
    return REG_ROLLON


async def reg_rollon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["rollon"] = q.data.split(":", 1)[1]
    await q.edit_message_text(f"Рол-он: {context.user_data['rollon']}")

    data = dict(context.user_data)
    data["telegram_id"] = update.effective_user.id
    data["username"] = update.effective_user.username or ""
    save_user(data)

    await q.message.reply_text(
        "Дякуємо, реєстрацію завершено! 🤍\n"
        f"Щодня о {REMINDER_HOUR:02d}:{REMINDER_MINUTE:02d} я надсилатиму коротку анкету "
        "про твої відчуття від рол-она. Це займе 1-2 хвилини.\n\n"
        "Можеш заповнити першу анкету прямо зараз командою /survey"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Скасовано. Напиши /start щоб почати знову.")
    return ConversationHandler.END


registration_conv = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
        REG_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_email)],
        REG_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone)],
        REG_AGE: [CallbackQueryHandler(reg_age, pattern=r"^age:")],
        REG_ROLLON: [CallbackQueryHandler(reg_rollon, pattern=r"^rollon:")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

# ---------------------------------------------------------------------------
# Ежедневная анкета — состояния
# ---------------------------------------------------------------------------

(
    SUR_STATE,
    SUR_FEEL,
    SUR_TIME,
    SUR_AROMA,
    SUR_FREQ,
    SUR_TEXT,
    SUR_CONTINUE,
    SUR_CONSENT,
    SUR_INSTAGRAM,
) = range(10, 19)

STATE_OPTIONS = ["без змін", "1", "2", "3", "4", "5 (сильний ефект)"]
FEEL_OPTIONS = [
    "заспокоєння",
    "менше тривоги",
    "легше заснути",
    "кращий настрій",
    "більше енергії",
    "легше зосередитись",
    "не відчула ефекту",
]
TIME_OPTIONS = ["1–3 хв", "5–10 хв", "10–20 хв", "не відчула"]
AROMA_OPTIONS = ["дуже подобається", "приємний", "нейтральний", "не сподобався"]
FREQ_OPTIONS = ["1–2 рази", "кілька разів", "щодня"]
CONTINUE_OPTIONS = ["так", "можливо", "ні"]
CONSENT_OPTIONS = ["так", "так, без імені", "ні"]


async def survey_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    if not user_exists(tg_id):
        await update.message.reply_text(
            "Спочатку потрібно зареєструватись — напиши /start"
        )
        return ConversationHandler.END
    context.user_data["survey"] = {"feelings": []}
    target = update.message or update.callback_query.message
    if update.callback_query:
        await update.callback_query.answer()
    await target.reply_text(
        "Як змінився твій стан?", reply_markup=kb(STATE_OPTIONS, "state")
    )
    return SUR_STATE


async def sur_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["survey"]["state_change"] = q.data.split(":", 1)[1]
    await q.edit_message_text(f"Стан: {context.user_data['survey']['state_change']}")

    kb_feel = InlineKeyboardMarkup(
        [[InlineKeyboardButton(o, callback_data=f"feel:{o}")] for o in FEEL_OPTIONS]
        + [[InlineKeyboardButton("✅ Готово", callback_data="feel:DONE")]]
    )
    await q.message.reply_text(
        "Що ти відчула? (обери одне чи декілька, потім натисни Готово)",
        reply_markup=kb_feel,
    )
    return SUR_FEEL


async def sur_feel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    choice = q.data.split(":", 1)[1]
    selected = context.user_data["survey"]["feelings"]

    if choice == "DONE":
        text = ", ".join(selected) if selected else "(нічого не обрано)"
        await q.edit_message_text(f"Відчуття: {text}")
        await q.message.reply_text(
            "Через скільки часу з'явився ефект?", reply_markup=kb(TIME_OPTIONS, "time")
        )
        return SUR_TIME

    if choice in selected:
        selected.remove(choice)
    else:
        selected.append(choice)

    marked = [("☑ " if o in selected else "") + o for o in FEEL_OPTIONS]
    kb_feel = InlineKeyboardMarkup(
        [[InlineKeyboardButton(m, callback_data=f"feel:{o}")] for m, o in zip(marked, FEEL_OPTIONS)]
        + [[InlineKeyboardButton("✅ Готово", callback_data="feel:DONE")]]
    )
    await q.edit_message_reply_markup(reply_markup=kb_feel)
    return SUR_FEEL


async def sur_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["survey"]["effect_time"] = q.data.split(":", 1)[1]
    await q.edit_message_text(f"Час ефекту: {context.user_data['survey']['effect_time']}")
    await q.message.reply_text("Як тобі аромат?", reply_markup=kb(AROMA_OPTIONS, "aroma"))
    return SUR_AROMA


async def sur_aroma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["survey"]["aroma_rating"] = q.data.split(":", 1)[1]
    await q.edit_message_text(f"Аромат: {context.user_data['survey']['aroma_rating']}")
    await q.message.reply_text(
        "Як часто ти використовувала рол-он?", reply_markup=kb(FREQ_OPTIONS, "freq")
    )
    return SUR_FREQ


async def sur_freq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["survey"]["usage_freq"] = q.data.split(":", 1)[1]
    await q.edit_message_text(f"Частота: {context.user_data['survey']['usage_freq']}")
    await q.message.reply_text(
        "Опиши свій досвід своїми словами 🤍 (або напиши /skip)"
    )
    return SUR_TEXT


async def sur_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["survey"]["experience_text"] = update.message.text.strip()
    await update.message.reply_text(
        "Чи будеш ти користуватись далі?", reply_markup=kb(CONTINUE_OPTIONS, "cont")
    )
    return SUR_CONTINUE


async def sur_text_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["survey"]["experience_text"] = ""
    await update.message.reply_text(
        "Чи будеш ти користуватись далі?", reply_markup=kb(CONTINUE_OPTIONS, "cont")
    )
    return SUR_CONTINUE


async def sur_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["survey"]["will_continue"] = q.data.split(":", 1)[1]
    await q.edit_message_text(f"Продовжить: {context.user_data['survey']['will_continue']}")
    await q.message.reply_text(
        "Чи можна використати твій відгук?", reply_markup=kb(CONSENT_OPTIONS, "consent")
    )
    return SUR_CONSENT


async def sur_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["survey"]["consent"] = q.data.split(":", 1)[1]
    await q.edit_message_text(f"Згода: {context.user_data['survey']['consent']}")
    await q.message.reply_text("Твій Instagram? (або напиши /skip)")
    return SUR_INSTAGRAM


async def sur_instagram_done(update: Update, context: ContextTypes.DEFAULT_TYPE, instagram: str):
    survey = context.user_data["survey"]
    survey["instagram"] = instagram
    survey["feelings"] = ", ".join(survey.get("feelings", []))
    save_response(update.effective_user.id, survey)
    await update.message.reply_text(
        "Дякуємо за відповіді! 🤍 Побачимось завтра."
    )
    context.user_data.clear()
    return ConversationHandler.END


async def sur_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await sur_instagram_done(update, context, update.message.text.strip())


async def sur_instagram_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await sur_instagram_done(update, context, "")


survey_conv = ConversationHandler(
    entry_points=[
        CommandHandler("survey", survey_entry),
        CallbackQueryHandler(survey_entry, pattern=r"^daily_survey$"),
    ],
    states={
        SUR_STATE: [CallbackQueryHandler(sur_state, pattern=r"^state:")],
        SUR_FEEL: [CallbackQueryHandler(sur_feel, pattern=r"^feel:")],
        SUR_TIME: [CallbackQueryHandler(sur_time, pattern=r"^time:")],
        SUR_AROMA: [CallbackQueryHandler(sur_aroma, pattern=r"^aroma:")],
        SUR_FREQ: [CallbackQueryHandler(sur_freq, pattern=r"^freq:")],
        SUR_TEXT: [
            CommandHandler("skip", sur_text_skip),
            MessageHandler(filters.TEXT & ~filters.COMMAND, sur_text),
        ],
        SUR_CONTINUE: [CallbackQueryHandler(sur_continue, pattern=r"^cont:")],
        SUR_CONSENT: [CallbackQueryHandler(sur_consent, pattern=r"^consent:")],
        SUR_INSTAGRAM: [
            CommandHandler("skip", sur_instagram_skip),
            MessageHandler(filters.TEXT & ~filters.COMMAND, sur_instagram),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

# ---------------------------------------------------------------------------
# Напоминание (ежедневная джоба)
# ---------------------------------------------------------------------------

async def send_daily_reminders(context: ContextTypes.DEFAULT_TYPE):
    for tg_id in all_user_ids():
        if already_responded_today(tg_id):
            continue
        try:
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📝 Заповнити анкету", callback_data="daily_survey")]]
            )
            await context.bot.send_message(
                chat_id=tg_id,
                text="Привіт! 🌙 Час поділитись відчуттями від рол-она за сьогодні.",
                reply_markup=markup,
            )
        except Exception as e:
            logger.warning("Не вдалось надіслати нагадування %s: %s", tg_id, e)


# ---------------------------------------------------------------------------
# Админ: экспорт и статистика
# ---------------------------------------------------------------------------

async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Ця команда доступна лише адміну.")
        return

    from openpyxl import Workbook

    conn = db()
    users = conn.execute("SELECT * FROM users").fetchall()
    user_cols = [d[0] for d in conn.execute("SELECT * FROM users").description]
    responses = conn.execute(
        "SELECT * FROM responses ORDER BY telegram_id, response_date"
    ).fetchall()
    resp_cols = [d[0] for d in conn.execute("SELECT * FROM responses").description]
    conn.close()

    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Users"
    ws1.append(user_cols)
    for row in users:
        ws1.append(row)

    ws2 = wb.create_sheet("Responses")
    ws2.append(resp_cols)
    for row in responses:
        ws2.append(row)

    fname = f"sentio_export_{datetime.now(TIMEZONE).strftime('%Y%m%d_%H%M')}.xlsx"
    wb.save(fname)
    await update.message.reply_document(document=open(fname, "rb"), filename=fname)
    os.remove(fname)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Ця команда доступна лише адміну.")
        return
    conn = db()
    n_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    n_resp = conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
    today = datetime.now(TIMEZONE).date().isoformat()
    n_today = conn.execute(
        "SELECT COUNT(*) FROM responses WHERE response_date = ?", (today,)
    ).fetchone()[0]
    conn.close()
    await update.message.reply_text(
        f"👥 Зареєстровано: {n_users}\n"
        f"📝 Всього відповідей: {n_resp}\n"
        f"📅 Відповіли сьогодні: {n_today}"
    )


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Твій Telegram ID: {update.effective_user.id}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(registration_conv)
    app.add_handler(survey_conv)
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("whoami", whoami))

    app.job_queue.run_daily(
        send_daily_reminders,
        time=dtime(hour=REMINDER_HOUR, minute=REMINDER_MINUTE, tzinfo=TIMEZONE),
    )

    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
