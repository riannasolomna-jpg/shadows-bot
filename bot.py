import os
import re
import json
import time
import threading
from flask import Flask
import telebot
from telebot import types
import groq

# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ADMIN_ID = 5076963429

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN)
client = groq.Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

BUFFER_SECONDS = 30
MIN_ANKETA_LENGTH = 100
MAX_TELEGRAM_TEXT = 4096

# На Render можно задать PERSISTENCE_FILE=/var/data/bot_state.json
PERSISTENCE_FILE = os.environ.get("PERSISTENCE_FILE", "bot_state.json")

# Несколько быстрых действий подряд объединяются в одну запись.
SAVE_DELAY = 2.0

user_buffers = {}
user_timers = {}
user_locks = {}
user_categories = {}
user_last_messages = {}
user_finish_buttons = {}
user_media = {}

state_lock = threading.RLock()
save_timer = None

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
2. Стая:
   Жрецы, Искры, Гавена, Утопленники, Кометы, Орфы.
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
   Если есть хотя бы одно из двух — пункт пройден.
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
- Логической ошибкой является только грубое противоречие внутри самой анкеты
  или явное нарушение указанного возрастного/категориального критерия.
- Не проверяй «канон» по своим догадкам. Если правило не дано выше,
  не используй его как основание для отказа.

ДУБЛИКАТЫ:
- Если один и тот же пункт явно указан два раза и это не продолжение текста,
  укажи дублирование.
- Если весь текст анкеты или большой фрагмент буквально продублирован подряд,
  укажи, что текст продублирован.
- Не считай обычное повторение слов внутри описания дубликатом пункта.

ОБЪЁМ:
- Характер: минимум 200 символов.
- Предыстория персонала: минимум 50–70 символов.
- Не устанавливай другие минимумы, которых нет в критериях.

ОРФОГРАФИЯ И ПУНКТУАЦИЯ:
- Указывай только ЯВНЫЕ ошибки и опечатки.
- Для каждой ошибки приводи конкретный фрагмент и исправление.
- Не переписывай весь текст ради стилистических предпочтений.
- Если слово может быть авторским, сленговым или намеренно необычным,
  не объявляй его ошибкой без уверенности.
- Явные ошибки вроде «птиць» → «птиц», «видет» → «видит»,
  «недостаточност» → «недостаточность» можно указывать.
- Грубые ошибки в обязательных пунктах важнее мелких запятых.

АНТИ-БРЕД:
Если сообщение не похоже на анкету персонажа, например это набор случайных слов,
спам, бессмысленный текст, попытка обойти проверку или текст без структуры,
статус должен быть «Требует правок».
Но не называй бредом просто короткое/неидеально оформленное описание,
если обязательные пункты реально можно распознать.

АПЕЛЛЯЦИЯ:
Если в анкете встречается слово «Апелляция» и есть раздел
«Пояснение:», считай это заявкой на апелляцию.
Не отклоняй её только за то, что автор не согласен с предыдущим замечанием.
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

# ============================================================
# FLASK / RENDER
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!", 200

@app.route("/health")
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 1000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )

# ============================================================
# СОХРАНЕНИЕ СОСТОЯНИЯ
# ============================================================

def _snapshot_state():
    with state_lock:
        return {
            "user_buffers": {
                str(k): v for k, v in user_buffers.items()
            },
            "user_categories": {
                str(k): v for k, v in user_categories.items()
            },
            "user_last_messages": {
                str(k): list(v) if isinstance(v, tuple) else v
                for k, v in user_last_messages.items()
            },
            "user_media": {
                str(k): v for k, v in user_media.items()
            }
        }

def _write_state():
    try:
        data = _snapshot_state()

        directory = os.path.dirname(PERSISTENCE_FILE)
        if directory:
            os.makedirs(directory, exist_ok=True)

        temp_file = PERSISTENCE_FILE + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp_file, PERSISTENCE_FILE)

        print(
            f"[STATE] Состояние сохранено: {PERSISTENCE_FILE}",
            flush=True
        )

    except Exception as e:
        print(
            f"[STATE] Ошибка сохранения: {type(e).__name__}: {e}",
            flush=True
        )

