import os
from threading import Thread

from flask import Flask
import telebot
from telebot import types
from groq import Groq


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Telegram ID администратора
ADMIN_ID = 5076963429


# =========================================================
# ПРОВЕРКА НАСТРОЕК
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN в переменных окружения.")

if not GROQ_API_KEY:
    print("⚠️ GROQ_API_KEY не найден. Проверка через ИИ работать не будет.")


# =========================================================
# ИНИЦИАЛИЗАЦИЯ
# =========================================================

bot = telebot.TeleBot(BOT_TOKEN)

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

user_states = {}


# =========================================================
# WEB-СЕРВЕР ДЛЯ RENDER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive!", 200


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port
    )


# =========================================================
# ГЛАВНОЕ МЕНЮ
# =========================================================

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    btn_anketa = types.KeyboardButton(
        "📝 Отправить анкету"
    )

    btn_help = types.KeyboardButton(
        "❓ Апелляция / Помощь"
    )

    markup.add(
        btn_anketa,
        btn_help
    )

    return markup


# =========================================================
# КАТЕГОРИИ
# =========================================================

def get_categories_keyboard():
    markup = types.InlineKeyboardMarkup(
        row_width=2
    )

    markup.add(
        types.InlineKeyboardButton(
            "Домовец",
            callback_data="cat_домовец"
        ),

        types.InlineKeyboardButton(
            "Наружник",
            callback_data="cat_наружник"
        ),

        types.InlineKeyboardButton(
            "Воспитатель",
            callback_data="cat_воспитатель"
        ),

        types.InlineKeyboardButton(
            "Другое",
            callback_data="cat_другое"
        )
    )

    return markup


# =========================================================
# /START
# =========================================================

@bot.message_handler(commands=["start"])
def send_welcome(message):

    chat_id = message.chat.id

    user_states[chat_id] = {
        "step": "main"
    }

    welcome_text = (
        "Приветствуем в сообществе «Тени Судьбы»! 🏛️\n\n"
        "Воспользуйтесь кнопками ниже, чтобы подать "
        "анкету персонажа или связаться с администрацией."
    )

    bot.send_message(
        chat_id,
        welcome_text,
        reply_markup=get_main_keyboard()
    )


# =========================================================
# КНОПКИ ГЛАВНОГО МЕНЮ
# =========================================================

@bot.message_handler(
    func=lambda msg: msg.text in [
        "📝 Отправить анкету",
        "❓ Апелляция / Помощь"
    ]
)
def handle_menu_click(message):

    chat_id = message.chat.id

    # -----------------------------------------
    # АНКЕТА
    # -----------------------------------------

    if message.text == "📝 Отправить анкету":

        user_states[chat_id] = {
            "step": "choose_category"
        }

        bot.send_message(
            chat_id,
            "Выберите категорию вашего персонажа:",
            reply_markup=get_categories_keyboard()
        )

    # -----------------------------------------
    # ПОМОЩЬ
    # -----------------------------------------

    elif message.text == "❓ Апелляция / Помощь":

        bot.send_message(
            chat_id,
            "По вопросам апелляций и помощи "
            "обращайтесь к администратору: @CrazyCrabSalad"
        )


# =========================================================
# ВЫБОР КАТЕГОРИИ
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("cat_")
)
def handle_category_choice(call):

    chat_id = call.message.chat.id

    category = call.data.replace(
        "cat_",
        ""
    ).capitalize()

    user_states[chat_id] = {
        "step": "waiting_anketa",
        "category": category
    }

    bot.answer_callback_query(
        call.id
    )

    text = (
        f"Выбрана категория: {category}.\n\n"
        "📌 Пришлите текст вашей анкеты одним сообщением.\n\n"
        "⚠️ Анкета должна содержать подробное "
        "описание персонажа (не менее 100 символов)."
    )

    bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=call.message.message_id
    )


# =========================================================
# ПРОВЕРКА АНКЕТЫ ЧЕРЕЗ GROQ
# =========================================================

