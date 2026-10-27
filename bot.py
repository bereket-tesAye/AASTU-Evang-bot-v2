import os
import time
import random
import string
import threading
import requests as req
import psycopg2
import psycopg2.extras
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────
TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0"))
ADMIN_1_ID = int(os.getenv("ADMIN_1_ID", "111111111"))
ADMIN_2_ID = int(os.getenv("ADMIN_2_ID", "222222222"))
ADMIN_3_ID = int(os.getenv("ADMIN_3_ID", "333333333"))

SOURCE_LABEL_MAP = {
    "ኢየሱስን እንደ ግል አዳኝ አድርጌ ለመቀበል": "✝️ Salvation",
    "በንሰሀ መመለስ እፈልጋለሁ":             "🔄 Repentance",
    "አማካሪ ማግኘት እፈልጋለሁ":             "🤝 Counseling",
    "ጥያቄ መጠየቅ እፈልጋለሁ":              "📖 Bible Q&A",
}

# ─────────────────────────────────────────────
#  Flask health server
# ─────────────────────────────────────────────
app = Flask(__name__)

@app.route("/")
@app.route("/health")
def health():
    return {"status": "ok", "message": "AASTU Evang Bot is running"}, 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ─────────────────────────────────────────────
#  Database
# ─────────────────────────────────────────────
def db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME", "postgres"),
        sslmode="require"
    )

def get_topic_id(user_id):
    conn = None
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT topic_id FROM user_progress WHERE telegram_id = %s", (user_id,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] else None
    except Exception as e:
        print(f"[DB] get_topic_id error: {e}")
        return None
    finally:
        if conn: conn.close()

