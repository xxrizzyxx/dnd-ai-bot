import os
import json
import re
import requests
import random
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
PROXY_URL = os.getenv("PROXY_URL")

CHARACTER_FILE = "characters.json"
WORLD_FILE = "world_state.json"

# ---------- РАСЫ И КЛАССЫ ----------
RACES = {
    "Человек": ["Стандартный", "Вариант"],
    "Эльф": ["Высший эльф", "Лесной эльф", "Тёмный эльф"],
    "Дварф": ["Горный дварф", "Холмовый дварф"],
    "Полуэльф": ["Стандартный"],
    "Полуорк": ["Стандартный"],
    "Гном": ["Лесной гном", "Скальный гном"],
    "Тифлинг": ["Стандартный"],
    "Драконорожденный": ["Чёрный", "Синий", "Зелёный", "Красный", "Белый"],
    "Орк": ["Стандартный"],
    "Полурослик": ["Легконогий", "Пухленький"]
}
CLASSES = {
    "Воин": ["Чемпион", "Рыцарь"],
    "Маг": ["Школа волшебства", "Школа иллюзий"],
    "Плут": ["Вор", "Убийца"],
    "Жрец": ["Домен жизни", "Домен войны"],
    "Следопыт": ["Охотник", "Зверолов"],
    "Варвар": ["Ярость", "Берсерк"],
    "Паладин": ["Клятва", "Защитник"],
    "Друид": ["Круг земли", "Круг луны"],
    "Бард": ["Коллегия знаний", "Коллегия доблести"],
    "Чародей": ["Драконья кровь", "Дикая магия"]
}
VALID_RACES = list(RACES.keys())
VALID_CLASSES = list(CLASSES.keys())

# ---------- ЗАГРУЗКА/СОХРАНЕНИЕ ----------
def load_json(file):
    if os.path.exists(file):
        with open(file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_json(file, data):
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

user_characters = load_json(CHARACTER_FILE)
world_state = load_json(WORLD_FILE)
creation_steps = {}

def get_active_char(user_id):
    chars = user_characters.get(user_id, {})
    active_name = chars.get("active")
    if active_name and active_name in chars.get("chars", {}):
        return active_name, chars["chars"][active_name]
    return None, None

def add_character(user_id, char_data, set_active=True):
    if user_id not in user_characters:
        user_characters[user_id] = {"chars": {}, "active": None}
    char_name = char_data["name"]
    if char_name in user_characters[user_id]["chars"]:
        i = 2
        while f"{char_name} {i}" in user_characters[user_id]["chars"]:
            i += 1
        char_data["name"] = f"{char_name} {i}"
    user_characters[user_id]["chars"][char_data["name"]] = char_data
    if set_active:
        user_characters[user_id]["active"] = char_data["name"]
    save_json(CHARACTER_FILE, user_characters)

def init_world(user_id):
    if user_id not in world_state:
        world_state[user_id] = {
            "location": "деревня",
            "quests": {"актив": "Поговори со старейшиной в деревне.", "выполн": []},
            "flags": {"знает_старейшину": False, "амулет_найден": False, "сундук_открыт": False},
            "npcs": {"старейшина": {"диалог": "Приветствую! В лесу появился злой дух. Принеси мне его амулет."}},
            "inventory_world": [],
            "story_log": []
        }
        save_json(WORLD_FILE, world_state)
    return world_state[user_id]

# ---------- ЗАПРОС К DEEPSEEK (ИСПРАВЛЕННЫЙ) ----------
def ask_deepseek(user_input, roll, char_data, world):
    if not DEEPSEEK_API_KEY:
        return "⚠️ Нет API-ключа DeepSeek. Добавь DEEPSEEK_API_KEY в .env"
    
    location = world.get("location", "неизвестно")
    quest = world.get("quests", {}).get("актив", "нет")
    flags = world.get("flags", {})
    name = char_data.get("name", "Герой")
    char_class = char_data.get("class", "воин")
    level = char_data.get("level", 1)
    stats = char_data.get("stats", {})
    stat_str = ", ".join([f"{k.upper()}: {v}" for k, v in stats.items()])
    
    prompt = (
        f"Ты Мастер D&D. Игрок: {name}, {char_class} {level} уровня. "
        f"Характеристики: {stat_str}. "
        f"Локация: {location}. Квест: {quest}. "
        f"События: {flags}. "
        f"Игрок написал: «{user_input}». Бросок d20: {roll}. "
        f"Опиши, что происходит. Дай атмосферный ответ, развивай сюжет. "
        f"Если игрок делает глупость — покажи последствия, но не убивай без предупреждения. "
        f"Отвечай на русском языке."
    )
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "Ты суровый, но справедливый Мастер D&D. Играй роль, будь атмосферным."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.9,
        "max_tokens": 500
    }
    
    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers=headers,
            json=data,
            timeout=20
        )
        
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"⚠️ Ошибка API: {response.status_code}\n{response.text[:200]}"
    except Exception as e:
        return f"⚠️ Ошибка подключения: {str(e)}"

