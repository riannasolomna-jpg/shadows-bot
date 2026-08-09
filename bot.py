import os
import re
import time
import json
import threading
import traceback
from threading import Thread
from flask import Flask
import telebot
from telebot import types
import groq

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ADMIN_ID = 5076963429

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN)
client = groq.Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Файл состояния. Для Render Persistent Disk можно задать:
# PERSISTENCE_FILE=/var/data/bot_state.json
PERSISTENCE_FILE = os.environ.get("PERSISTENCE_FILE", "bot_state.json")
STATE_LOCK = threading.RLock()

user_buffers = {}
user_media = {}
user_timers = {}
user_locks = {}
user_categories = {}
user_last_messages = {}
user_finish_buttons = {}

BUFFER_SECONDS = 30
MIN_ANKETA_LENGTH = 100
MAX_TELEGRAM_TEXT = 4096
POLLING_RESTART_SECONDS = 5

WELCOME_TEXT = (
    "👋 Приветствуем!\n\n"
    "Для вступления нажмите кнопку «📝 Отправить анкету» и выберите категорию персонажа.\n\n"
    "📌 Как работает проверка:\n"
    "• Все первичные ошибки и замечания формирует автоматический бот-модератор.\n"
    "• Бот объединяет ваши сообщения в течение 30 секунд в одну анкету — отправляйте части подряд.\n"
    "• После отправки бот сразу же выдаст вам список правок или подтвердит принятие.\n"
    "• Как только ваша анкета будет полностью одобрена ботом, он автоматически отправит её на окончательное рассмотрение администрации.\n"
    "• Если анкета содержит грубые ошибки, выдуманные сведения или не проходит обязательные критерии, администрация её не получит.\n\n"
    "❓ По любым возникшим проблемам и вопросам обращайтесь к @CrazyCrabSalad."
)