def save_state():
    global save_timer

    with state_lock:
        if save_timer is not None:
            try:
                save_timer.cancel()
            except Exception:
                pass

        save_timer = threading.Timer(
            SAVE_DELAY,
            _write_state
        )
        save_timer.daemon = True
        save_timer.start()

def load_state():
    if not os.path.exists(PERSISTENCE_FILE):
        print(
            f"[STATE] Файл состояния не найден: {PERSISTENCE_FILE}",
            flush=True
        )
        return

    try:
        with open(PERSISTENCE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        with state_lock:
            user_buffers.clear()
            user_categories.clear()
            user_last_messages.clear()
            user_media.clear()

            for k, v in data.get(
                "user_buffers",
                {}
            ).items():
                user_buffers[int(k)] = v

            for k, v in data.get(
                "user_categories",
                {}
            ).items():
                user_categories[int(k)] = v

            for k, v in data.get(
                "user_last_messages",
                {}
            ).items():
                user_last_messages[int(k)] = (
                    tuple(v)
                    if isinstance(v, list)
                    else v
                )

            for k, v in data.get(
                "user_media",
                {}
            ).items():
                user_media[int(k)] = v

        print(
            "[STATE] Состояние восстановлено.",
            flush=True
        )

        for chat_id in list(
            user_buffers.keys()
        ):
            if get_category_for_chat(chat_id):
                schedule_analysis(chat_id)

    except Exception as e:
        print(
            f"[STATE] Ошибка загрузки: "
            f"{type(e).__name__}: {e}",
            flush=True
        )

# ============================================================
# КНОПКИ
# ============================================================

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    markup.row(
        types.KeyboardButton(
            "📝 Отправить анкету"
        ),
        types.KeyboardButton(
            "📩 Апелляция"
        )
    )

    markup.row(
        types.KeyboardButton("❓ Помощь")
    )

    return markup

def get_categories_keyboard():
    markup = types.InlineKeyboardMarkup(
        row_width=2
    )

    markup.add(
        types.InlineKeyboardButton(
            "🏠 Домовец",
            callback_data="cat_домовец"
        ),
        types.InlineKeyboardButton(
            "👤 Персонал",
            callback_data="cat_персонал"
        ),
        types.InlineKeyboardButton(
            "📌 Другое",
            callback_data="cat_другое"
        )
    )

    return markup

def get_finish_keyboard():
    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            "✅ Закончить отправку анкеты",
            callback_data="finish_anketa"
        )
    )

    return markup

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def cancel_user_timer(chat_id):
    timer = user_timers.pop(
        chat_id,
        None
    )

    if timer:
        try:
            timer.cancel()
        except Exception:
            pass

def remove_old_finish_button(chat_id):
    msg_id = user_finish_buttons.pop(
        chat_id,
        None
    )

    if msg_id:
        try:
            bot.delete_message(
                chat_id,
                msg_id
            )
        except Exception:
            pass

def clear_user_buffer(chat_id):
    cancel_user_timer(chat_id)
    remove_old_finish_button(chat_id)

    with state_lock:
        user_buffers.pop(chat_id, None)
        user_locks.pop(chat_id, None)
        user_categories.pop(chat_id, None)
        user_last_messages.pop(chat_id, None)
        user_media.pop(chat_id, None)

    save_state()

def safe_send(chat_id, text, **kwargs):
    kwargs.pop(
        "parse_mode",
        None
    )

    return bot.send_message(
        chat_id,
        text,
        **kwargs
    )

def split_for_telegram(
    text,
    limit=MAX_TELEGRAM_TEXT
):
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""

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

def send_long_message(
    chat_id,
    text,
    reply_markup=None
):
    chunks = split_for_telegram(text)
    last_msg = None

    for i, chunk in enumerate(chunks):
        markup = (
            reply_markup
            if i == len(chunks) - 1
            else None
        )

        last_msg = safe_send(
            chat_id,
            chunk,
            reply_markup=markup
        )

    return last_msg