def analyze_anketa_with_ai(text):

    if not client:

        return (
            False,
            "Ошибка ИИ: не настроен GROQ_API_KEY."
        )

    prompt = f"""
Ты — модератор и редактор текстовой ролевой игры
по вселенной «Дом, в котором...».

Внимательно прочитай анкету пользователя:

---------------- АНКЕТА ----------------

{text}

-------------- КОНЕЦ АНКЕТЫ ------------


Твоя задача:

1. Найти абсолютно все орфографические ошибки.
2. Найти пунктуационные ошибки.
3. Найти грамматические ошибки.
4. Найти опечатки.
5. Проверить логические противоречия.
6. Проверить очевидные нестыковки в биографии персонажа.
7. Проверить, нет ли взаимоисключающих утверждений.

ВАЖНО:

Если есть ХОТЯ БЫ ОДНА орфографическая,
пунктуационная, грамматическая ошибка,
опечатка или очевидная логическая нестыковка,
статус должен быть ОТКЛОНЕНО.

Если ошибок нет — ОДОБРЕНО.

Не придумывай ошибки там, где их нет.


ОТВЕТ ОБЯЗАТЕЛЬНО ДОЛЖЕН ИМЕТЬ ТАКУЮ СТРУКТУРУ:

СТАТУС: ОДОБРЕНО
или
СТАТУС: ОТКЛОНЕНО

📌 Найденные ошибки и опечатки:
• Если ошибок нет — напиши «Ошибок не найдено».
• Если ошибки есть — каждую ошибку укажи отдельно
  и обязательно напиши правильный вариант.

📌 Разбор логики и канона:
• Кратко укажи 2–3 важных момента.
"""

    try:

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            temperature=0.2,
            max_tokens=1200
        )

        result = response.choices[0].message.content

        if not result:
            return (
                False,
                "Ошибка ИИ: модель не вернула ответ."
            )

        result_upper = result.upper()

        # -----------------------------------------
        # НАДЁЖНАЯ ПРОВЕРКА СТАТУСА
        # -----------------------------------------

        if "СТАТУС: ОДОБРЕНО" in result_upper:

            is_passed = True

        elif "СТАТУС: ОТКЛОНЕНО" in result_upper:

            is_passed = False

        else:

            return (
                False,
                "Ошибка ИИ: модель не указала корректный статус."
            )

        return (
            is_passed,
            result
        )

    except Exception as e:

        print(
            f"Ошибка Groq: {repr(e)}"
        )

        return (
            False,
            f"Ошибка ИИ: {e}"
        )


# =========================================================
# ПРИЁМ АНКЕТЫ
# =========================================================

@bot.message_handler(
    func=lambda msg:
        user_states.get(
            msg.chat.id,
            {}
        ).get("step") == "waiting_anketa"
)
def receive_anketa(message):

    chat_id = message.chat.id

    text = message.text or ""

    # -----------------------------------------
    # ПРОВЕРКА ДЛИНЫ
    # -----------------------------------------

    if len(text.strip()) < 100:

        bot.send_message(
            chat_id,
            "❌ Анкета слишком короткая!\n\n"
            "Пожалуйста, распишите анкету подробнее "
            "(не менее 100 символов)."
        )

        return

    # -----------------------------------------
    # ПОЛУЧАЕМ КАТЕГОРИЮ
    # -----------------------------------------

    category = user_states.get(
        chat_id,
        {}
    ).get(
        "category",
        "Не указана"
    )

    # -----------------------------------------
    # СООБЩЕНИЕ О ПРОВЕРКЕ
    # -----------------------------------------

    bot.send_message(
        chat_id,
        "⏳ Ваша анкета проверяется "
        "авто-модератором на грамотность и логику...",
        reply_markup=get_main_keyboard()
    )

    # -----------------------------------------
    # ПРОВЕРКА ИИ
    # -----------------------------------------

    is_passed, ai_analysis = analyze_anketa_with_ai(
        text
    )

    # -----------------------------------------
    # ЕСЛИ GROQ НЕ РАБОТАЕТ
    # -----------------------------------------

    if ai_analysis.startswith("Ошибка ИИ:"):

        user_states[chat_id]["step"] = "waiting_anketa"

        bot.send_message(
            chat_id,
            "⚠️ Не удалось проверить анкету "
            "через ИИ.\n\n"
            "Попробуйте отправить её немного позже."
        )

        print(
            f"Groq error for {chat_id}: "
            f"{ai_analysis}"
        )

        return

    # -----------------------------------------
    # ЕСЛИ АНКЕТА НЕ ПРОШЛА
    # -----------------------------------------

    if not is_passed:

        user_states[chat_id]["step"] = "main"

        rejection_text = (
            "❌ Ваша анкета не прошла "
            "первичную проверку!\n\n"
            f"{ai_analysis}\n\n"
            "Пожалуйста, исправьте ошибки "
            "и отправьте анкету заново через меню."
        )

        bot.send_message(
            chat_id,
            rejection_text
        )

        return

    # -----------------------------------------
    # ЕСЛИ АНКЕТА ПРОШЛА
    # -----------------------------------------

    user_states[chat_id]["step"] = "completed"

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "Отсутствует"
    )

    user_fullname = message.from_user.full_name

    # -----------------------------------------
    # ФОРМИРУЕМ АНКЕТУ ДЛЯ АДМИНА
    # -----------------------------------------

    admin_caption = (
        "📥 НОВАЯ ГОТОВАЯ АНКЕТА!\n\n"
        f"От: {user_fullname}\n"
        f"Username: {username}\n"
        f"ID: {chat_id}\n"
        f"Категория: {category}\n\n"
        "---------- АНАЛИЗ ИИ ----------\n\n"
        f"{ai_analysis}\n\n"
        "---------- ПОЛНЫЙ ТЕКСТ ----------\n\n"
        f"{text}"
    )

    # -----------------------------------------
    # КНОПКИ АДМИНИСТРАТОРА
    # -----------------------------------------

    admin_markup = types.InlineKeyboardMarkup(
        row_width=2
    )

    admin_markup.add(
        types.InlineKeyboardButton(
            "✅ Принять",
            callback_data=f"accept_{chat_id}"
        ),

        types.InlineKeyboardButton(
            "❌ Отклонить",
            callback_data=f"reject_{chat_id}"
        )
    )

    admin_markup.add(
        types.InlineKeyboardButton(
            "💬 Ответить",
            callback_data=f"reply_{chat_id}"
        )
    )

    # -----------------------------------------
    # ОГРАНИЧЕНИЕ TELEGRAM 4096 СИМВОЛОВ
    # -----------------------------------------

    if len(admin_caption) <= 4000:

        bot.send_message(
            ADMIN_ID,
            admin_caption,
            reply_markup=admin_markup
        )

    else:

        # Первое сообщение
        first_part = admin_caption[:4000]

        # Остальная часть
        second_part = admin_caption[4000:]

        bot.send_message(
            ADMIN_ID,
            first_part
        )

        bot.send_message(
            ADMIN_ID,
            second_part,
            reply_markup=admin_markup
        )


