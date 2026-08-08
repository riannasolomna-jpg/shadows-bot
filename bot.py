import os
import time
import threading
import telebot
from telebot import types
import requests
from flask import Flask

# === ИНИЦИАЛИЗАЦИЯ И НАСТРОЙКИ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ADMIN_ID = 5076963429  # Твой Telegram ID

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

# === ХРАНИЛИЩА ДАННЫХ ===
user_buffers = {}
user_timers = {}
user_roles = {}
admin_reply_state = {}  # Для хранения ID игрока, которому админ пишет ответ

SYSTEM_PROMPT = """
Ты — лояльный и объективный модератор анкет персонажей для текстовой ролевой игры.
Твоя задача — проверить наличие базовых пунктов и отсутствие критических противоречий. НЕ придирайся к художественному стилю, сюжетным ходам или психологическим деталям.

КРИТЕРИИ ОЦЕНКИ:

1. НАЛИЧИЕ И ОБЪЁМ ОСНОВНЫХ ПУНКТОВ:
   - В анкете должны быть: Имя/Кличка, Возраст, Внешность, Характер, История/Причина попадания.
   - Разделы «Характер», «Внешность» и «История» должны быть содержательными (ориентир — не менее 4–5 полноценных предложений или нескольких абзацев на каждый из этих пунктов).
   - Если какой-то из основных пунктов отсутствует или написан слишком скупо (1–2 коротких предложения), укажи на необходимость расширить его.

2. ЛОЯЛЬНОСТЬ К СЮЖЕТУ И ДЕТАЛЯМ (ВАЖНО!):
   - Если Характер, Внешность или История заполнены объёмно, СЧИТАЙ ПУНКТ ПОЛНОСТЬЮ ПРОЙДЕННЫМ.
   - ЗАПРЕЩЕНО требовать расписывать влияние болезней/травм/диагнозов на повседневную жизнь персонажа.
   - ЗАПРЕЩЕНО требовать бытовых или юридических подробностей событий из прошлого (как оформляли документы, как давали взятки и т.д.). Принимай факты автора как данность.
   - ЗАПРЕЩЕНО требовать дополнительных разъяснений к уже описанным чертам характера.

3. ПРОВЕРКА НА ДУБЛИ:
   - Если пункты или куски текста продублированы дважды, попроси удалить повторы.

4. КРИТИЧЕСКИЕ ОШИБКИ:
   - Отмечай только явные физические или временные противоречия (например: «ему 12 лет, но он 15 лет служил в армии»).

ФОРМАТ ОТВЕТА:

Если ключевые пункты заполнены и нет критических противоречий:
Статус: Одобрено.
Замечаний нет.

Если не хватает ключевого пункта, объём слишком мал или есть дубликаты:
Статус: Требует правок.
Пункты с замечаниями:
- [Название пункта]: [В чём заключается конкретная ошибка]
"""

# === КЛАВИАТУРЫ ===
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("📝 Отправить анкету")
    btn2 = types.KeyboardButton("❓ Апелляция / Помощь")
    markup.add(btn1, btn2)
    return markup

def get_role_keyboard():
    markup = types.InlineKeyboardMarkup()
    btn_dom = types.InlineKeyboardButton("🏠 Домовец", callback_data="role_domovets")
    btn_staff = types.InlineKeyboardButton("👔 Персонал / Опекун", callback_data="role_staff")
    markup.row(btn_dom, btn_staff)
    return markup