def normalize_category(raw):
    raw = raw.strip().lower()

    if raw == "домовец":
        return "Домовец"

    if raw in (
        "персонал",
        "другое"
    ):
        return "Персонал"

    return raw.capitalize()

def extract_status(report):
    first_500 = report[:500].lower()

    if re.search(
        r"статус\s*:\s*требует\s+правок",
        first_500
    ):
        return False

    if re.search(
        r"статус\s*:\s*принять",
        first_500
    ):
        return True

    return False

# ============================================================
# ИИ
# ============================================================

def analyze_anketa_with_ai(
    text,
    category,
    appeal=False
):
    if not client:
        return (
            None,
            "Ошибка ИИ: не настроен GROQ_API_KEY."
        )

    category_for_ai = (
        "Домовец"
        if category == "Домовец"
        else "Персонал"
    )

    extra = ""

    if appeal:
        extra = (
            "ЭТО АПЕЛЛЯЦИЯ.\n"
            "В тексте есть слово «Апелляция» "
            "и раздел «Пояснение:».\n"
            "Не придумывай новые нарушения. "
            "Проверь только объективные критерии.\n"
            "В отчёте обязательно укажи, что это апелляция "
            "и что окончательное решение по спорному вопросу "
            "принимает администрация."
        )

    user_prompt = (
        f"КАТЕГОРИЯ: {category_for_ai}\n"
        f"АПЕЛЛЯЦИЯ: {'ДА' if appeal else 'НЕТ'}\n\n"
        "АНКЕТА:\n"
        "----------------\n"
        f"{text}\n"
        "----------------\n\n"
        f"{extra}\n\n"
        "Проведи проверку строго по SYSTEM PROMPT.\n"
        "Каждое замечание должно иметь конкретное доказательство "
        "в тексте.\n"
        "Если не можешь показать конкретный фрагмент или конкретное "
        "нарушенное правило — НЕ ПИШИ такое замечание.\n\n"
        "Особенно проверь:\n"
        "- отсутствие обязательных пунктов;\n"
        "- возраст;\n"
        "- минимальные объёмы;\n"
        "- явные опечатки;\n"
        "- грубые противоречия;\n"
        "- явные дубликаты;\n"
        "- очевидный бред/спам.\n\n"
        "Не добавляй требований от себя."
    )

    try:
        print(
            "[AI] Начинаю проверку анкеты.",
            flush=True
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            temperature=0.0,
            max_tokens=1400
        )

        result = (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

        passed = extract_status(result)

        print(
            "[AI] Проверка завершена. "
            f"Статус: "
            f"{'Принять' if passed else 'Требует правок'}",
            flush=True
        )

        return passed, result

    except Exception as e:
        print(
            f"[AI] Ошибка: {type(e).__name__}: {e}",
            flush=True
        )

        return (
            None,
            f"Ошибка ИИ: {type(e).__name__}: {e}"
        )

# ============================================================
# /START
# ============================================================

@bot.message_handler(commands=["start"])
def send_welcome(message):
    chat_id = message.chat.id

    clear_user_buffer(chat_id)

    safe_send(
        chat_id,
        WELCOME_TEXT,
        reply_markup=get_main_keyboard()
    )

# ============================================================
# МЕНЮ
# ============================================================

@bot.message_handler(
    func=lambda msg: msg.text in [
        "📝 Отправить анкету",
        "📩 Апелляция",
        "❓ Помощь"
    ]
)
def handle_menu_click(message):
    chat_id = message.chat.id

    if message.text == "📝 Отправить анкету":
        clear_user_buffer(chat_id)

        safe_send(
            chat_id,
            "Выберите категорию анкеты:",
            reply_markup=get_categories_keyboard()
        )
        return

    if message.text == "📩 Апелляция":
        clear_user_buffer(chat_id)

        user_categories[chat_id] = "Апелляция"
        save_state()

        msg = safe_send(
            chat_id,
            "📩 Апелляция\n\n"
            "Отправьте анкету одним или несколькими сообщениями.\n"
            "Обязательно добавьте в текст:\n"
            "• слово «Апелляция»;\n"
            "• раздел «Пояснение:» — здесь аргументируйте, почему "
            "не согласны с замечаниями бота.\n\n"
            "Анкета вместе с пояснением будет передана администрации.",
            reply_markup=get_finish_keyboard()
        )

        user_finish_buttons[
            chat_id
        ] = msg.message_id

        return

    safe_send(
        chat_id,
        "❓ Помощь\n\n"
        "Если анкета состоит из нескольких частей, отправляйте их подряд "
        "в течение 30 секунд. Когда закончите — нажмите "
        "«✅ Закончить отправку анкеты» под последним сообщением.\n\n"
        "По вопросам и проблемам: @CrazyCrabSalad",
        reply_markup=get_main_keyboard()
    )

# ============================================================
# ВЫБОР КАТЕГОРИИ
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("cat_")
)
def handle_category_choice(call):
    chat_id = call.message.chat.id

    raw = call.data.replace(
        "cat_",
        "",
        1
    )

    category = normalize_category(raw)

    user_categories[chat_id] = category
    user_buffers[chat_id] = []
    user_media[chat_id] = []

    cancel_user_timer(chat_id)
    save_state()

    bot.answer_callback_query(call.id)

    msg = safe_send(
        chat_id,
        f"Выбрана категория: {category}.\n\n"
        "📌 Теперь отправляйте анкету.\n"
        "Можно одним или несколькими сообщениями.\n"
        "Можно отдельно отправлять текст, любое количество фотографий, "
        "музыки, документов и голосовых.\n\n"
        "Когда закончите — нажмите кнопку ниже.",
        reply_markup=get_finish_keyboard()
    )

    user_finish_buttons[
        chat_id
    ] = msg.message_id