def set_topic_id(user_id, topic_id):
    conn = None
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO user_progress (telegram_id, topic_id)
               VALUES (%s, %s)
               ON CONFLICT (telegram_id) DO UPDATE SET topic_id = EXCLUDED.topic_id""",
            (user_id, topic_id)
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] set_topic_id error: {e}")
    finally:
        if conn: conn.close()

def get_user_by_topic(topic_id):
    conn = None
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT telegram_id FROM user_progress WHERE topic_id = %s", (topic_id,))
        row = cur.fetchone()
        return int(row[0]) if row else None
    except Exception as e:
        print(f"[DB] get_user_by_topic error: {e}")
        return None
    finally:
        if conn: conn.close()

# ─────────────────────────────────────────────
#  Anonymous ID helpers
# ─────────────────────────────────────────────
def _generate_anon_id():
    chars = string.ascii_uppercase + string.digits
    return "#" + "".join(random.choices(chars, k=6))

def get_or_create_anon_id(user_id):
    conn = None
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT anon_id FROM user_progress WHERE telegram_id = %s", (user_id,))
        row = cur.fetchone()
        if row and row[0]:
            return row[0]
        anon_id = _generate_anon_id()
        cur.execute(
            """INSERT INTO user_progress (telegram_id, anon_id)
               VALUES (%s, %s)
               ON CONFLICT (telegram_id) DO UPDATE
               SET anon_id = CASE
                   WHEN user_progress.anon_id IS NULL THEN EXCLUDED.anon_id
                   ELSE user_progress.anon_id
               END""",
            (user_id, anon_id)
        )
        conn.commit()
        cur.execute("SELECT anon_id FROM user_progress WHERE telegram_id = %s", (user_id,))
        row = cur.fetchone()
        return row[0] if row else anon_id
    except Exception as e:
        print(f"[DB] get_or_create_anon_id error: {e}")
        return _generate_anon_id()
    finally:
        if conn: conn.close()

# ─────────────────────────────────────────────
#  Bot
# ─────────────────────────────────────────────
bot = telebot.TeleBot(TOKEN, threaded=True)
BOT_ID = bot.get_me().id

# ─────────────────────────────────────────────
#  Keyboards
# ─────────────────────────────────────────────
main_kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
main_kb.row("ኢየሱስን እንደ ግል አዳኝ አድርጌ ለመቀበል")
main_kb.row("በንሰሀ መመለስ እፈልጋለሁ")
main_kb.row("ስለ ኢየሱስ ክርስቶስ በበለጠ ለማወቅ")
main_kb.row("የመጽሐፍ ቅዱስ ጥናት እቅድ ለማግኘት")
main_kb.row("አማካሪ ማግኘት እፈልጋለሁ")
main_kb.row("ጥያቄ መጠየቅ እፈልጋለሁ")
main_kb.row("በስህተት ነው የነካሁት")

cancel_kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
cancel_kb.add(KeyboardButton("❌ ሰርዝ (Cancel)"))

sex_kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
sex_kb.row("Male", "Female")
sex_kb.row("❌ ሰርዝ (Cancel)")

# ─────────────────────────────────────────────
#  Study files
# ─────────────────────────────────────────────
STUDY_FILES = {
    "እየሱስ ከአብ ጋር እኩል ስልጣን የለውም":          "BQACAgQAAyEFAATkiwQeAAMUacTbMcmwvG88u9injn2s_JNg3ZIAAhMdAAIHdihST2mm2MGw0qo6BA",
    "ሥላሴ ሚለው ቃል መፅሐፍ ቅዱስ ላይ የለም":          "BQACAgQAAyEFAATkiwQeAAMNacTbMaZk4sg1CaPu9ZZ6Dfkio8kAAgwdAAIHdihSTwX9MvVYtmM6BA",
    "አምላክ እንዴት ወደ አምላክ ይፀልያል?":             "BQACAgQAAyEFAATkiwQeAAMQacTbMRzZ4yCmC2JPLW7iwLsOHoAAAg8dAAIHdihSZqqDCB2OQhU6BA",
    "አምላክ እንዴት ይወልዳል?":                      "BQACAgQAAyEFAATkiwQeAAMRacTbMed9vEegLIPBPTQoILT--40AAhAdAAIHdihS0ds89QKq1lA6BA",
    "ስንት አምላክ ነው ያላቹ?":                      "BQACAgQAAyEFAATkiwQeAAMOacTbMUIqjlYCQCvzKuIkmaecm5QAAg0dAAIHdihS8mG5Xi5-0uY6BA",
    "አንድ አምላክ እንዴት የአንድ አምላክ ልጅ ይባላል?":   "BQACAgQAAyEFAATkiwQeAAMTacTbMdKoMbmiUWz0Rd4WMAWby9QAAhIdAAIHdihSoaptNhjhh-A6BA",
    "የውሃ ጥምቀት በኢየሱስ ክርስቶስ ስም":             "BQACAgQAAyEFAATkiwQeAAMWacTbMS3oCKVxFvlfMYJiBAq8nEIAAhUdAAIHdihSJ9OUTPAO0ao6BA",
    "ትምህርተ ሥላሴና የአረማውያኑ":                   "BQACAgQAAyEFAATkiwQeAAMPacTbMXJsAmzgTpc-i8sQsFyPXJIAAg4dAAIHdihSyaA5H27yGsM6BA",
    "የኦንሊ ጂሰሱ_አብ ወልድና መንፈስ ቅዱስ":           "BQACAgQAAyEFAATkiwQeAAMVacTbMbVLit8MP8ZBqN7W5fD4pfMAAhQdAAIHdihSk2HT3OjY4ic6BA",
    "አብ ፣ ወልድና መንፈስ ቅዱስ የተለያዩ አካላት አይደሉምን": "BQACAgQAAyEFAATkiwQeAAMSacTbMSGtXjsgRvk8DAQo4ud2cRwAAhEdAAIHdihS7tw9h3oYsWs6BA",
}

# ─────────────────────────────────────────────
#  Forum topic helpers
# ─────────────────────────────────────────────
def ensure_topic(user_id, source=""):
    tid = get_topic_id(user_id)
    if tid:
        return tid
    label   = SOURCE_LABEL_MAP.get(source, "💬 General")
    anon_id = get_or_create_anon_id(user_id)
    result  = bot.create_forum_topic(ADMIN_GROUP_ID, name=f"{label} | {anon_id}")
    tid     = result.message_thread_id
    set_topic_id(user_id, tid)
    return tid

def forward_to_admin(user_id, message, source=""):
    try:
        tid = ensure_topic(user_id, source)
        # copy_message strips the "Forwarded from" attribution header,
        # keeping the content but hiding the sender's identity.
        bot.copy_message(ADMIN_GROUP_ID, user_id, message.message_id, message_thread_id=tid)
    except Exception as e:
        print(f"[forward_to_admin] {e}")

def send_to_user(admin_msg):
    tid = admin_msg.message_thread_id
    print(f"[send_to_user] tid={tid}")
    if not tid:
        print(f"[send_to_user] no thread id, skipping")
        return
    user_id = get_user_by_topic(tid)
    if not user_id:
        print(f"[send_to_user] no user found for topic {tid}")
        return
    print(f"[send_to_user] sending to user_id={user_id}")
    try:
        if admin_msg.text:
            bot.send_message(user_id, f"💬 {admin_msg.text}")
        elif admin_msg.photo:
            bot.send_photo(user_id, admin_msg.photo[-1].file_id, caption=admin_msg.caption or "")
        elif admin_msg.document:
            bot.send_document(user_id, admin_msg.document.file_id, caption=admin_msg.caption or "")
        elif admin_msg.voice:
            bot.send_voice(user_id, admin_msg.voice.file_id)
        elif admin_msg.video:
            bot.send_video(user_id, admin_msg.video.file_id, caption=admin_msg.caption or "")
        elif admin_msg.sticker:
            bot.send_sticker(user_id, admin_msg.sticker.file_id)
        else:
            bot.send_message(user_id, "📎 አዲስ መልዕክት ከአማካሪ ደርሷል።")
    except Exception as e:
        print(f"[send_to_user] {e}")

# ─────────────────────────────────────────────
#  Registration state
# ─────────────────────────────────────────────
user_states = {}

def start_registration(message, source):
    cid = message.chat.id
    user_states[cid] = {"step": "sex", "source": source}

    if "አማካሪ ማግኘት እፈልጋለሁ" in source:
        msg = ("እኛን ለማግኘት ስለፈለጉ እናመሰግናለን🙏\n"
               "በcounseling Team ወደ ሚሰጥ ወደ ማማከር አገልግሎት ይወስዶታል።\n\n"
               "ለማቋረጥ 'cancel' ብለው ይጻፉ።\n\n"
               "👉 ፆታዎን ያስገቡ (Male / Female):")
    elif "በንሰሀ መመለስ እፈልጋለሁ" in source:
        msg = (
            "🙏 በንሰሀ ለመመለስ መወሰንዎ ትልቅ ደስታ ነው!\n\n"
            "በኃጢአታችን ብንናዘዝ ኃጢአታችንን ይቅር ሊለን ከዓመፃም ሁሉ ሊያነጻን የታመነና ጻድቅ ነው።\n"
            "     - 1ኛ የዮሐንስ መልእክት 1 : 9\n\n"
            "ይህንን አጭር ፀሎት ይፀልዩ፦\n\n"
            "\"አምላክ ሆይ ፣ በእኔ ምትክ እንዲቆምልኝና የሚገባኝን ቁጣህን በእርሱ ላይ ስለተቀበለልኝ "
            "ስለ ልጅህ አመሰግንሃለሁ። በክርስቶስ የመስቀል ላይ ሥራ ምክንያት በዙፋንህ ፊት ይቅር "
            "የተባልኩና የጸደቅኩ ሆኜ እቆማለሁ። ምንም እንኳ ከኃጢአቴ ይቅር የተባልኩ ብሆንም፣ "
            "ይህ ማለት ግን በኃጢአት ውስጥ አልወድቅም ማለት አይደለም። ሥጋዬ ከመንገድህ ሊያርቀኝ "
            "ይፈልጋል፤ አንዳንዴም በፈተናው ተሸንፌ ትእዛዝህን እጥሳለሁ። ከአንተ ከመሸሽ ይልቅ፣ "
            "ንስሐ መግባትን እመርጣለሁ። መንፈስ ቅዱስ ሆይ፣ ቶሎ ንስሐ እንድገባና ወደ ጸጋው ዙፋን "
            "እንድሮጥ እርዳኝ። አባት ሆይ፣ በየማለዳው ስለሚታደሰው ምሕረትህ አመሰግንሃለሁ። "
            "ምሕረትህን እንደ ቀላል እንዳልመለከተው፤ ይልቁንም ሁልጊዜ በፊትህ በታማኝነት "
            "መመላለስንና አለመታዘዜን በንስሐ መናዘዝን ልማዴ ላድርገው። አንተ እጅግ ታማኝ አባት ነህ፤ "
            "እጆችህን ዘርግተህ ትጠብቀኛለህ። ለምትሰጠኝ ብዙ የንስሐ ዕድሎች ሁሉ አመሰግንሃለሁ።\n"
            "     በኢየሱስ ስም፣ አሜን.\"\n\n"
            "ለማቋረጥ 'cancel' ብለው ይጻፉ።\n\n"
            "👉 ፆታዎን ያስገቡ (Male / Female):"
        )
    elif "ኢየሱስን እንደ ግል አዳኝ አድርጌ ለመቀበል" in source:
        msg = ("🙏 ኢየሱስን እንደ ግል አዳኝ ለመቀበል የመወሰንዎ ትልቅ ደስታ ነው!\n\n"
               "ለማቋረጥ 'cancel' ብለው ይጻፉ።\n\n"
               "👉 ፆታዎን ያስገቡ (Male / Female):")
    else:
        msg = ("🙏 ጥያቄ መጠየቅ ስለፈለጉ እናመሰግናለን🙏\n\n"
               "ለማቋረጥ 'cancel' ብለው ይጻፉ።\n\n"
               "👉 ፆታዎን ያስገቡ (Male / Female):")

    bot.send_message(cid, msg, reply_markup=sex_kb)

# ─────────────────────────────────────────────
#  Handlers — admin group
# ─────────────────────────────────────────────
@bot.message_handler(
    func=lambda m: (
        m.chat.id == ADMIN_GROUP_ID
        and m.message_thread_id is not None
        and m.from_user is not None
        and m.from_user.id != BOT_ID
    )
)
def on_admin_reply(msg):
    print(f"[admin_reply] thread={msg.message_thread_id} from={msg.from_user.id} text={msg.text!r}")
    user_id = get_user_by_topic(msg.message_thread_id)
    print(f"[admin_reply] resolved user_id={user_id}")
    send_to_user(msg)

# ─────────────────────────────────────────────
#  Handlers — commands
# ─────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def on_start(msg):
    bot.reply_to(msg,
        "🙏 እንኳን ወደ AASTU Evang Mobilizers Team Bot በሰላም መጡ!\n\n"
        "📋 ትዕዛዞች:\n"
        "/start - ይህን መልዕክት ያሳያል\n"
        "/help  - ምን መስራት እንደሚችል ያብራራል\n\n"
        "👇 ከታች ካሉት አማራጮች አንዱን ይምረጡ፦",
        reply_markup=main_kb
    )

@bot.message_handler(commands=["help"])
def on_help(msg):
    bot.reply_to(msg,
        "🤖 ይህ ቦት ኢየሱስን በበለጠ እንዲያውቁ ይረዳዎታል።\n\n"
        "👇 ምርጫዎች:\n"
        "• ኢየሱስን እንደ ግል አዳኝ አድርጌ ለመቀበል\n"
        "• በንሰሀ መመለስ እፈልጋለሁ\n"
        "• ስለ ኢየሱስ ክርስቶስ በበለጠ ለማወቅ\n"
        "• የመጽሐፍ ቅዱስ ጥናት እቅድ ለማግኘት\n"
        "• አማካሪ ማግኘት እፈልጋለሁ\n"
        "• ጥያቄ መጠየቅ እፈልጋለሁ\n\n"
        "❤️ ኢየሱስ ሁሉንም ይወዳል!!",
        reply_markup=main_kb
    )

@bot.message_handler(commands=["no"])
def on_no(msg):
    bot.send_message(msg.chat.id,
        "ችግር የለም😊! ሃሳብዎን ከቀየሩ /yes ይጫኑ።\nእግዚአብሔር ይባርክዎ! 🙏")

@bot.message_handler(commands=["yes"])
def on_yes(msg):
    start_registration(msg, "ኢየሱስን እንደ ግል አዳኝ አድርጌ ለመቀበል")

# ─────────────────────────────────────────────
#  Registration steps
# ─────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.chat.id in user_states)
def on_registration(msg):
    cid  = msg.chat.id
    text = msg.text.strip() if msg.text else ""

    if text in ("❌ ሰርዝ (Cancel)",) or text.lower() == "cancel":
        del user_states[cid]
        bot.send_message(cid, "ምዝገባው ተሰርዟል። 🙏", reply_markup=main_kb)
        return

    state = user_states[cid]

    if state["step"] == "sex":
        if text.lower() not in ["male", "female"]:
            bot.send_message(cid, "❌ Male ወይም Female ብቻ ያስገቡ።", reply_markup=sex_kb)
            return
        state["sex"] = text

        source   = state["source"]
        anon_id  = get_or_create_anon_id(cid)

        # Create the forum topic using only the anonymous ID — no real name
        try:
            tid = ensure_topic(cid, source)
            bot.send_message(
                ADMIN_GROUP_ID,
                f"🚨 *New Request*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 *Category:* {source}\n"
                f"⚧ *Sex:* {state['sex']}\n"
                f"� *Anonymous ID:* `{anon_id}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"↩️ Reply here to message this person anonymously.",
                parse_mode="Markdown",
                message_thread_id=tid
            )
        except Exception as e:
            print(f"[registration] topic error: {e}")



        bot.send_message(cid,
            "✅ ተመዝግቧል! አማካሪ በቅርቡ ያነጋግርዎታል። እግዚአብሔር ይባርክዎ! 🙏\n\n"
            "ከዚህ በኋላ የምትልኩት ማንኛውም መልዕክት ወደ አማካሪ ቡድናችን ይደርሳል።",
            reply_markup=main_kb
        )
        del user_states[cid]

# ─────────────────────────────────────────────
#  Bible study
# ─────────────────────────────────────────────
def next_lesson_btn():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("ቀጣዩን ቀን አሳየኝ (Next Day) ➡️", callback_data="next_day"))
    return m

def start_bible_study(msg):
    uid  = msg.chat.id
    book = "የዮሐንስ ወንጌል"
    conn = None
    try:
        conn = db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT chapter, teaching_content FROM study_content WHERE book_name=%s AND day_number=1", (book,))
        lesson = cur.fetchone()
        if lesson:
            cur.execute(
                """INSERT INTO user_progress (telegram_id, active_book, current_day, last_sent_at, subscription_status)
                   VALUES (%s, %s, 1, NOW(), 'active')
                   ON CONFLICT (telegram_id) DO UPDATE SET
                       active_book = EXCLUDED.active_book,
                       current_day = 1,
                       last_sent_at = NOW(),
                       subscription_status = 'active'""",
                (uid, book)
            )
            conn.commit()
            bot.send_message(uid, f"📖 *{lesson['chapter']}*\n\n{lesson['teaching_content']}",
                             parse_mode="Markdown", reply_markup=next_lesson_btn())
        else:
            bot.send_message(uid, "⚠️ የጥናት ይዘቱ አልተገኘም። እባክዎ አስተዳዳሪውን ያነጋግሩ።")
    except Exception as e:
        print(f"[bible_study] {e}")
        bot.send_message(uid, "⚠️ ችግር ተፈጥሯል። እባክዎ ቆይተው ይሞክሩ።")
    finally:
        if conn: conn.close()

@bot.callback_query_handler(func=lambda c: c.data == "next_day")
def on_next_day(call):
    uid  = call.from_user.id
    conn = None
    try:
        conn = db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT active_book, current_day FROM user_progress WHERE telegram_id=%s", (uid,))
        row = cur.fetchone()
        if not row:
            bot.answer_callback_query(call.id, "እባክዎ መጀመሪያ ጥናቱን ይጀምሩ።")
            return
        next_day = row["current_day"] + 1
        cur.execute("SELECT chapter, teaching_content FROM study_content WHERE book_name=%s AND day_number=%s",
                    (row["active_book"], next_day))
        content = cur.fetchone()
        if content:
            cur.execute("UPDATE user_progress SET current_day=%s, last_sent_at=NOW() WHERE telegram_id=%s",
                        (next_day, uid))
            conn.commit()
            bot.send_message(uid, f"📖 *{content['chapter']}*\n\n{content['teaching_content']}",
                             parse_mode="Markdown", reply_markup=next_lesson_btn())
            bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
            bot.answer_callback_query(call.id)
        else:
            cur.execute("UPDATE user_progress SET subscription_status='completed' WHERE telegram_id=%s", (uid,))
            conn.commit()
            bot.send_message(uid, "🎉 እንኳን ደስ አሎት! የዮሐንስ ወንጌል ጥናትዎን አጠናቅቀዋል።")
            bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
            bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"[next_day] {e}")
        bot.answer_callback_query(call.id, "⚠️ ችግር ተፈጥሯል።")
    finally:
        if conn: conn.close()

# ─────────────────────────────────────────────
#  Daily scheduler
# ─────────────────────────────────────────────
def send_daily():
    conn = None
    try:
        conn = db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT telegram_id, active_book, current_day FROM user_progress
                       WHERE last_sent_at <= NOW() - INTERVAL '24 hours'
                       AND subscription_status='active'""")
        for user in cur.fetchall():
            nd = user["current_day"] + 1
            cur.execute("SELECT chapter, teaching_content FROM study_content WHERE book_name=%s AND day_number=%s",
                        (user["active_book"], nd))
            content = cur.fetchone()
            if content:
                try:
                    bot.send_message(user["telegram_id"],
                                     f"📖 *{content['chapter']}*\n\n{content['teaching_content']}",
                                     parse_mode="Markdown")
                    cur.execute("UPDATE user_progress SET current_day=%s, last_sent_at=NOW() WHERE telegram_id=%s",
                                (nd, user["telegram_id"]))
                    conn.commit()
                except Exception as e:
                    print(f"[daily] send error: {e}")
            else:
                cur.execute("UPDATE user_progress SET subscription_status='completed' WHERE telegram_id=%s",
                            (user["telegram_id"],))
                conn.commit()
                bot.send_message(user["telegram_id"], "🎉 እንኳን ደስ አሎት! የ21 ቀን ጥናትዎን አጠናቅቀዋል።")
    except Exception as e:
        print(f"[daily] {e}")
    finally:
        if conn: conn.close()