SYSTEM_PROMPT = """
Ты — строгий помощник модератора текстовой ролевой игры по фандому
«Дом, в котором».

ВАЖНЕЙШЕЕ ПРАВИЛО:
НЕ ВЫДУМЫВАЙ ЗАМЕЧАНИЯ.
Замечание можно делать только тогда, когда оно прямо подтверждается
текстом анкеты или явно следует из перечисленных ниже обязательных критериев.
Если сомневаешься — НЕ считай это ошибкой.
Не требуй того, чего нет в критериях.
Не придумывай требования к стилю, биографии, стае или лору.
Не отклоняй анкету только потому, что персонаж тебе не нравится.

КАТЕГОРИИ:
- «Домовец» — проверяется по правилам Домовца.
- «Персонал» — сюда относятся все сотрудники/персонал.
- Если категория «Другое», рассматривай её как ПЕРСОНАЛ.
- Категории «Наружник» больше НЕ существует.

ОБЯЗАТЕЛЬНЫЕ ПУНКТЫ ДЛЯ «ДОМОВЦА»:
1. Кличка.
2. Стая: Жрецы, Искры, Гавена, Утопленники, Кометы, Орфы.
   Мистерийцы допустимы только если игрок действительно использует эту стаю
   по актуальному лору.
3. Пол.
4. Возраст — строго 14–18 лет.
5. Заболевание — СТРОГО ОБЯЗАТЕЛЬНЫЙ ПУНКТ.
   Пункт считается выполненным, если:
   а) указано физическое заболевание/инвалидность;
   ИЛИ
   б) в биографии есть логичное объяснение попадания в Дом через
   доплату, связи, взятку, перевод по блату и т.п.
6. Внешность.
7. Характер — минимум 200 символов.
8. Причина попадания.
9. Возраст попадания.
10. Умения.
11. Юз.

ОБЯЗАТЕЛЬНЫЕ ПУНКТЫ ДЛЯ «ПЕРСОНАЛА»:
1. Кличка.
2. Пол.
3. Возраст — 20+ лет.
4. Внешность.
5. Характер — минимум 200 символов.
6. Предыстория — минимум 50–70 символов.
7. Должность.
8. Юз.

ПРОВЕРКА ПУНКТОВ:
- Не считай пункт отсутствующим, если он просто назван немного иначе,
  но его содержание очевидно.
- Не требуй конкретного порядка пунктов.
- Не требуй идеальной разметки.
- Не придирайся к художественному стилю.
- Не считай обычную фантазию логической ошибкой.
- Логическая ошибка — только грубое противоречие внутри анкеты
  или явное нарушение возрастного/категориального критерия.
- Не проверяй «канон» по своим догадкам.

ДУБЛИКАТЫ:
- Если один и тот же пункт явно указан два раза и это не продолжение текста,
  укажи дублирование.
- Если весь текст анкеты или большой фрагмент буквально продублирован подряд,
  укажи, что текст продублирован.
- Не считай обычное повторение слов внутри описания дубликатом пункта.

ОБЪЁМ:
- Характер: минимум 200 символов.
- Предыстория персонала: минимум 50–70 символов.
- Не устанавливай другие минимумы.

ОРФОГРАФИЯ И ПУНКТУАЦИЯ:
- Указывай только ЯВНЫЕ ошибки и опечатки.
- Для каждой ошибки приводи конкретный фрагмент и исправление.
- Не переписывай весь текст ради стилистических предпочтений.
- Если слово может быть авторским, сленговым или намеренно необычным,
  не объявляй его ошибкой без уверенности.
- Грубые ошибки обязательных пунктов важнее мелких запятых.

АНТИ-БРЕД:
Если сообщение не похоже на анкету персонажа, например это набор случайных слов,
спам, бессмысленный текст, попытка обойти проверку или текст без структуры,
статус должен быть «Требует правок».
Но не называй бредом короткое/неидеально оформленное описание,
если обязательные пункты реально можно распознать.

АПЕЛЛЯЦИЯ:
Если в анкете встречается слово «Апелляция» и есть раздел «Пояснение:»,
считай это заявкой на апелляцию.
Не отклоняй её только за несогласие с предыдущим замечанием.
В отчёте отдельно укажи, что это апелляция и что окончательное решение
остаётся за администрацией.

ФОРМАТ ОТВЕТА — СТРОГО:

СТАТУС: [Принять / Требует правок]

ЗАМЕЧАНИЯ ДЛЯ ИГРОКА:
Если есть хотя бы одна подтверждённая проблема:
1. [конкретное замечание]
2. [конкретное замечание]
...
Если подтверждённых проблем НЕТ:
Нет

ОТЧЕТ ДЛЯ АДМИНА:
[Краткое резюме в 2–3 предложениях.]

ПОМНИ:
- Никаких выдуманных ошибок.
- Никаких скрытых критериев.
- Никаких «мне кажется».
- Если всё обязательное есть и явных проблем нет — обязательно «Принять».
"""

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!", 200

@app.route("/health")
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 1000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)

def save_state():
    with STATE_LOCK:
        data = {
            "user_buffers": user_buffers,
            "user_media": user_media,
            "user_categories": user_categories,
            "user_last_messages": {
                str(k): list(v) if isinstance(v, tuple) else v
                for k, v in user_last_messages.items()
            },
        }
        path = PERSISTENCE_FILE
        tmp = path + ".tmp"
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            print(f"[STATE] Состояние сохранено: {path}", flush=True)
        except Exception as e:
            print(f"[STATE] Ошибка сохранения: {type(e).__name__}: {e}", flush=True)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

def load_state():
    with STATE_LOCK:
        path = PERSISTENCE_FILE
        if not os.path.exists(path):
            print("[STATE] Файл состояния не найден.", flush=True)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            user_buffers.clear()
            user_buffers.update({int(k): v for k, v in data.get("user_buffers", {}).items()})
            user_media.clear()
            user_media.update({int(k): v for k, v in data.get("user_media", {}).items()})
            user_categories.clear()
            user_categories.update({int(k): v for k, v in data.get("user_categories", {}).items()})
            user_last_messages.clear()
            for k, v in data.get("user_last_messages", {}).items():
                user_last_messages[int(k)] = tuple(v) if isinstance(v, list) else v
            print(f"[STATE] Состояние загружено: {path}", flush=True)
        except Exception as e:
            print(f"[STATE] Ошибка загрузки: {type(e).__name__}: {e}", flush=True)