# ============================================================
# СБОР АНКЕТЫ
# ============================================================

def schedule_analysis(chat_id):
    cancel_user_timer(chat_id)

    timer = threading.Timer(
        BUFFER_SECONDS,
        finalize_anketa,
        args=(chat_id,)
    )

    timer.daemon = True
    user_timers[chat_id] = timer
    timer.start()

def append_to_buffer(
    chat_id,
    text
):
    user_buffers.setdefault(
        chat_id,
        []
    ).append(text)

    save_state()
    schedule_analysis(chat_id)

def get_category_for_chat(chat_id):
    category = user_categories.get(chat_id)

    if category == "Апелляция":
        return "Апелляция"

    if category in (
        "Домовец",
        "Персонал"
    ):
        return category

    return None

def add_media(
    chat_id,
    media_type,
    file_id,
    caption=""
):
    user_media.setdefault(
        chat_id,
        []
    ).append(
        {
            "type": media_type,
            "file_id": file_id,
            "caption": caption or ""
        }
    )

    save_state()

# ============================================================
# ПРИЁМ ТЕКСТА И МЕДИА
# ============================================================

@bot.message_handler(
    content_types=[
        "text",
        "photo",
        "document",
        "audio",
        "voice",
        "video"
    ]
)
def receive_anketa_part(message):
    chat_id = message.chat.id

    category = get_category_for_chat(
        chat_id
    )

    if not category:
        safe_send(
            chat_id,
            "⚠️ Вы ещё не начали заполнение анкеты!\n\n"
            "Пожалуйста, сначала нажмите кнопку «📝 Отправить анкету» "
            "и выберите категорию персонажа.",
            reply_markup=get_main_keyboard()
        )
        return

    text = (
        message.text
        or message.caption
        or ""
    ).strip()

    msg_key = (
        message.message_id,
        text
    )

    if user_last_messages.get(
        chat_id
    ) == msg_key:
        return

    user_last_messages[
        chat_id
    ] = msg_key

    remove_old_finish_button(
        chat_id
    )

    if text:
        append_to_buffer(
            chat_id,
            text
        )

    if message.content_type == "photo":
        add_media(
            chat_id,
            "photo",
            message.photo[-1].file_id,
            message.caption or ""
        )

    elif message.content_type == "audio":
        add_media(
            chat_id,
            "audio",
            message.audio.file_id,
            message.caption or ""
        )

    elif message.content_type == "document":
        add_media(
            chat_id,
            "document",
            message.document.file_id,
            message.caption or ""
        )

    elif message.content_type == "voice":
        add_media(
            chat_id,
            "voice",
            message.voice.file_id,
            message.caption or ""
        )

    elif message.content_type == "video":
        add_media(
            chat_id,
            "video",
            message.video.file_id,
            message.caption or ""
        )

    elif not text:
        safe_send(
            chat_id,
            "⚠️ Этот тип сообщения пока не поддерживается."
        )
        return

    total_len = sum(
        len(x)
        for x in user_buffers.get(
            chat_id,
            []
        )
    )

    media_count = len(
        user_media.get(
            chat_id,
            []
        )
    )

    msg = safe_send(
        chat_id,
        f"📨 Материал получен "
        f"(текст ~{total_len} символов, "
        f"вложений: {media_count}).\n\n"
        "Отправляйте следующую часть или нажмите кнопку ниже, "
        "если закончили:",
        reply_markup=get_finish_keyboard()
    )

    user_finish_buttons[
        chat_id
    ] = msg.message_id

    schedule_analysis(
        chat_id
    )