def get_admin_action_keyboard(user_id):
    markup = types.InlineKeyboardMarkup()
    btn_accept = types.InlineKeyboardButton("✅ Принять", callback_data=f"adm_accept_{user_id}")
    btn_reject = types.InlineKeyboardButton("❌ Отклонить", callback_data=f"adm_reject_{user_id}")
    btn_reply = types.InlineKeyboardButton("💬 Ответить", callback_data=f"adm_reply_{user_id}")
    markup.row(btn_accept, btn_reject)
    markup.row(btn_reply)
    return markup

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def send_smart_message(chat_id, text, reply_markup=None):
    if len(text) <= 4000:
        try:
            bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception:
            bot.send_message(chat_id, text, reply_markup=reply_markup)
    else:
        chunks = [text[i:i+3900] for i in range(0, len(text), 3900)]
        for i, chunk in enumerate(chunks):
            m = reply_markup if i == len(chunks) - 1 else None
            try:
                bot.send_message(chat_id, chunk, parse_mode="Markdown", reply_markup=m)
            except Exception:
                bot.send_message(chat_id, chunk, reply_markup=m)

def analyze_with_ai(text_to_analyze):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text_to_analyze}
        ],
        "temperature": 0.3
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=25)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        return f"Ошибка ИИ (Код {response.status_code})"
    except Exception as e:
        return f" Ошибка соединения с ИИ: {e}"

# === ОБРАБОТКА КОМАНД И КНОПОК ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "*Приветствуем!*\n\n"
        "Для подачи анкеты нажмите кнопку ниже или выберите роль.\n\n"
        "*📌 Как работает проверка:*\n"
        "• Все первичные ошибки выявляет авто-модератор.\n"
        "• Сообщения объединяются в течение *30 секунд*.\n"
        "• После одобрения ботом анкета поступает на личное рассмотрение администрации.\n\n"
        "❓ По вопросам обращайтесь к @CrazyCrabSalad."
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda m: m.text == "📝 Отправить анкету")
def start_application(message):
    bot.send_message(
        message.chat.id, 
        "Выберите, кем является ваш персонаж:", 
        reply_markup=get_role_keyboard()
    )

@bot.message_handler(func=lambda m: m.text == "❓ Апелляция / Помощь")
def show_help(message):
    help_text = (
        "*📌 Инструкция по апелляции и связи:*\n\n"
        "Если вы не согласны с замечаниями бота, отправьте анкету повторно, добавив в начало сообщения:\n"
        "1. Слово: *Апелляция*\n"
        "2. Раздел: *Пояснение:* (ваши аргументы)\n\n"
        "Прямой контакт администрации: @CrazyCrabSalad"
    )
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("role_"))
def handle_role_selection(call):
    role = "Домовец" if call.data == "role_domovets" else "Персонал / Опекун"
    user_roles[call.message.chat.id] = role
    bot.answer_callback_query(call.id, f"Выбрана роль: {role}")
    bot.send_message(
        call.message.chat.id, 
        f"✅ Категория зафиксирована: *{role}*.\n\n"
        "Теперь отправьте текст вашей анкеты сюда в чат (одним или несколькими сообщениями подряд).",
        parse_mode="Markdown"
    )

# === ОБРАБОТКА АДМИН-КНОПОК ===
@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def handle_admin_actions(call):
    if call.from_user.id != ADMIN_ID:
        return

    data = call.data.split("_")
    action = data[1]
    target_user_id = int(data[2])

    if action == "accept":
        bot.send_message(target_user_id, "🎉 *Поздравляем! Ваша анкета официально принята администрацией!* Добро пожаловать!", parse_mode="Markdown")
        bot.answer_callback_query(call.id, "Уведомление о принятии отправлено!")
        bot.edit_message_text(f"{call.message.text}\n\n✅ **ПРИНЯТО АДМИНИСТРАТОРОМ**", call.message.chat.id, call.message.message_id)

    elif action == "reject":
        bot.send_message(target_user_id, "❌ *К сожалению, ваша анкета была отклонена администрацией.* Свяжитесь с @CrazyCrabSalad для уточнения деталей.", parse_mode="Markdown")
        bot.answer_callback_query(call.id, "Уведомление об отказе отправлено!")
        bot.edit_message_text(f"{call.message.text}\n\n❌ **ОТКЛОНЕНО АДМИНИСТРАТОРОМ**", call.message.chat.id, call.message.message_id)

    elif action == "reply":
        admin_reply_state[ADMIN_ID] = target_user_id
        bot.send_message(ADMIN_ID, f"💬 Напишите ответ для игрока (ID: `{target_user_id}`). Следующее ваше сообщение будет отправлено ему напрямую:", parse_mode="Markdown")
        bot.answer_callback_query(call.id)