# =========================================================
# ДЕЙСТВИЯ АДМИНИСТРАТОРА
# =========================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith(
            (
                "accept_",
                "reject_",
                "reply_"
            )
        )
)
def handle_admin_action(call):

    # -----------------------------------------
    # ПРОВЕРКА ПРАВ
    # -----------------------------------------

    if call.from_user.id != ADMIN_ID:

        bot.answer_callback_query(
            call.id,
            "У вас нет прав администратора."
        )

        return

    # -----------------------------------------
    # РАЗБИРАЕМ CALLBACK
    # -----------------------------------------

    parts = call.data.split("_", 1)

    action = parts[0]
    target_chat_id = int(parts[1])

    bot.answer_callback_query(
        call.id
    )

    # -----------------------------------------
    # ПРИНЯТЬ
    # -----------------------------------------

    if action == "accept":

        bot.send_message(
            target_chat_id,
            "🎉 Ваша анкета успешно принята "
            "администрацией!\n\n"
            "Поздравляем!"
        )

        try:

            bot.edit_message_text(
                call.message.text
                + "\n\n"
                "✅ ПРИНЯТО АДМИНИСТРАТОРОМ",

                chat_id=ADMIN_ID,
                message_id=call.message.message_id
            )

        except Exception as e:

            print(
                f"Не удалось изменить сообщение: {e}"
            )

    # -----------------------------------------
    # ОТКЛОНИТЬ
    # -----------------------------------------

    elif action == "reject":

        bot.send_message(
            target_chat_id,
            "❌ К сожалению, ваша анкета "
            "была отклонена.\n\n"
            "Свяжитесь с @CrazyCrabSalad "
            "для уточнения деталей."
        )

        try:

            bot.edit_message_text(
                call.message.text
                + "\n\n"
                "❌ ОТКЛОНЕНО АДМИНИСТРАТОРОМ",

                chat_id=ADMIN_ID,
                message_id=call.message.message_id
            )

        except Exception as e:

            print(
                f"Не удалось изменить сообщение: {e}"
            )

    # -----------------------------------------
    # ОТВЕТИТЬ
    # -----------------------------------------

    elif action == "reply":

        msg = bot.send_message(
            ADMIN_ID,
            f"Введите ответ для пользователя "
            f"{target_chat_id}:"
        )

        bot.register_next_step_handler(
            msg,
            send_reply_to_user,
            target_chat_id
        )


# =========================================================
# ОТПРАВКА ОТВЕТА ПОЛЬЗОВАТЕЛЮ
# =========================================================

def send_reply_to_user(
    message,
    target_chat_id
):

    if not message.text:

        bot.send_message(
            ADMIN_ID,
            "❌ Ответ должен быть текстовым сообщением."
        )

        return

    try:

        bot.send_message(
            target_chat_id,
            "💬 Сообщение от администрации:\n\n"
            f"{message.text}"
        )

        bot.send_message(
            ADMIN_ID,
            "✅ Сообщение успешно доставлено пользователю!"
        )

    except Exception as e:

        bot.send_message(
            ADMIN_ID,
            "❌ Не удалось отправить сообщение пользователю.\n\n"
            f"Ошибка: {e}"
        )


# =========================================================
# ЗАПУСК
# =========================================================

if __name__ == "__main__":

    print("🚀 Запуск Flask-сервера...")

    Thread(
        target=run_flask,
        daemon=True
    ).start()

    print("🤖 Telegram-бот запущен!")

    bot.infinity_polling(
        skip_pending=True
        )