scheduler = BackgroundScheduler()
scheduler.add_job(send_daily, "interval", minutes=60)
scheduler.start()

# ─────────────────────────────────────────────
#  Main message router
# ─────────────────────────────────────────────
MENU_BUTTONS = {
    "ኢየሱስን እንደ ግል አዳኝ አድርጌ ለመቀበል", "በንሰሀ መመለስ እፈልጋለሁ",
    "ስለ ኢየሱስ ክርስቶስ በበለጠ ለማወቅ", "የመጽሐፍ ቅዱስ ጥናት እቅድ ለማግኘት",
    "አማካሪ ማግኘት እፈልጋለሁ", "ጥያቄ መጠየቅ እፈልጋለሁ", "በስህተት ነው የነካሁት",
    "Back to Main Menu", "Commmon Questions on christianity",
    "Common Muslim questions about Christianity?",
    "Common Only Jesus questions about Christianity",
    "የዮሐንስ ወንጌል (Gospel of John)",
}

@bot.message_handler(func=lambda m: True)
def router(msg):
    if msg.chat.id == ADMIN_GROUP_ID:
        return

    cid  = msg.chat.id
    text = msg.text or ""

    # Relay if registered and not pressing a menu button
    if get_topic_id(cid) is not None and text not in MENU_BUTTONS and text not in STUDY_FILES:
        forward_to_admin(cid, msg)
        return

    if text == "አማካሪ ማግኘት እፈልጋለሁ":
        start_registration(msg, "አማካሪ ማግኘት እፈልጋለሁ")

    elif text == "ጥያቄ መጠየቅ እፈልጋለሁ":
        start_registration(msg, "ጥያቄ መጠየቅ እፈልጋለሁ")

    elif text == "በንሰሀ መመለስ እፈልጋለሁ":
        start_registration(msg, "በንሰሀ መመለስ እፈልጋለሁ")

    elif text == "ስለ ኢየሱስ ክርስቶስ በበለጠ ለማወቅ":
        bot.send_message(cid,
            "ኢየሱስ ማነው? ወደ ሰላም የሚወስደውን መንገድ መረዳት!!\n\n"
            "1. ዓለማቀፋዊው እውነት\n"
            "ምንም ዓይነት አስተዳደግ፣ ሀብት ወይም የኑሮ ደረጃ ቢኖረን፣ እያንዳንዱ የሰው ልጅ "
            "ያንኑ መሠረታዊ ጥያቄ ይጠይቃል፦ \"ከሞት በኋላ ምን ይከሰታል?\"\n\n"
            "2. ችግሩ፦ ኃጢአትና መለየት\n"
            "እግዚአብሔር የፈጠረን ከእርሱ ጋር ህብረት እንድናደርግ ነበር፤ እኛ ግን የራሳችንን "
            "መንገድ መረጥን። ሮሜ 6፡23 \"የኃጢአት ደመወዝ ሞት ነው\" ይላል።\n\n"
            "3. መፍትሄው፦ የኢየሱስ መስዋዕትነት\n"
            "ኢየሱስ ክርስቶስ ፍጹም ሕይወት ኖሮ፣ በመስቀል ላይ የእኛን ቦታ ተካ። ከሙታን ተነሳ።\n\n"
            "4. ምላሻችን ምን መሆን አለበት?\n"
            "• ንስሐ መግባት • ማመን • መቀበል\n\n"
            "ከእርሱ ጋር ለመቀጠል \"ኢየሱስን እንደ ግል አዳኝ አድርጌ ለመቀበል\" ይጫኑ።\n\n"
            "❤️ ኢየሱስ ሁሉንም ይወዳል!!"
        )

    elif text == "ኢየሱስን እንደ ግል አዳኝ አድርጌ ለመቀበል":
        bot.send_message(cid,
            "🙏 እንደ ግል አዳኝ እንዴት መቀበል ይችላሉ?\n\n"
            "1. ኃጢአተኛ መሆንዎን አምነው ይቀበሉ\n"
            "\"ሁሉ ኃጢአትን ሠርተዋልና የእግዚአብሔርም ክብር ጎድሎአቸዋል\"\n"
            "        - ሮሜ 3:23\n\n"
            "ኀጢያት የእግዚአብሔር ተዛዝ ላይ ማመጽ ነው። መጽሐፍ ቅዱስ እንደሚያስረዳን "
            "እኛ ሁላችን ኀጢያተኞች ነን።\n\n"
            "2. ኢየሱስ ስለ ኃጢአትዎ እንደሞተ ይምኑ\n"
            "\"ነገር ግን ገና ኃጢአተኞች ሳለን ክርስቶስ ስለ እኛ ሞቶአልና\"\n"
            "        - ሮሜ 5:8\n\n"
            "እግዚአብሔር እኛን እጅግ ስለሚወደን አንድ ልጁን ስለ በደላችን እራሱ ተቀጣልን።\n\n"
            "3. በኢየሱስ ክርስቶስ ትንሳኤ ያምኑ\n"
            "\"ትንሣኤና ሕይወት እኔ ነኝ፤ የሚያምንብኝ ቢሞት እንኳ ሕያው ይሆናል\"\n"
            "        - ዮሐንስ 11:25\n\n"
            "ማጠቃለያ ፀሎት:\n"
            "\"ጌታ ሆይ አኔን ሰለወደድከኝ አመሰግናለሁ። አሁን በገልጥ ሃጥያተኛ መሆኔን አምናለሁ። "
            "ለኔ ኀጢያት በኔ ቦታ ሰለተቀጣህልኝ አመሰግናለሁ። ኢየሱስ በኔ ፈንታ መሞቱን ሞትን ድል "
            "አድርጎ በሶስተኛ ቀን መነሳቱን አምናለሁ። ከእንግዲህ ወዲህ ያንተ ልጅ ሆኜ ካንተ ጋር ህብረት "
            "እያደረኩ መኖር እፈልጋለሁ። አለምን እና ሰይጣንን ክዳለሁ፣ ህይወቴን ተረከበኝ።\"\n\n"
            "🎉 ይህንን ፀሎት ከልብ ከፀለዩ እንኳን ደስ አሎት! አሁን የእግዚአብሔር ልጅ ሆነዋል🎉\n\n"
            "ከክርስቶስ ጋር የሚረዳዎት ጓደኛ ይፈልጋሉ?\n"
            "/yes - ጓደኛ እፈልጋለሁ\n"
            "/no  - ጓደኛ አልፈልጋም"
        )

    elif text == "የመጽሐፍ ቅዱስ ጥናት እቅድ ለማግኘት":
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row("የዮሐንስ ወንጌል (Gospel of John)")
        kb.row("Commmon Questions on christianity")
        kb.row("Back to Main Menu")
        bot.send_message(cid, "የትኛውን ጥናት መጀመር ይፈልጋሉ?", reply_markup=kb)

    elif text == "Commmon Questions on christianity":
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row("Common Muslim questions about Christianity?")
        kb.row("Common Only Jesus questions about Christianity")
        kb.row("Back to Main Menu")
        bot.send_message(cid, "የትኛውን ጥናት መጀመር ይፈልጋሉ?", reply_markup=kb)

    elif text == "Common Muslim questions about Christianity?":
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row("እየሱስ ከአብ ጋር እኩል ስልጣን የለውም")
        kb.row("ሥላሴ ሚለው ቃል መፅሐፍ ቅዱስ ላይ የለም")
        kb.row("አምላክ እንዴት ወደ አምላክ ይፀልያል?")
        kb.row("አምላክ እንዴት ይወልዳል?")
        kb.row("ስንት አምላክ ነው ያላቹ?")
        kb.row("አንድ አምላክ እንዴት የአንድ አምላክ ልጅ ይባላል?")
        kb.row("Back to Main Menu")
        bot.send_message(cid, "የትኛውን ጥናት መጀመር ይፈልጋሉ?", reply_markup=kb)

    elif text == "Common Only Jesus questions about Christianity":
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row("የውሃ ጥምቀት በኢየሱስ ክርስቶስ ስም")
        kb.row("ትምህርተ ሥላሴና የአረማውያኑ")
        kb.row("የኦንሊ ጂሰሱ_አብ ወልድና መንፈስ ቅዱስ")
        kb.row("አብ ፣ ወልድና መንፈስ ቅዱስ የተለያዩ አካላት አይደሉምን")
        kb.row("Back to Main Menu")
        bot.send_message(cid, "የትኛውን ጥናት መጀመር ይፈልጋሉ?", reply_markup=kb)

    elif text in STUDY_FILES:
        try:
            bot.send_chat_action(cid, "upload_document")
            bot.send_document(cid, STUDY_FILES[text], caption=f"📄 {text}")
        except Exception as e:
            bot.send_message(cid, "⚠️ ፋይሉን ማግኘት አልተቻለም።")
            print(f"[file] {e}")

    elif text == "Back to Main Menu":
        bot.send_message(cid, "ዋና ማውጫ", reply_markup=main_kb)

    elif text == "የዮሐንስ ወንጌል (Gospel of John)":
        start_bible_study(msg)

    elif text == "በስህተት ነው የነካሁት":
        bot.send_message(cid, "ችግር የለም! 😊 አማራጮቹን ለማየት /start ይጫኑ።", reply_markup=main_kb)

    else:
        bot.send_message(cid, "አልገባኝም። /start ይጠቀሙ", reply_markup=main_kb)

# ─────────────────────────────────────────────
#  Start
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("Starting Flask health server...")
    threading.Thread(target=run_flask, daemon=True).start()

    print("Clearing any existing webhook...")
    req.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
            params={"drop_pending_updates": "false"})
    time.sleep(2)

    print("Starting bot polling...")
    while True:
        try:
            bot.infinity_polling(
                timeout=25,
                long_polling_timeout=25,
                allowed_updates=["message", "callback_query"]
            )
        except Exception as e:
            if "409" in str(e):
                print(f"409 conflict, waiting 15s...")
                time.sleep(15)
            else:
                print(f"Polling error: {e}, retrying in 5s...")
                time.sleep(5)