# ============================================================
# ДОСРОЧНОЕ ЗАВЕРШЕНИЕ
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "finish_anketa"
)
def finish_anketa_callback(call):
    chat_id = call.message.chat.id

    bot.answer_callback_query(
        call.id,
        "Анкета отправлена на проверку."
    )

    remove_old_finish_button(
        chat_id
    )

    finalize_anketa(
        chat_id
    )

# ============================================================
# ОТПРАВКА ВЛОЖЕНИЙ АДМИНУ
# ============================================================

def send_media_to_admin(
    media_items,
    target_chat_id
):
    for index, item in enumerate(
        media_items,
        start=1
    ):
        try:
            caption = (
                f"📎 Вложение "
                f"{index}/{len(media_items)}"
            )

            if item.get("caption"):
                caption += (
                    "\n"
                    + item["caption"]
                )

            caption = caption[:1024]

            if item["type"] == "photo":
                bot.send_photo(
                    target_chat_id,
                    item["file_id"],
                    caption=caption
                )

            elif item["type"] == "audio":
                bot.send_audio(
                    target_chat_id,
                    item["file_id"],
                    caption=caption
                )

            elif item["type"] == "document":
                bot.send_document(
                    target_chat_id,
                    item["file_id"],
                    caption=caption
                )

            elif item["type"] == "voice":
                bot.send_voice(
                    target_chat_id,
                    item["file_id"],
                    caption=caption
                )

            elif item["type"] == "video":
                bot.send_video(
                    target_chat_id,
                    item["file_id"],
                    caption=caption
                )

        except Exception as e:
            print(
                f"[MEDIA] Ошибка отправки вложения: "
                f"{type(e).__name__}: {e}",
                flush=True
            )

            safe_send(
                target_chat_id,
                f"⚠️ Не удалось передать вложение: {e}"
            )

# ============================================================
# ФИНАЛИЗАЦИЯ
# ============================================================

