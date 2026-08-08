import os
import time
import threading
import requests
import telebot
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8644839960:AAGuezNejW02oqd6omY4GLzmYV7j56INarw")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
ADMIN_ID = 5076963429

# Простой веб-сервер, чтобы Render Free Web Service не закрывал процесс
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

bot = telebot.TeleBot(BOT_TOKEN)

WELCOME_TEXT = "Ваша анкета и материалы приняты на проверку! Ожидайте решения."

user_buffers = {}
user_timers = {}

SYSTEM_PROMPT = """
Ты — помощник модератора текстовой ролевой игры по фандому «Дом, в котором».

ТВОЯ ЗАДАЧА: Проверить анкету персонажа и сформировать точечный список замечаний для игрока.

1. ПРОВЕРКА НАЛИЧИЯ ОБЯЗАТЕЛЬНЫХ ПУНКТОВ И ЛОРА:
Если любой из обязательных пунктов отсутствует — это СТРОГАЯ ОШИБКА. Напрямик напиши, какого именно пункта нет.

• Обязательные пункты для «Домовца»:
1. Кличка
2. Стая (Жрецы, Искры, Гавена, Утопленники, Кометы, Орфы + опционально Мистерийцы)
3. Пол
4. Возраст (14-18 лет)
5. Заболевание (СТРОГО ОБЯЗАТЕЛЬНЫЙ ПУНКТ! Оценивай логически по лору Дома:
   - В пункте должно быть физическое заболевание/инвалидность ИЛИ...
   - В биографии/предыстории должно быть логическое объяснение (например: за ребенка доплатили, дали взятку, перевели по блату, связи и т.д.).
   - Если есть хотя бы одно из двух (физ. болезнь ИЛИ объяснение с доплатой/связями в био) — ПУНКТ СЧИТАЕТСЯ ПРОЙДЕННЫМ. Расписывать симптомы к каждой болезни НЕ требуется)
6. Внешность
7. Характер (мин. 200 символов)
8. Причина попадания
9. Возраст попадания
10. Умения (описывать полную механику НЕ требуется)
11. Юз

• Обязательные пункты для «Персонала»:
1. Кличка
2. Пол
3. Возраст (20+ лет)
4. Внешность
5. Характер (мин. 200 символов)
6. Предыстория (мин. 50-70 символов)
7. Должность
8. Юз

2. ПРОВЕРКА ОБЪЁМА И ЛОГИКИ:
- Если в пункте мало текста (например, в Характере или Предыстории), укажи текущий объём и точный минимум, который должен быть.
- Указывай ТОЛЬКО на слишком грубые логические ошибки и критические несоответствия лору стаи.

3. ОРФОГРАФИЯ:
Укажи явные опечатки и ошибки, если они есть.

ФОРМАТ ТВОЕГО ОТВЕТА (Строго придерживайся структуры):

СТАТУС: [Принять / Требует правок]

ЗАМЕЧАНИЯ ДЛЯ ИГРОКА:
(Если СТАТУС = Требует правок, составь ЕДИНЫЙ СТРОГИЙ НУМЕРОВАННЫЙ СПИСОК (1, 2, 3...). Если ВСЁ ХОРОШО — напиши "Нет")
1. ...
2. ...

ОТЧЕТ ДЛЯ АДМИНА:
[Краткое резюме для владельца в 2-3 предложения]
"""

def send_smart_message(chat_id, text):
    """Безопасная отправка длинных сообщений"""
    if len(text) <= 4000:
        try:
            bot.send_message(chat_id, text, parse_mode="Markdown")
        except:
            bot.send_message(chat_id, text)
    else:
        for chunk in [text[i:i+3900] for i in range(0, len(text), 3900)]:
            bot.send_message(chat_id, chunk)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, WELCOME_TEXT)