# ---------- КОМАНДЫ ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, _ = get_active_char(user_id)
    if active_name:
        await update.message.reply_text(f"🧙‍♂️ С возвращением! Активен: **{active_name}**.\n\n📍 Ты в мире D&D. Напиши, что делаешь (осмотреться, идти в лес, поговорить со старейшиной).")
    else:
        await update.message.reply_text("🧙‍♂️ Добро пожаловать! Создай персонажа: «хочу нового персонажа».")

async def list_chars(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in user_characters or not user_characters[user_id]["chars"]:
        await update.message.reply_text("У тебя нет созданных персонажей.")
        return
    chars = user_characters[user_id]["chars"]
    active = user_characters[user_id]["active"]
    msg = "**Твои персонажи:**\n"
    for name, data in chars.items():
        marker = "👉" if name == active else "•"
        msg += f"{marker} **{name}** — {data.get('race', '??')} / {data.get('class', '??')} (ур. {data.get('level', 1)})\n"
    await update.message.reply_text(msg)

async def switch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    args = update.message.text.split()
    if len(args) < 2:
        await update.message.reply_text("Напиши /switch <имя>.")
        return
    target_name = " ".join(args[1:])
    if user_id in user_characters and target_name in user_characters[user_id]["chars"]:
        user_characters[user_id]["active"] = target_name
        save_json(CHARACTER_FILE, user_characters)
        await update.message.reply_text(f"✅ Активен **{target_name}**.")
    else:
        await update.message.reply_text(f"❌ Персонаж «{target_name}» не найден.")

async def reset_char(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    args = update.message.text.split()
    if len(args) >= 2 and args[1].lower() == "all":
        if user_id in user_characters:
            user_characters[user_id] = {"chars": {}, "active": None}
            save_json(CHARACTER_FILE, user_characters)
            await update.message.reply_text("🗑️ Все удалены.")
        return
    if user_id in user_characters and user_characters[user_id]["active"]:
        del user_characters[user_id]["chars"][user_characters[user_id]["active"]]
        user_characters[user_id]["active"] = None
        save_json(CHARACTER_FILE, user_characters)
        await update.message.reply_text("🗑️ Активный персонаж удалён.")
    else:
        await update.message.reply_text("❌ Нет активного.")

async def inventory(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, char = get_active_char(user_id)
    if not char:
        await update.message.reply_text("У тебя нет активного персонажа.")
        return
    inv = char.get("inventory", [])
    companions = char.get("companions", [])
    msg = f"**Инвентарь {char['name']}:**\n"
    msg += "\n".join([f"• {item}" for item in inv]) if inv else "Пусто."
    if companions:
        msg += "\n\n**Компаньоны:**\n" + "\n".join([f"• {comp}" for comp in companions])
    world = world_state.get(user_id, {})
    world_inv = world.get("inventory_world", [])
    if world_inv:
        msg += "\n\n**Мировые предметы:**\n" + "\n".join([f"• {item}" for item in world_inv])
    await update.message.reply_text(msg)

async def random_character(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id in creation_steps:
        del creation_steps[user_id]
    await update.message.reply_text("🎲 Создаём случайного героя!")
    race = random.choice(VALID_RACES)
    char_class = random.choice(VALID_CLASSES)
    base_stats = [15, 14, 13, 12, 10, 8]
    random.shuffle(base_stats)
    stats = {
        "str": base_stats[0], "dex": base_stats[1], "con": base_stats[2],
        "int": base_stats[3], "wis": base_stats[4], "cha": base_stats[5]
    }
    name = f"{race} {char_class}"
    char_data = {
        "name": name, "race": race, "subrace": "Стандартный", "class": char_class,
        "subclass": "Стандартный", "extra_race": None, "extra_class": None,
        "stats": stats, "appearance": "Не указана", "background": "Не указана",
        "level": 1, "xp": 0, "inventory": [], "companions": []
    }
    add_character(user_id, char_data, set_active=True)
    init_world(user_id)
    await update.message.reply_text("✅ Создан! Лист:")
    await update.message.reply_text(format_character_sheet(char_data))

async def new_char(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id in creation_steps:
        del creation_steps[user_id]
    creation_steps[user_id] = {"step": "name"}
    ctx.user_data['temp_char'] = {}
    await update.message.reply_text("🧙‍♂️ Создаём героя! Как его зовут?")

# ---------- ОСНОВНАЯ ЛОГИКА ----------
async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    user_text = update.message.text
    text_lower = user_text.lower()

    if "хочу нового персонажа" in text_lower or "/new" in text_lower:
        await new_char(update, ctx); return
    if "/list" in text_lower:
        await list_chars(update, ctx); return
    if text_lower.startswith("/switch"):
        await switch(update, ctx); return
    if text_lower.startswith("/reset"):
        await reset_char(update, ctx); return
    if text_lower.startswith("/inventory"):
        await inventory(update, ctx); return

    if user_id in creation_steps:
        await handle_creation(update, ctx)
        return

    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Нет персонажа. Создай: «хочу нового персонажа».")
        return

    if user_id not in world_state:
        init_world(user_id)
    world = world_state[user_id]
    location = world.get("location", "деревня")
    
    # Проверка на команды осмотра и перемещения (остаётся без изменений)
    if "осмотреться" in text_lower or "осмотр" in text_lower:
        if location == "деревня":
            response = "🌾 Ты в деревне. Видишь: таверну, кузницу, дом старейшины и тропу в лес."
        elif location == "лес":
            response = "🌲 Ты в тёмном лесу. Слышно пение птиц и шорох листьев. Есть тропа к пещере."
        elif location == "пещера":
            response = "🕯️ Ты в сырой пещере. Слышен звук капающей воды. Глубоко в темноте кто-то шевелится."
        elif location == "замок":
            response = "🏰 Ты у ворот старого замка. Они приоткрыты. Внутри слышны шаги."
        else:
            response = f"📍 Ты в {location}. Осмотрись внимательнее."
        await update.message.reply_text(response)
        return

    if "идти" in text_lower:
        if "деревня" in text_lower:
            world["location"] = "деревня"
            response = "🚶 Ты возвращаешься в деревню."
        elif "лес" in text_lower:
            world["location"] = "лес"
            response = "🌳 Ты входишь в лес. Ветви скрывают небо."
        elif "пещера" in text_lower:
            world["location"] = "пещера"
            response = "🕳️ Ты входишь в пещеру. Темно и сыро."
        elif "замок" in text_lower:
            world["location"] = "замок"
            response = "🏰 Ты подходишь к замку. Ворота скрипят."
        else:
            response = "❓ Я не знаю такого места. Можно пойти в: деревня, лес, пещера, замок."
        save_json(WORLD_FILE, world_state)
        await update.message.reply_text(response)
        return

    if "поговорить" in text_lower or "сказать" in text_lower:
        if "старейшина" in text_lower:
            npc_text = world.get("npcs", {}).get("старейшина", {}).get("диалог", "Старейшина молчит.")
            response = f"👴 Старейшина: «{npc_text}»"
            if not world.get("flags", {}).get("знает_старейшину"):
                world["flags"]["знает_старейшину"] = True
                response += "\n\n📜 Ты получил квест: принеси амулет из леса."
                world["quests"]["актив"] = "Найди амулет в лесу и верни старейшине."
            save_json(WORLD_FILE, world_state)
            await update.message.reply_text(response)
            return

    if "искать" in text_lower or "поиск" in text_lower:
        if location == "лес" and not world.get("flags", {}).get("амулет_найден"):
            if random.random() < 0.6:
                world["flags"]["амулет_найден"] = True
                world["inventory_world"].append("амулет леса")
                response = "🍃 Ты нашёл амулет под корнями дуба! Он светится тусклым светом."
            else:
                response = "🔍 Ты обыскал лес, но ничего не нашёл. Попробуй ещё раз."
            save_json(WORLD_FILE, world_state)
            await update.message.reply_text(response)
            return
        elif location == "пещера" and not world.get("flags", {}).get("сундук_открыт"):
            if random.random() < 0.5:
                world["flags"]["сундук_открыт"] = True
                world["inventory_world"].append("золотая монета")
                response = "💰 Ты нашёл сундук с 50 золотыми монетами!"
            else:
                response = "🕳️ В пещере темно, ты ничего не видишь."
            save_json(WORLD_FILE, world_state)
            await update.message.reply_text(response)
            return

    if "квест" in text_lower:
        await update.message.reply_text(f"📜 **Текущий квест:** {world.get('quests', {}).get('актив', 'Нет активного квеста.')}")
        return

    if "бить" in text_lower or "атака" in text_lower:
        d20 = random.randint(1, 20)
        if d20 >= 15:
            response = f"⚔️ Ты атакуешь! Бросок d20: {d20}. Урон: {random.randint(5,10)}. Враг ранен!"
        elif d20 >= 10:
            response = f"🎲 Бросок d20: {d20}. Ты попадаешь, но слабо. Урон 2."
        else:
            response = f"💨 Бросок d20: {d20}. Промах! Враг смеётся."
        await update.message.reply_text(response)
        return

    if "статы" in text_lower:
        stats = char_data.get('stats', {})
        response = f"📊 **Характеристики:**\n" + "\n".join([f"{k.upper()}: {v}" for k, v in stats.items()])
        await update.message.reply_text(response)
        return

    if "помощь" in text_lower or "help" in text_lower:
        response = (
            "📖 **Доступные действия:**\n"
            "• осмотреться — увидеть окружение\n"
            "• идти в [лес/деревню/пещеру/замок] — переместиться\n"
            "• поговорить со старейшиной — получить квест\n"
            "• искать — найти предметы\n"
            "• квест — проверить задание\n"
            "• бить/атака — сразиться с врагом\n"
            "• статы — посмотреть характеристики\n"
            "• инвентарь — посмотреть вещи"
        )
        await update.message.reply_text(response)
        return

    # Если ничего не подошло — отправляем в DeepSeek
    roll = random.randint(1, 20)
    await update.message.reply_text(f"🎲 Мастер слушает... (бросок d20: {roll})")
    
    response = ask_deepseek(user_text, roll, char_data, world)
    
    # Опыт и уровень
    xp_gain = random.randint(5, 15)
    char_data['xp'] = char_data.get('xp', 0) + xp_gain
    level = char_data.get('level', 1)
    if char_data['xp'] >= level * 30:
        char_data['xp'] -= level * 30
        char_data['level'] = level + 1
        user_characters[user_id]["chars"][active_name] = char_data
        save_json(CHARACTER_FILE, user_characters)
        response += f"\n\n🎉 Ты достиг {char_data['level']} уровня!"
    
    world["story_log"] = world.get("story_log", []) + [f"{user_text} -> {response[:100]}..."]
    save_json(WORLD_FILE, world_state)
    await update.message.reply_text(response)

# ---------- СОЗДАНИЕ ПЕРСОНАЖА ----------
async def handle_creation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    user_text = update.message.text
    step_info = creation_steps.get(user_id)
    if not step_info:
        return
    step = step_info.get("step")
    temp = ctx.user_data.get('temp_char', {})

    if step == "name":
        temp["name"] = user_text.strip()
        creation_steps[user_id]["step"] = "race"
        await update.message.reply_text(f"Выбери расу:\n{', '.join(VALID_RACES)}.")
    elif step == "race":
        norm = user_text.strip().lower()
        race = next((r for r in VALID_RACES if norm in r.lower()), None)
        if not race:
            await update.message.reply_text(f"Не знаю. Выбери из: {', '.join(VALID_RACES)}")
            return
        temp["race"] = race
        creation_steps[user_id]["step"] = "subrace"
        await update.message.reply_text(f"Подраса? ({', '.join(RACES[race])}) или «нет».")
    elif step == "subrace":
        temp["subrace"] = "Стандартный" if user_text.strip().lower() in ["нет","skip"] else user_text.strip()
        creation_steps[user_id]["step"] = "class"
        await update.message.reply_text(f"Класс:\n{', '.join(VALID_CLASSES)}.")
    elif step == "class":
        norm = user_text.strip().lower()
        char_class = next((c for c in VALID_CLASSES if norm in c.lower()), None)
        if not char_class:
            await update.message.reply_text(f"Нет. Выбери: {', '.join(VALID_CLASSES)}")
            return
        temp["class"] = char_class
        creation_steps[user_id]["step"] = "subclass"
        await update.message.reply_text(f"Подкласс? ({', '.join(CLASSES[char_class])}) или «нет».")
    elif step == "subclass":
        temp["subclass"] = "Стандартный" if user_text.strip().lower() in ["нет","skip"] else user_text.strip()
        creation_steps[user_id]["step"] = "stats"
        await update.message.reply_text("Характеристики (СИЛ ЛВК ТЕЛ ИНТ МДР ХАР): 6 чисел от 3 до 20.")
    elif step == "stats":
        parts = user_text.strip().split()
        if len(parts) != 6:
            await update.message.reply_text("Нужно 6 чисел.")
            return
        try:
            vals = [int(x) for x in parts]
            if any(v < 3 or v > 20 for v in vals):
                await update.message.reply_text("От 3 до 20.")
                return
            temp["stats"] = {
                "str": vals[0], "dex": vals[1], "con": vals[2],
                "int": vals[3], "wis": vals[4], "cha": vals[5]
            }
            creation_steps[user_id]["step"] = "appearance"
            await update.message.reply_text("Внешность (или «нет»).")
        except ValueError:
            await update.message.reply_text("Только целые числа.")
    elif step == "appearance":
        temp["appearance"] = "Не указана" if user_text.strip().lower() in ["нет","skip"] else user_text.strip()
        creation_steps[user_id]["step"] = "background"
        await update.message.reply_text("Предыстория (или «нет»).")
    elif step == "background":
        temp["background"] = "Не указана" if user_text.strip().lower() in ["нет","skip"] else user_text.strip()
        temp["level"] = 1
        temp["xp"] = 0
        temp["inventory"] = []
        temp["companions"] = []
        add_character(user_id, temp, set_active=True)
        init_world(user_id)
        if user_id in creation_steps:
            del creation_steps[user_id]
        await update.message.reply_text("✅ Персонаж создан!")
        await update.message.reply_text(format_character_sheet(temp))

def format_character_sheet(char_data):
    stats = char_data.get('stats', {})
    stat_lines = "\n".join([f"  • {k.upper()}: {v}" for k, v in stats.items()])
    return (
        f"📜 **Лист Персонажа**\n\n"
        f"🧝 **Имя:** {char_data['name']}\n"
        f"⚔️ **Раса:** {char_data.get('race', '??')}\n"
        f"🎯 **Класс:** {char_data.get('class', '??')}\n"
        f"⬆️ **Уровень:** {char_data.get('level', 1)}\n"
        f"💡 **Опыт:** {char_data.get('xp', 0)} / {char_data.get('level', 1) * 30}\n\n"
        f"📊 **Характеристики:**\n{stat_lines}\n\n"
        f"👁️ **Внешность:**\n{char_data.get('appearance', 'Не указана')}\n\n"
        f"📖 **Предыстория:**\n{char_data.get('background', 'Не указана')}"
    )

# ---------- ЗАПУСК ----------
def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN не найден в .env!")
    builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    if PROXY_URL:
        builder = builder.proxy_url(PROXY_URL)
    app = builder.build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_char))
    app.add_handler(CommandHandler("list", list_chars))
    app.add_handler(CommandHandler("switch", switch))
    app.add_handler(CommandHandler("reset", reset_char))
    app.add_handler(CommandHandler("inventory", inventory))
    app.add_handler(CommandHandler("random", random_character))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("✅ D&D-бот с DeepSeek готов!")
    app.run_polling()

if __name__ == '__main__':
    main()