def schedule_recovered_timers():
    with STATE_LOCK:
        chat_ids = list(user_buffers.keys())
    for chat_id in chat_ids:
        if user_categories.get(chat_id):
            schedule_analysis(chat_id)

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton("📝 Отправить анкету"),
               types.KeyboardButton("📩 Апелляция"))
    markup.row(types.KeyboardButton("❓ Помощь"))
    return markup

def get_categories_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🏠 Домовец", callback_data="cat_домовец"),
        types.InlineKeyboardButton("👤 Персонал", callback_data="cat_персонал"),
        types.InlineKeyboardButton("📌 Другое", callback_data="cat_другое")
    )
    return markup

def get_finish_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "✅ Закончить отправку анкеты",
        callback_data="finish_anketa"
    ))
    return markup

def cancel_user_timer(chat_id):
    timer = user_timers.pop(chat_id, None)
    if timer:
        try:
            timer.cancel()
        except Exception:
            pass

def remove_old_finish_button(chat_id):
    msg_id = user_finish_buttons.pop(chat_id, None)
    if msg_id:
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

def clear_user_buffer(chat_id):
    cancel_user_timer(chat_id)
    remove_old_finish_button(chat_id)
    with STATE_LOCK:
        user_buffers.pop(chat_id, None)
        user_media.pop(chat_id, None)
        user_locks.pop(chat_id, None)
        user_categories.pop(chat_id, None)
        user_last_messages.pop(chat_id, None)
    save_state()

def safe_send(chat_id, text, **kwargs):
    kwargs.pop("parse_mode", None)
    return bot.send_message(chat_id, text, **kwargs)

def split_for_telegram(text, limit=MAX_TELEGRAM_TEXT):
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.splitlines(True):
        if len(current) + len(line) <= limit:
            current += line
        else:
            if current:
                chunks.append(current)
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            current = line
    if current:
        chunks.append(current)
    return chunks

def send_long_message(chat_id, text, reply_markup=None):
    chunks = split_for_telegram(text)
    last_msg = None
    for i, chunk in enumerate(chunks):
        last_msg = safe_send(
            chat_id,
            chunk,
            reply_markup=reply_markup if i == len(chunks) - 1 else None
        )
    return last_msg

def normalize_category(raw):
    raw = raw.strip().lower()
    if raw == "домовец":
        return "Домовец"
    if raw in ("персонал", "другое"):
        return "Персонал"
    return raw.capitalize()

def extract_status(report):
    first_500 = report[:500].lower()
    if re.search(r"статус\s*:\s*требует\s+правок", first_500):
        return False
    if re.search(r"статус\s*:\s*принять", first_500):
        return True
    return False

def safe_media_record(message, kind):
    record = {
        "kind": kind,
        "message_id": message.message_id,
        "caption": (message.caption or "").strip(),
        "file_id": None,
        "file_name": None,
        "mime_type": None
    }
    if kind == "photo" and message.photo:
        record["file_id"] = message.photo[-1].file_id
    elif kind == "audio" and message.audio:
        record["file_id"] = message.audio.file_id
        record["file_name"] = message.audio.file_name
        record["mime_type"] = message.audio.mime_type
    elif kind == "document" and message.document:
        record["file_id"] = message.document.file_id
        record["file_name"] = message.document.file_name
        record["mime_type"] = message.document.mime_type
    elif kind == "voice" and message.voice:
        record["file_id"] = message.voice.file_id
        record["mime_type"] = message.voice.mime_type
    return record

def append_media(chat_id, record):
    with STATE_LOCK:
        user_media.setdefault(chat_id, []).append(record)
    save_state()

def media_count(chat_id):
    return len(user_media.get(chat_id, []))

