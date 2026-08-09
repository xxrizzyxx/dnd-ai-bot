import os
import json
import random
import requests
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
            "quests": {"актив": "Исследуй мир и найди своё приключение.", "выполн": []},
            "flags": {},
            "npcs": {},
            "inventory_world": [],
            "story_log": []
        }
        save_json(WORLD_FILE, world_state)
    return world_state[user_id]

# ---------- ЗАПРОС К OPENROUTER (БЕСПЛАТНЫЙ DEEPSEEK) ----------
def ask_deepseek(user_input, roll, char_data, world):
    if not DEEPSEEK_API_KEY:
        return "⚠️ Нет API-ключа. Добавь DEEPSEEK_API_KEY в .env"
    
    location = world.get("location", "неизвестно")
    quest = world.get("quests", {}).get("актив", "нет")
    flags = world.get("flags", {})
    name = char_data.get("name", "Герой")
    char_class = char_data.get("class", "воин")
    level = char_data.get("level", 1)
    stats = char_data.get("stats", {})
    stat_str = ", ".join([f"{k.upper()}: {v}" for k, v in stats.items()])
    
    prompt = (
        f"Ты — Мастер D&D. Игрок: {name}, {char_class} {level} уровня. "
        f"Характеристики: {stat_str}. Локация: {location}. Квест: {quest}. "
        f"Флаги: {flags}. Игрок написал: «{user_input}». Бросок d20: {roll}. "
        f"Опиши результат максимально подробно, атмосферно и красочно. Минимум 3 абзаца. Отвечай на русском."
    )
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "deepseek/deepseek-chat-v3-0324:free",
        "messages": [
            {"role": "system", "content": "Ты — талантливый писатель и суровый Мастер D&D. Твои ответы всегда длинные, детализированные и захватывающие."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.95,
        "max_tokens": 1000
    }
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=25
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"⚠️ Ошибка API: {response.status_code}\n{response.text[:300]}"
    except Exception as e:
        return f"⚠️ Ошибка: {str(e)}"

# ---------- КОМАНДЫ ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, _ = get_active_char(user_id)
    if active_name:
        await update.message.reply_text(
            f"🧙‍♂️ Добро пожаловать в мир приключений, {active_name}!\n"
            f"Ты находишься в таверне на окраине деревни. Что ты хочешь сделать?\n\n"
            f"Просто напиши своё действие — я расскажу, что произойдёт."
        )
    else:
        await update.message.reply_text(
            "🧙‍♂️ Приветствую, искатель приключений!\n"
            "Для начала создай персонажа: напиши **«хочу нового персонажа»** или **/new**."
        )

async def new_char(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id in creation_steps:
        del creation_steps[user_id]
    creation_steps[user_id] = {"step": "name"}
    ctx.user_data['temp_char'] = {}
    await update.message.reply_text("🧙‍♂️ Как зовут твоего героя?")

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

    roll = random.randint(1, 20)
    await update.message.reply_text(f"🎲 Мастер слушает... (бросок d20: {roll})")
    
    response = ask_deepseek(user_text, roll, char_data, world)
    
    xp_gain = random.randint(5, 20)
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
    print("✅ D&D-бот с OpenRouter (DeepSeek бесплатно) запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()
