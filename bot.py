import os
import time
from threading import Thread
from flask import Flask
import telebot
from telebot import types
import groq

# --- ИНИЦИАЛИЗАЦИЯ И НАСТРОЙКИ ---
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
ADMIN_ID = 5076963429  # Твой Telegram ID

bot = telebot.TeleBot(BOT_TOKEN)
client = groq.Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Временное хранилище анкет пользователей
user_states = {}

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (HEALTH CHECK) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- КНОПКИ ГЛАВНОГО МЕНЮ ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_anketa = types.KeyboardButton("📝 Отправить анкету")
    btn_help = types.KeyboardButton("❓ Апелляция / Помощь")
    markup.add(btn_anketa, btn_help)
    return markup

def get_categories_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Домовец", callback_data="cat_домовец"),
        types.InlineKeyboardButton("Наружник", callback_data="cat_наружник"),
        types.InlineKeyboardButton("Воспитатель", callback_data="cat_воспитатель"),
        types.InlineKeyboardButton("Другое", callback_data="cat_другое")
    )
    return markup

# --- ОБРАБОТКА КОМАНДЫ /START ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    user_states[chat_id] = {'step': 'main'}
    welcome_text = (
        "Приветствуем в сообществе **Тени Судьбы**! 🏛️\n\n"
        "Воспользуйтесь кнопками ниже, чтобы подать анкету персонажа "
        "или связаться с администрацией."
    )
    bot.send_message(chat_id, welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

# --- ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ МЕНЮ ---
@bot.message_handler(func=lambda msg: msg.text in ["📝 Отправить анкету", "❓ Апелляция / Помощь"])
def handle_menu_click(message):
    chat_id = message.chat.id
    if message.text == "📝 Отправить анкету":
        user_states[chat_id] = {'step': 'choose_category'}
        bot.send_message(
            chat_id, 
            "Выберите категорию вашего персонажа:", 
            reply_markup=get_categories_keyboard()
        )
    elif message.text == "❓ Апелляция / Помощь":
        bot.send_message(
            chat_id, 
            "По вопросам апелляций и помощи обращайтесь к администратору: @CrazyCrabSalad"
        )

# --- ОБРАБОТКА ВЫБОРА КАТЕГОРИИ ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("cat_"))
def handle_category_choice(call):
    chat_id = call.message.chat.id
    category = call.data.replace("cat_", "").capitalize()
    
    user_states[chat_id] = {
        'step': 'waiting_anketa',
        'category': category
    }
    
    bot.edit_message_text(
        f"Выбрана категория: **{category}**.\n\n"
        "📌 **Пришлите текст вашей анкеты одним или несколькими сообщениями.**\n"
        "⚠️ Анкета должна содержать подробное описание (не менее 100 символов).",
        chat_id=chat_id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )

# --- АНАЛИЗ АНКЕТЫ ЧЕРЕЗ GROQ ИИ ---
def analyze_anketa_with_ai(text):
    if not client:
        return "Ошибка ИИ (Не настроен GROQ_API_KEY)"
    
    prompt = f"""
Ты — строгий модератор текстовой ролевой игры по вселенной «Дом, в котором...».
Проанализируй следующую анкету персонажа на предмет ошибок, логических неувязок и соответствия атмосфере.

Текст анкеты:
{text}

Выдай краткий разбор (3-5 пунктов) с указанием сильных сторон и замечаний/ошибок, если они есть.
"""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=600
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка ИИ (Код ошибки: {e})"

# --- ПРИЕМ И ВАЛИДАЦИЯ АНКЕТЫ ---
@bot.message_handler(func=lambda msg: user_states.get(msg.chat.id, {}).get('step') == 'waiting_anketa')
def receive_anketa(message):
    chat_id = message.chat.id
    text = message.text or ""

    # Проверка на минимальную длину (фильтр от "...", "Fjjf" и случайных нажатий)
    if len(text.strip()) < 100:
        bot.send_message(
            chat_id,
            "❌ **Анкета слишком короткая!**\n\n"
            "Пожалуйста, распишите анкету подробнее (кличка, пол, внешность, характер, история) "
            "и пришлите её снова.",
            parse_mode="Markdown"
        )
        return

    category = user_states[chat_id].get('category', 'Не указана')
    user_states[chat_id]['step'] = 'completed'

    bot.send_message(
        chat_id,
        "⏳ Ваша анкета принята и отправлена на проверку авто-модератору и администрации...",
        reply_markup=get_main_keyboard()
    )

    # Проверка через ИИ
    ai_analysis = analyze_anketa_with_ai(text)

    # Формирование карточки для админа
    username = f"@{message.from_user.username}" if message.from_user.username else "Отсутствует"
    user_fullname = message.from_user.full_name

    admin_caption = (
        f"📥 **НОВАЯ ГОТОВАЯ АНКЕТА!**\n"
        f"От: {user_fullname} ({username})\n"
        f"Категория: *{category}*\n\n"
        f"--- **АНАЛИЗ ИИ** ---\n"
        f"{ai_analysis}\n\n"
        f"--- **ПОЛНЫЙ ТЕКСТ** ---\n"
        f"{text}"
    )

    # Клавиатура решений для админа
    admin_markup = types.InlineKeyboardMarkup(row_width=2)
    admin_markup.add(
        types.InlineKeyboardButton("✅ Принять", callback_data=f"accept_{chat_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{chat_id}")
    )
    admin_markup.add(
        types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{chat_id}")
    )

    # Отправка админу
    if len(admin_caption) > 4000:
        bot.send_message(ADMIN_ID, admin_caption[:4000], parse_mode="Markdown")
        bot.send_message(ADMIN_ID, admin_caption[4000:], parse_mode="Markdown", reply_markup=admin_markup)
    else:
        bot.send_message(ADMIN_ID, admin_caption, parse_mode="Markdown", reply_markup=admin_markup)

# --- РЕАКЦИЯ АДМИНА (КНОПКИ В АДМИНКЕ) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith(("accept_", "reject_", "reply_")))
def handle_admin_action(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "У вас нет прав администратора.")
        return

    action, target_chat_id = call.data.split("_")
    target_chat_id = int(target_chat_id)

    if action == "accept":
        bot.send_message(target_chat_id, "🎉 **Ваша анкета успешно принята администрацией!** Поздравляем!", parse_mode="Markdown")
        bot.edit_message_text(call.message.text + "\n\n✅ **ПРИНЯТО АДМИНИСТРАТОРОМ**", chat_id=ADMIN_ID, message_id=call.message.message_id)
    elif action == "reject":
        bot.send_message(target_chat_id, "❌ **К сожалению, ваша анкета была отклонена.** Свяжитесь с @CrazyCrabSalad для уточнения деталей.", parse_mode="Markdown")
        bot.edit_message_text(call.message.text + "\n\n❌ **ОТКЛОНЕНО АДМИНИСТРАТОРОМ**", chat_id=ADMIN_ID, message_id=call.message.message_id)
    elif action == "reply":
        msg = bot.send_message(ADMIN_ID, f"Введите ответ для пользователя `{target_chat_id}`:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, send_reply_to_user, target_chat_id)

def send_reply_to_user(message, target_chat_id):
    bot.send_message(target_chat_id, f"💬 **Сообщение от администрации:**\n\n{message.text}", parse_mode="Markdown")
    bot.send_message(ADMIN_ID, "Сообщение успешно доставлено пользователю!")

# --- ЗАПУСК ВЕБ-СЕРВЕРА И БОТА ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    bot.infinity_polling(skip_pending_updates=True)
    