def send_media_to_admin(chat_id, records):
    for index, record in enumerate(records, 1):
        try:
            kind = record.get("kind")
            file_id = record.get("file_id")
            caption = record.get("caption", "") or ""
            caption = f"📎 Вложение {index}/{len(records)}" + (f"\n{caption}" if caption else "")
            if kind == "photo":
                bot.send_photo(ADMIN_ID, file_id, caption=caption)
            elif kind == "audio":
                bot.send_audio(ADMIN_ID, file_id, caption=caption)
            elif kind == "document":
                bot.send_document(ADMIN_ID, file_id, caption=caption)
            elif kind == "voice":
                bot.send_voice(ADMIN_ID, file_id, caption=caption)
        except Exception as e:
            safe_send(ADMIN_ID, f"⚠️ Не удалось передать вложение {index}/{len(records)} от пользователя {chat_id}: {type(e).__name__}: {e}")

def analyze_anketa_with_ai(text, category, appeal=False):
    if not client:
        return None, "Ошибка ИИ: не настроен GROQ_API_KEY."
    category_for_ai = "Домовец" if category == "Домовец" else "Персонал"
    extra = ""
    if appeal:
        extra = """
ЭТО АПЕЛЛЯЦИЯ.
В тексте есть слово «Апелляция» и раздел «Пояснение:».
Не придумывай новые нарушения. Проверь только объективные критерии.
В отчёте обязательно укажи, что это апелляция и что окончательное решение
по спорному вопросу принимает администрация.
"""
    user_prompt = f"""
КАТЕГОРИЯ: {category_for_ai}
АПЕЛЛЯЦИЯ: {"ДА" if appeal else "НЕТ"}

АНКЕТА:
----------------
{text}
----------------

{extra}

Проведи проверку строго по SYSTEM PROMPT.
Каждое замечание должно иметь конкретное доказательство в тексте.
Если не можешь показать конкретный фрагмент или конкретное нарушенное
правило — НЕ ПИШИ такое замечание.

Особенно проверь:
- отсутствие обязательных пунктов;
- возраст;
- минимальные объёмы;
- явные опечатки;
- грубые противоречия;
- явные дубликаты;
- очевидный бред/спам.

Не добавляй требований от себя.
"""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
            max_tokens=1400
        )
        result = response.choices[0].message.content.strip()
        return extract_status(result), result
    except Exception as e:
        print(f"[AI] Ошибка: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return None, f"Ошибка ИИ: {type(e).__name__}: {e}"

@bot.message_handler(commands=["start"])
def send_welcome(message):
    clear_user_buffer(message.chat.id)
    safe_send(message.chat.id, WELCOME_TEXT, reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda msg: msg.text in [
    "📝 Отправить анкету", "📩 Апелляция", "❓ Помощь"
])
def handle_menu_click(message):
    chat_id = message.chat.id
    if message.text == "📝 Отправить анкету":
        clear_user_buffer(chat_id)
        safe_send(chat_id, "Выберите категорию анкеты:",
                  reply_markup=get_categories_keyboard())
        return

    if message.text == "📩 Апелляция":
        clear_user_buffer(chat_id)
        user_categories[chat_id] = "Апелляция"
        save_state()
        msg = safe_send(
            chat_id,
            "📩 Апелляция\n\n"
            "Отправьте анкету одним или несколькими сообщениями.\n"
            "Можно прикладывать текст, фотографии, музыку и документы.\n"
            "Обязательно добавьте в текст:\n"
            "• слово «Апелляция»;\n"
            "• раздел «Пояснение:» — здесь аргументируйте, почему не согласны "
            "с замечаниями бота.\n\n"
            "Анкета вместе с пояснением будет передана администрации.",
            reply_markup=get_finish_keyboard()
        )
        user_finish_buttons[chat_id] = msg.message_id
        return

    safe_send(
        chat_id,
        "❓ Помощь\n\n"
        "Если анкета состоит из нескольких частей, отправляйте их подряд "
        "в течение 30 секунд. Можно отправлять сколько угодно фотографий, "
        "музыки и документов.\n\n"
        "Когда закончите — нажмите «✅ Закончить отправку анкеты» "
        "под последним сообщением.\n\n"
        "По вопросам и проблемам: @CrazyCrabSalad",
        reply_markup=get_main_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("cat_"))
def handle_category_choice(call):
    chat_id = call.message.chat.id
    raw = call.data.replace("cat_", "", 1)
    category = normalize_category(raw)

    clear_user_buffer(chat_id)
    user_categories[chat_id] = category
    user_buffers[chat_id] = []
    user_media[chat_id] = []
    save_state()

    bot.answer_callback_query(call.id)
    msg = safe_send(
        chat_id,
        f"Выбрана категория: {category}.\n\n"
        "📌 Теперь отправляйте анкету.\n"
        "Можно одним или несколькими сообщениями.\n"
        "Можно отдельно отправлять любое количество фотографий, музыки "
        "и документов — бот сохранит их вместе с анкетой.\n\n"
        "Когда закончите — нажмите кнопку ниже.",
        reply_markup=get_finish_keyboard()
    )
    user_finish_buttons[chat_id] = msg.message_id

def schedule_analysis(chat_id):
    cancel_user_timer(chat_id)
    timer = threading.Timer(BUFFER_SECONDS, finalize_anketa, args=(chat_id,))
    timer.daemon = True
    user_timers[chat_id] = timer
    timer.start()

def append_to_buffer(chat_id, text):
    with STATE_LOCK:
        user_buffers.setdefault(chat_id, []).append(text)
    save_state()
    schedule_analysis(chat_id)

def get_category_for_chat(chat_id):
    category = user_categories.get(chat_id)
    if category == "Апелляция":
        return "Апелляция"
    if category in ("Домовец", "Персонал"):
        return category
    return None

def accept_media_message(message):
    chat_id = message.chat.id
    record = safe_media_record(message, message.content_type)
    if not record.get("file_id"):
        return False
    append_media(chat_id, record)
    schedule_analysis(chat_id)
    remove_old_finish_button(chat_id)
    total_items = len(user_buffers.get(chat_id, [])) + media_count(chat_id)
    msg = safe_send(
        chat_id,
        f"📎 Вложение получено. Всего материалов: {total_items}.\n\n"
        "Можете отправить ещё материалы или нажать кнопку ниже.",
        reply_markup=get_finish_keyboard()
    )
    user_finish_buttons[chat_id] = msg.message_id
    return True

@bot.message_handler(content_types=["text", "photo", "document", "audio", "voice"])
def receive_anketa_part(message):
    chat_id = message.chat.id
    category = get_category_for_chat(chat_id)

    if not category:
        safe_send(
            chat_id,
            "⚠️ Вы ещё не начали заполнение анкеты!\n\n"
            "Сначала нажмите «📝 Отправить анкету» и выберите категорию "
            "«🏠 Домовец», «👤 Персонал» или «📌 Другое».\n\n"
            "Для апелляции используйте кнопку «📩 Апелляция».",
            reply_markup=get_main_keyboard()
        )
        return

    text_for_key = (message.text or message.caption or "").strip()
    msg_key = (message.message_id, text_for_key, message.content_type)
    if user_last_messages.get(chat_id) == msg_key:
        return
    user_last_messages[chat_id] = msg_key
    save_state()

    if message.content_type in ("photo", "audio", "document", "voice"):
        accept_media_message(message)
        return

    if not text_for_key:
        safe_send(chat_id, "⚠️ Пожалуйста, отправляйте анкету текстовым сообщением.")
        return

    remove_old_finish_button(chat_id)
    append_to_buffer(chat_id, text_for_key)
    total_len = sum(len(x) for x in user_buffers.get(chat_id, []))
    total_media = media_count(chat_id)

    msg = safe_send(
        chat_id,
        f"📨 Часть анкеты получена (собрано ~{total_len} символов).\n"
        f"📎 Вложений сохранено: {total_media}.\n\n"
        "Отправляйте следующую часть или нажмите кнопку ниже, если закончили:",
        reply_markup=get_finish_keyboard()
    )
    user_finish_buttons[chat_id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == "finish_anketa")
def finish_anketa_callback(call):
    chat_id = call.message.chat.id
    if not get_category_for_chat(chat_id):
        bot.answer_callback_query(call.id, "Сначала начните подачу анкеты.", show_alert=True)
        return
    bot.answer_callback_query(call.id, "Анкета отправлена на проверку.")
    remove_old_finish_button(chat_id)
    finalize_anketa(chat_id)

def finalize_anketa(chat_id):
    lock = user_locks.setdefault(chat_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return

    try:
        cancel_user_timer(chat_id)
        remove_old_finish_button(chat_id)

        parts = list(user_buffers.get(chat_id, []))
        media_records = list(user_media.get(chat_id, []))
        category = get_category_for_chat(chat_id)

        if (not parts and not media_records) or not category:
            return

        text = "\n\n".join(parts).strip()
        appeal = category == "Апелляция"

        with STATE_LOCK:
            user_buffers.pop(chat_id, None)
            user_media.pop(chat_id, None)
        save_state()

        if len(text) < MIN_ANKETA_LENGTH:
            safe_send(
                chat_id,
                "❌ В текстовой части анкеты недостаточно информации для проверки.\n\n"
                f"Нужно минимум {MIN_ANKETA_LENGTH} символов текста.\n"
                "Отправьте недостающий текст и начните подачу заново.",
                reply_markup=get_main_keyboard()
            )
            user_categories.pop(chat_id, None)
            save_state()
            return

        safe_send(
            chat_id,
            "⏳ Анкета собрана. Проверяю обязательные пункты, "
            "объём, явные ошибки и логику..."
        )

        passed, report = analyze_anketa_with_ai(
            text, category if not appeal else "Домовец", appeal=appeal
        )

        if passed is None:
            safe_send(
                chat_id,
                "⚠️ Не удалось выполнить автоматическую проверку.\n\n"
                f"{report}\n\n"
                "Анкета НЕ отправлена администрации. "
                "Попробуйте отправить её ещё раз позже.",
                reply_markup=get_main_keyboard()
            )
            user_categories.pop(chat_id, None)
            save_state()
            return

        if not passed and not appeal:
            user_response = (
                "⚠️ Ваша анкета содержит замечания и требует правок:\n\n"
                f"{report}\n\n"
                "📌 Исправьте недочёты и отправьте анкету заново через меню."
                "\n\n📌 Не согласны с замечаниями бота? "
                "Вы можете подать апелляцию через кнопку «📩 Апелляция»."
            )
            send_long_message(chat_id, user_response, reply_markup=get_main_keyboard())
            user_categories.pop(chat_id, None)
            save_state()
            return

        try:
            chat_info = bot.get_chat(chat_id)
            username = f"@{chat_info.username}" if getattr(chat_info, "username", None) else "Отсутствует"
            full_name = getattr(chat_info, "full_name", None) or "Неизвестно"
        except Exception:
            username, full_name = "Отсутствует", "Неизвестно"

        admin_title = "📩 АПЕЛЛЯЦИЯ — АНКЕТА НА РАССМОТРЕНИЕ" if appeal else "📥 НОВАЯ ГОТОВАЯ АНКЕТА!"
        admin_text = (
            f"{admin_title}\n\n"
            f"👤 Игрок: {full_name}\n"
            f"🔹 Username: {username}\n"
            f"🆔 ID: {chat_id}\n"
            f"📂 Категория: {'Апелляция' if appeal else category}\n\n"
            "========== АНАЛИЗ ИИ ==========\n\n"
            f"{report}\n\n"
            "========== ПОЛНЫЙ ТЕКСТ АНКЕТЫ ==========\n\n"
            f"{text}\n\n"
            "========== ВЛОЖЕНИЯ ==========\n\n"
            f"Количество вложений: {len(media_records)}"
        )

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Принять", callback_data=f"accept_{chat_id}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{chat_id}")
        )
        markup.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{chat_id}"))

        send_long_message(ADMIN_ID, admin_text, reply_markup=markup)

        if media_records:
            send_media_to_admin(chat_id, media_records)

        if appeal:
            safe_send(
                chat_id,
                "📩 Ваша апелляция вместе с анкетой передана администрации.\n\n"
                "Ожидайте ответа владельца.",
                reply_markup=get_main_keyboard()
            )
        else:
            safe_send(
                chat_id,
                "✅ Автоматическая проверка пройдена.\n\n"
                "Ваша анкета отправлена администрации на рассмотрение.",
                reply_markup=get_main_keyboard()
            )

        user_categories.pop(chat_id, None)
        save_state()

    except Exception as e:
        print(f"[FINALIZE] Ошибка для {chat_id}: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        safe_send(
            chat_id,
            "⚠️ Во время обработки анкеты произошла техническая ошибка.\n"
            "Анкета не была передана администрации. Попробуйте ещё раз позже.",
            reply_markup=get_main_keyboard()
        )
    finally:
        lock.release()

@bot.callback_query_handler(func=lambda call: call.data.startswith(("accept_", "reject_", "reply_")))
def handle_admin_action(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "У вас нет прав администратора.", show_alert=True)
        return

    action, target_chat_id = call.data.split("_", 1)
    try:
        target_chat_id = int(target_chat_id)
    except ValueError:
        bot.answer_callback_query(call.id, "Некорректный ID.")
        return

    if action == "accept":
        safe_send(target_chat_id, "🎉 Ваша анкета успешно принята администрацией! Поздравляем!")
        bot.answer_callback_query(call.id, "Анкета принята.")
        try:
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass

    elif action == "reject":
        safe_send(
            target_chat_id,
            "❌ К сожалению, ваша анкета была отклонена администрацией.\n\n"
            "Если хотите узнать причину или не согласны с решением, "
            "обратитесь к @CrazyCrabSalad."
        )
        bot.answer_callback_query(call.id, "Анкета отклонена.")
        try:
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass

    elif action == "reply":
        msg = safe_send(ADMIN_ID, f"Введите ответ для пользователя {target_chat_id}:")
        bot.register_next_step_handler(msg, send_reply_to_user, target_chat_id)
        bot.answer_callback_query(call.id)

def send_reply_to_user(message, target_chat_id):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text or ""
    if not text.strip():
        safe_send(ADMIN_ID, "Пустое сообщение не отправлено.")
        return
    try:
        safe_send(target_chat_id, "💬 Сообщение от администрации:\n\n" + text)
        safe_send(ADMIN_ID, "✅ Сообщение успешно доставлено пользователю.")
    except Exception as e:
        safe_send(ADMIN_ID, f"❌ Не удалось доставить сообщение: {type(e).__name__}: {e}")

def run_telegram_polling():
    print("[BOT] Поток Telegram polling запущен.", flush=True)
    while True:
        try:
            print("[BOT] Запускаю Telegram polling...", flush=True)
            try:
                bot.remove_webhook()
                time.sleep(1)
            except Exception as e:
                print(f"[BOT] remove_webhook: {type(e).__name__}: {e}", flush=True)

            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True,
                allowed_updates=["message", "callback_query"]
            )

            print(
                f"[BOT] polling завершился. Перезапуск через {POLLING_RESTART_SECONDS} сек.",
                flush=True
            )
        except Exception as e:
            print(f"[BOT] polling упал: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
        time.sleep(POLLING_RESTART_SECONDS)

if __name__ == "__main__":
    print("============================================================", flush=True)
    print("[START] Запуск бота...", flush=True)
    print(f"[START] PID: {os.getpid()}", flush=True)
    print(f"[START] Файл состояния: {PERSISTENCE_FILE}", flush=True)

    load_state()

    flask_thread = Thread(target=run_flask, daemon=True, name="flask-thread")
    flask_thread.start()
    print("[START] Flask запущен.", flush=True)

    schedule_recovered_timers()

    telegram_thread = Thread(
        target=run_telegram_polling,
        daemon=False,
        name="telegram-polling-thread"
    )
    telegram_thread.start()
    print("[START] Telegram polling запущен.", flush=True)

    telegram_thread.join()