def process_buffered_application(user_id, message_obj):
    """Функция обработки анкеты после истечения 30 секунд"""
    full_text = "\n\n".join(user_buffers.get(user_id, []))
    user_buffers.pop(user_id, None)
    user_timers.pop(user_id, None)

    user_info = f"@{message_obj.from_user.username}" if message_obj.from_user.username else f"ID: {message_obj.from_user.id}"
    lower_text = full_text.lower()

    # === БЛОК ПРОВЕРКИ АПЕЛЛЯЦИИ ===
    if "апелляция" in lower_text or "аппеляция" in lower_text:
        has_appeal = "апелляция" in lower_text or "аппеляция" in lower_text
        has_explanation = "пояснение" in lower_text

        if has_appeal and has_explanation:
            bot.send_message(message_obj.chat.id, "Ваша апелляция принята! Анкета отправлена напрямую администратору на личное рассмотрение.")
            
            admin_msg_1 = (
                f"📩 **АПЕЛЛЯЦИЯ ОТ ИГРОКА!**\n"
                f"От: {message_obj.from_user.first_name} ({user_info})\n"
                f"Игрок подал апелляцию и не согласен с решением авто-системы."
            )
            send_smart_message(ADMIN_ID, admin_msg_1)

            ai_report = analyze_with_ai(full_text)

            admin_msg_2 = f"📋 **СПОСОБНЫЕ ОШИБКИ ПО МНЕНИЮ ИИ:**\n\n{ai_report}"
            send_smart_message(ADMIN_ID, admin_msg_2)

            admin_msg_3 = f"📝 **ТЕКСТ АПЕЛЛЯЦИИ И АНКЕТЫ:**\n\n{full_text}"
            send_smart_message(ADMIN_ID, admin_msg_3)
            return
        else:
            bot.send_message(
                message_obj.chat.id, 
                "⚠️ **Ошибка при подаче апелляции!**\n\n"
                "Для подачи апелляции в сообщении должны присутствовать ДВА ключевых слова:\n"
                "1. **Апелляция**\n"
                "2. **Пояснение:** (подробно распишите, почему вы не согласны с ботом).\n\n"
                "Пожалуйста, отправьте анкету повторно с выполнением этих условий."
            )
            return
    # ===============================

    report = analyze_with_ai(full_text)

    if "Требует правок" in report:
        appeal_instruction = (
            "\n\n---\n"
            "📌 **Не согласны с ошибками бота?**\n"
            "Вы можете подать апелляцию напрямую владельцу. Для этого отправьте повторно анкету в чат, обязательно указав в тексте:\n"
            "• Слово: **Апелляция**\n"
            "• Раздел: **Пояснение:** (где вы аргументируете свою позицию)."
        )
        
        user_response = (
            "⚠️ **Ваша анкета содержит замечания и требует правок:**\n\n"
            f"{report}\n\n"
            "📌 **Пожалуйста, исправьте указанные недочёты и отправьте исправленный вариант сюда в чат.**\n"
            "💡 *Примечание: Если ваша анкета разделена на несколько частей, отправляйте их подряд в течение 30 секунд — бот объединит их в одно сообщение.*"
            f"{appeal_instruction}\n\n"
            "*(P.s. если есть какие-то противоречия с замечаниями, напишите пожалуйста админам или прям в бота, чтобы владелец принял во внимание).*"
        )
        send_smart_message(message_obj.chat.id, user_response)
    else:
        bot.send_message(message_obj.chat.id, "Ваша анкета и материалы приняты на проверку! Ожидайте решения.")
        
        admin_header = (
            f"📥 **Новая готовая анкета на проверку!**\n"
            f"От: {message_obj.from_user.first_name} ({user_info})\n\n"
            f"--- **АНАЛИЗ ИИ** ---\n\n"
        )
        send_smart_message(ADMIN_ID, admin_header + report)
        bot.forward_message(ADMIN_ID, message_obj.chat.id, message_obj.message_id)

def analyze_with_ai(text):
    """Запрос к API Groq"""
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Вот анкета для проверки:\n\n{text}"}
            ]
        }
        res = requests.post(url, json=payload, headers=headers)
        res_data = res.json()
        if "choices" in res_data:
            return res_data['choices'][0]['message']['content']
        return f"Ошибка сервиса: {res_data}"
    except Exception as e:
        return f"Ошибка при вызове ИИ: {e}"

@bot.message_handler(content_types=['text', 'photo', 'audio', 'document'])
def handle_application(message):
    if message.from_user.id == ADMIN_ID:
        bot.reply_to(message, "Вы администратор. Сюда будут приходить анкеты от игроков.")
        return

    user_id = message.from_user.id
    text_content = message.text or message.caption or ""

    if not text_content and (message.photo or message.audio or message.document):
        bot.reply_to(message, "Файл получен! Не забудь отправить сам текст анкеты.")
        bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
        return

    if user_id not in user_buffers:
        user_buffers[user_id] = []
    
    user_buffers[user_id].append(text_content)

    if user_id in user_timers:
        user_timers[user_id].cancel()

    t = threading.Timer(30.0, process_buffered_application, args=[user_id, message])
    user_timers[user_id] = t
    t.start()

print("Бот запущен!")
bot.infinity_polling()
   