# === СБОРА И ОБРАБОТКА АНКЕТЫ ===
def process_buffered_application(user_id, message_obj):
    full_text = "\n\n".join(user_buffers.get(user_id, []))
    role = user_roles.get(user_id, "Не указана")
    user_buffers.pop(user_id, None)
    user_timers.pop(user_id, None)

    user_info = f"@{message_obj.from_user.username}" if message_obj.from_user.username else f"ID: {message_obj.from_user.id}"
    lower_text = full_text.lower()

    if "апелляция" in lower_text or "аппеляция" in lower_text:
        if ("апелляция" in lower_text or "аппеляция" in lower_text) and "пояснение" in lower_text:
            bot.send_message(message_obj.chat.id, "Ваша апелляция принята! Анкета отправлена напрямую администратору.")
            ai_report = analyze_with_ai(full_text)
            
            admin_msg = (
                f"📩 *АПЕЛЛЯЦИЯ ОТ ИГРОКА!*\n"
                f"От: {message_obj.from_user.first_name} ({user_info})\n"
                f"Роль: *{role}*\n\n"
                f"📋 *АНАЛИЗ ИИ:*\n{ai_report}\n\n"
                f"📄 *ПОЛНЫЙ ТЕКСТ:* \n{full_text}"
            )
            send_smart_message(ADMIN_ID, admin_msg, reply_markup=get_admin_action_keyboard(user_id))
            return

    report = analyze_with_ai(full_text)

    if "Требует правок" in report:
        user_response = (
            "⚠️ *Ваша анкета содержит замечания и требует правок:*\n\n"
            f"{report}\n\n"
            "📌 Пожалуйста, исправьте указанные недочёты и отправьте антету повторно."
        )
        send_smart_message(message_obj.chat.id, user_response)
    else:
        bot.send_message(message_obj.chat.id, "Ваша анкета успешно прошла первичную проверку и передана администратору! Ожидайте вердикта.")
        
        admin_msg = (
            f"📥 *НОВАЯ ГОТОВАЯ АНКЕТА!*\n"
            f"От: {message_obj.from_user.first_name} ({user_info})\n"
            f"Категория: *{role}*\n\n"
            f"--- *АНАЛИЗ ИИ* ---\n{report}\n\n"
            f"--- *ПОЛНЫЙ ТЕКСТ* ---\n{full_text}"
        )
        send_smart_message(ADMIN_ID, admin_msg, reply_markup=get_admin_action_keyboard(user_id))

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    # Обработка ответа администратора игроку
    if message.from_user.id == ADMIN_ID and ADMIN_ID in admin_reply_state:
        target_id = admin_reply_state.pop(ADMIN_ID)
        try:
            bot.send_message(target_id, f"✉️ *Сообщение от администрации:*\n\n{message.text}", parse_mode="Markdown")
            bot.send_message(ADMIN_ID, "✅ Сообщение успешно доставлено игроку!")
        except Exception as e:
            bot.send_message(ADMIN_ID, f"❌ Не удалось отправить сообщение: {e}")
        return

    # Сбор текста анкеты от пользователя
    user_id = message.from_user.id
    if user_id not in user_buffers:
        user_buffers[user_id] = []

    user_buffers[user_id].append(message.text)

    if user_id in user_timers:
        user_timers[user_id].cancel()

    t = threading.Timer(30.0, process_buffered_application, args=[user_id, message])
    user_timers[user_id] = t
    t.start()

if __name__ == "__main__":
    bot.polling(none_stop=True)