def finalize_anketa(chat_id):
    lock = user_locks.setdefault(
        chat_id,
        threading.Lock()
    )

    if not lock.acquire(
        blocking=False
    ):
        return

    try:
        cancel_user_timer(
            chat_id
        )

        remove_old_finish_button(
            chat_id
        )

        parts = user_buffers.get(
            chat_id,
            []
        )

        media_items = list(
            user_media.get(
                chat_id,
                []
            )
        )

        category = get_category_for_chat(
            chat_id
        )

        if not category:
            return

        if not parts and not media_items:
            return

        text = "\n\n".join(
            parts
        ).strip()

        appeal = (
            category == "Апелляция"
        )

        user_buffers.pop(
            chat_id,
            None
        )

        user_media.pop(
            chat_id,
            None
        )

        save_state()

        if len(text) < MIN_ANKETA_LENGTH:
            safe_send(
                chat_id,
                "❌ Анкета слишком короткая для проверки.\n\n"
                f"Минимум для запуска проверки: "
                f"{MIN_ANKETA_LENGTH} символов.\n"
                "Отправьте недостающую информацию и начните "
                "подачу анкеты заново.",
                reply_markup=get_main_keyboard()
            )

            user_categories.pop(
                chat_id,
                None
            )

            save_state()
            return

        safe_send(
            chat_id,
            "⏳ Анкета собрана. Проверяю обязательные пункты, "
            "объём, явные ошибки и логику..."
        )

        passed, report = analyze_anketa_with_ai(
            text,
            category
            if not appeal
            else "Домовец",
            appeal=appeal
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

            user_categories.pop(
                chat_id,
                None
            )

            save_state()
            return

        if (
            not passed
            and not appeal
        ):
            user_response = (
                "⚠️ Ваша анкета содержит замечания и требует правок:\n\n"
                f"{report}\n\n"
                "📌 Исправьте недочёты и отправьте анкету заново через меню.\n\n"
                "📌 Не согласны с замечаниями бота? Вы можете подать апелляцию "
                "через кнопку «📩 Апелляция»."
            )

            send_long_message(
                chat_id,
                user_response,
                reply_markup=get_main_keyboard()
            )

            user_categories.pop(
                chat_id,
                None
            )

            save_state()
            return

        try:
            chat_info = bot.get_chat(
                chat_id
            )

            username = (
                f"@{chat_info.username}"
                if getattr(
                    chat_info,
                    "username",
                    None
                )
                else "Отсутствует"
            )

            full_name = (
                getattr(
                    chat_info,
                    "full_name",
                    None
                )
                or "Неизвестно"
            )

        except Exception:
            username = "Отсутствует"
            full_name = "Неизвестно"

        admin_title = (
            "📩 АПЕЛЛЯЦИЯ — АНКЕТА НА РАССМОТРЕНИЕ"
            if appeal
            else "📥 НОВАЯ ГОТОВАЯ АНКЕТА!"
        )

        admin_text = (
            f"{admin_title}\n\n"
            f"👤 Игрок: {full_name}\n"
            f"🔹 Username: {username}\n"
            f"🆔 ID: {chat_id}\n"
            f"📂 Категория: "
            f"{'Апелляция' if appeal else category}\n\n"
            "========== АНАЛИЗ ИИ ==========\n\n"
            f"{report}\n\n"
            "========== ПОЛНЫЙ ТЕКСТ АНКЕТЫ ==========\n\n"
            f"{text or '[Текст отсутствует — только вложения]'}\n\n"
            f"📎 Вложений: {len(media_items)}"
        )

        markup = types.InlineKeyboardMarkup(
            row_width=2
        )

        markup.add(
            types.InlineKeyboardButton(
                "✅ Принять",
                callback_data=f"accept_{chat_id}"
            ),
            types.InlineKeyboardButton(
                "❌ Отклонить",
                callback_data=f"reject_{chat_id}"
            )
        )

        markup.add(
            types.InlineKeyboardButton(
                "💬 Ответить",
                callback_data=f"reply_{chat_id}"
            )
        )

        send_long_message(
            ADMIN_ID,
            admin_text,
            reply_markup=markup
        )

        if media_items:
            send_media_to_admin(
                media_items,
                ADMIN_ID
            )

        if appeal:
            safe_send(
                chat_id,
                "📩 Ваша апелляция вместе с анкетой "
                "и вложениями передана администрации.\n\n"
                "Ожидайте ответа владельца.",
                reply_markup=get_main_keyboard()
            )
        else:
            safe_send(
                chat_id,
                "✅ Автоматическая проверка пройдена.\n\n"
                "Ваша анкета вместе с вложениями отправлена "
                "администрации на рассмотрение.",
                reply_markup=get_main_keyboard()
            )

        user_categories.pop(
            chat_id,
            None
        )

        save_state()

    finally:
        lock.release()

# ============================================================
# АДМИНСКИЕ КНОПКИ
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith(
        (
            "accept_",
            "reject_",
            "reply_"
        )
    )
)
def handle_admin_action(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(
            call.id,
            "У вас нет прав администратора."
        )
        return

    parts = call.data.split(
        "_",
        1
    )

    if len(parts) != 2:
        bot.answer_callback_query(
            call.id,
            "Некорректная команда."
        )
        return

    action, target_chat_id = parts

    try:
        target_chat_id = int(
            target_chat_id
        )
    except ValueError:
        bot.answer_callback_query(
            call.id,
            "Некорректный ID."
        )
        return

    if action == "accept":
        safe_send(
            target_chat_id,
            "🎉 Ваша анкета успешно принята "
            "администрацией! Поздравляем!"
        )

        bot.answer_callback_query(
            call.id,
            "Анкета принята."
        )

        try:
            bot.edit_message_reply_markup(
                chat_id=ADMIN_ID,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass

    elif action == "reject":
        safe_send(
            target_chat_id,
            "❌ К сожалению, ваша анкета была "
            "отклонена администрацией.\n\n"
            "Если хотите узнать причину или не согласны "
            "с решением, обратитесь к @CrazyCrabSalad."
        )

        bot.answer_callback_query(
            call.id,
            "Анкета отклонена."
        )

        try:
            bot.edit_message_reply_markup(
                chat_id=ADMIN_ID,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass

    elif action == "reply":
        msg = safe_send(
            ADMIN_ID,
            f"Введите ответ для пользователя "
            f"{target_chat_id}:"
        )

        bot.register_next_step_handler(
            msg,
            send_reply_to_user,
            target_chat_id
        )

        bot.answer_callback_query(
            call.id
        )

# ============================================================
# ОТВЕТ АДМИНА
# ============================================================

def send_reply_to_user(
    message,
    target_chat_id
):
    if message.from_user.id != ADMIN_ID:
        return

    text = message.text or ""

    if not text.strip():
        safe_send(
            ADMIN_ID,
            "Пустое сообщение не отправлено."
        )
        return

    safe_send(
        target_chat_id,
        "💬 Сообщение от администрации:\n\n"
        + text
    )

    safe_send(
        ADMIN_ID,
        "✅ Сообщение успешно доставлено пользователю."
    )

# ============================================================
# НАДЁЖНЫЙ POLLING
# ============================================================

def polling_worker():
    print(
        "[BOT] Поток Telegram polling запущен.",
        flush=True
    )

    while True:
        try:
            print(
                "[BOT] Запускаю Telegram polling...",
                flush=True
            )

            bot.remove_webhook()
            time.sleep(1)

            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=False
            )

            print(
                "[BOT] Polling завершился. "
                "Перезапуск через 5 секунд...",
                flush=True
            )

        except Exception as e:
            print(
                f"[BOT] Polling упал: "
                f"{type(e).__name__}: {e}. "
                "Перезапуск через 5 секунд...",
                flush=True
            )

        time.sleep(5)

# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print(
        "[START] Запуск бота...",
        flush=True
    )

    print(
        f"[START] PID: {os.getpid()}",
        flush=True
    )

    print(
        f"[START] Файл состояния: {PERSISTENCE_FILE}",
        flush=True
    )

    load_state()

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )
    flask_thread.start()

    print(
        "[START] Flask запущен.",
        flush=True
    )

    polling_thread = threading.Thread(
        target=polling_worker,
        daemon=True
    )
    polling_thread.start()

    print(
        "[START] Telegram polling запущен.",
        flush=True
    )

    while True:
        time.sleep(60)
