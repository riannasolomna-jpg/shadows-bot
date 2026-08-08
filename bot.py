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
        "📌 **Пришлите текст вашей анкеты единым сообщением.**\n"
        "⚠️ Анкета должна содержать подробное описание персонажа (не менее 100 символов).",
        chat_id=chat_id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )

# --- АНАЛИЗ АНКЕТЫ ЧЕРЕЗ GROQ ИИ (ГРАММАТИКА + ЛОГИКА) ---
def analyze_anketa_with_ai(text):
    if not client:
        return False, "Ошибка ИИ: Не настроен GROQ_API_KEY"
    
    prompt = f"""
Ты — строгий редактор и модератор текстовой ролевой игры по вселенной «Дом, в котором...».

Твоя задача — детально проверить предложенную анкету на:
1. Орфографические, пунктуационные и грамматические ошибки (каждую найденную ошибку выпиши отдельно по пунктам с указанием верного написания).
2. Логические неувязки и соответствие канону/атмосфере вселенной.

Текст анкеты:
{text}

Ответь СТРОГО в следующем формате:
СТАТУС: [ОДОБРЕНО / ОТКЛОНЕНО]
(Ставь ОТКЛОНЕНО, если в анкете есть грубые орфографические/пунктуационные ошибки или сюжетные нестыковки).

📌 **Орфографические и пунктуационные ошибки:**
• [Ошибка 1] -> [Как правильно]
• [Ошибка 2] -> [Как правильно]
(Если ошибок нет, напиши "Ошибок не обнаружено")

📌 **Логика и канон персонажа:**
• [Краткий разбор логики и сюжета по пунктам]
"""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=1000
        )
        result = response.choices[0].message.content
        is_passed = "СТАТУС: ОДОБРЕНО" in result or "ОДОБРЕНО" in result.split('\n')[0]
        return is_passed, result
    except Exception as e:
        return False, f"Ошибка ИИ (Код ошибки: {e})"

# --- ПРИЕМ И ВАЛИДАЦИЯ АНКЕТЫ ---
@bot.message_handler(func=lambda msg: user_states.get(msg.chat.id, {}).get('step') == 'waiting_anketa')
def receive_anketa(message):
    chat_id = message.chat.id
    text = message.text or ""

    # Проверка длины
    if len(text.strip()) < 100:
        bot.send_message(
            chat_id,
            "❌ **Анкета слишком короткая!**\n\n"
            "Пожалуйста, распишите анкету подробнее (не менее 100 символов).",
            parse_mode="Markdown"
        )
        return

    category = user_states[chat_id].get('category', 'Не указана')
    user_states[chat_id]['step'] = 'completed'

    bot.send_message(
        chat_id,
        "⏳ Ваша анкета проверяется авто-модератором на грамотность и логику...",
        reply_markup=get_main_keyboard()
    )

    # Проверка через ИИ
    is_passed, ai_analysis = analyze_anketa_with_ai(text)

    # Если ИИ отклонил или ключ упал
    if not is_passed and "Ошибка ИИ" not in ai_analysis:
        bot.send_message(
            chat_id,
            f"❌ **Ваша анкета не прошла первичную проверку!**\n\n"
            f"{ai_analysis}\n\n"
            f"Пожалуйста, исправьте указанные ошибки и отправьте анкету заново через меню.",
            parse_mode="Markdown"
        )
        return

    # Отправка администратору
    username = f"@{message.from_user.username}" if message.from_user.username else "Отсутствует"
    user_fullname = message.from_user.full_name

    admin_caption = (
        f"📥 **НОВАЯ ГОТОВАЯ АНКЕТА!**\n"
        f"От: {user_fullname} ({username})\n"
        f"Категория: *{category}*\n\n"
        f"--- **АНАЛИЗ ИИ (ОШИБКИ И ЛОГИКА)** ---\n"
        f"{ai_analysis}\n\n"
        f"--- **ПОЛНЫЙ ТЕКСТ** ---\n"
        f"{text}"
    )

    admin_markup = types.InlineKeyboardMarkup(row_width=2)
    admin_markup.add(
        types.InlineKeyboardButton("✅ Принять", callback_data=f"accept_{chat_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{chat_id}")
    )
    admin_markup.add(
        types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{chat_id}")
    )

    if len(admin_caption) > 4000:
        bot.send_message(ADMIN_ID, admin_caption[:4000], parse_mode="Markdown")
        bot.send_message(ADMIN_ID, admin_caption[4000:], parse_mode="Markdown", reply_markup=admin_markup)
    else:
        bot.send_message(ADMIN_ID, admin_caption, parse_mode="Markdown", reply_markup=admin_markup)

# --- РЕАКЦИЯ АДМИНА ---
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
    
