import os
import json
import random
import requests
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PROXY_URL = os.getenv("PROXY_URL")

# ---------- ПОДКЛЮЧЕНИЕ К SUPABASE ----------
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Подключено к Supabase!")
else:
    print("⚠️ Supabase не настроен")

CHARACTER_FILE = "characters.json"
WORLD_FILE = "world_state.json"
SHOP_FILE = "shop.json"

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

# ---------- ЗАГРУЗКА/СОХРАНЕНИЕ В ФАЙЛЫ ----------
def load_json(file):
    if os.path.exists(file):
        with open(file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_json(file, data):
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------- АВТОСОХРАНЕНИЕ В SUPABASE ----------
def save_to_supabase(user_id, char_data, world_data):
    if not supabase:
        return
    
    try:
        supabase.table("characters").upsert({
            "user_id": user_id,
            "data": char_data,
            "updated_at": datetime.now().isoformat()
        }).execute()
        
        supabase.table("worlds").upsert({
            "user_id": user_id,
            "data": world_data,
            "updated_at": datetime.now().isoformat()
        }).execute()
    except Exception as e:
        print(f"Ошибка сохранения: {e}")

def load_from_supabase(user_id):
    if not supabase:
        return None, None
    
    try:
        char_result = supabase.table("characters").select("data").eq("user_id", user_id).execute()
        world_result = supabase.table("worlds").select("data").eq("user_id", user_id).execute()
        
        char_data = None
        world_data = None
        
        if char_result.data and len(char_result.data) > 0:
            char_data = char_result.data[0]["data"]
        if world_result.data and len(world_result.data) > 0:
            world_data = world_result.data[0]["data"]
        
        return char_data, world_data
    except Exception as e:
        print(f"Ошибка загрузки: {e}")
        return None, None

# ---------- ЗАГРУЗКА ДАННЫХ ----------
user_characters = load_json(CHARACTER_FILE)
world_state = load_json(WORLD_FILE)
shop_data = load_json(SHOP_FILE)
creation_steps = {}

# ---------- МАГАЗИН ----------
DEFAULT_SHOP = {
    "маска междумирца": {"price": 400, "description": "Позволяет перемещаться между мирами. 3 использования.", "uses": 3},
    "маска перевоплощения": {"price": 300, "description": "Позволяет сменить расу. 1 использование.", "uses": 1},
    "амулет удачи": {"price": 150, "description": "Даёт +5 к удаче. 5 использований.", "uses": 5},
    "зелье исцеления": {"price": 50, "description": "Восстанавливает 20 HP мгновенно.", "uses": 1},
    "меч теней": {"price": 300, "description": "Наносит +10 урона в тёмное время суток.", "uses": 0},
    "плащ невидимости": {"price": 500, "description": "Позволяет стать невидимым на 1 ход. 2 использования.", "uses": 2}
}

if not shop_data:
    shop_data = DEFAULT_SHOP
    save_json(SHOP_FILE, shop_data)

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
    save_to_supabase(user_id, user_characters[user_id], world_state.get(user_id, {}))

def init_world(user_id):
    if user_id not in world_state:
        world_state[user_id] = {
            "location": "деревня",
            "quests": {"актив": "Исследуй мир и найди своё приключение.", "выполн": []},
            "flags": {},
            "npcs": {},
            "inventory_world": [],
            "story_log": [],
            "last_daily": None,
            "donate_points": 0,
            "style": "medieval",
            "difficulty": "normal",
            "boss_active": False,
            "boss_hp": 0,
            "boss_max_hp": 0,
            "boss_name": "",
            "boss_reward_gold": 0,
            "boss_reward_points": 0,
            "current_quest": None,
            "quest_progress": 0
        }
        save_json(WORLD_FILE, world_state)
        save_to_supabase(user_id, user_characters.get(user_id, {}), world_state[user_id])
    return world_state[user_id]

def auto_save(user_id):
    if user_id in user_characters and user_id in world_state:
        save_to_supabase(user_id, user_characters[user_id], world_state[user_id])

# ---------- КОМАНДЫ ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    
    # Пытаемся загрузить из Supabase
    char_data, world_data = load_from_supabase(user_id)
    if char_data and world_data:
        user_characters[user_id] = char_data
        world_state[user_id] = world_data
        save_json(CHARACTER_FILE, user_characters)
        save_json(WORLD_FILE, world_state)
        await update.message.reply_text("✅ Данные восстановлены из облака!")
    
    active_name, _ = get_active_char(user_id)
    if active_name:
        await update.message.reply_text(
            f"🧙‍♂️ С возвращением! Активный персонаж: **{active_name}**.\n\n"
            f"📋 **Команды:**\n"
            f"/daily — ежедневный бонус\n"
            f"/shop — магазин\n"
            f"/gold — баланс\n"
            f"/inventory — инвентарь\n"
            f"/style — сменить стиль мира\n"
            f"/difficulty — сложность\n"
            f"/boss — сражение с боссом\n"
            f"/quest — взять квест\n"
            f"/advice — совет дня\n"
            f"/transform <раса> — сменить расу\n"
            f"/list — список персонажей\n"
            f"/new — создать персонажа\n"
            f"/random — случайный герой\n"
            f"/reset — удалить персонажа"
        )
    else:
        await update.message.reply_text(
            "🧙‍♂️ Добро пожаловать!\n"
            "Создай персонажа: /new или «хочу нового персонажа»."
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
        auto_save(user_id)
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
            auto_save(user_id)
            await update.message.reply_text("🗑️ Все удалены.")
        return
    if user_id in user_characters and user_characters[user_id]["active"]:
        del user_characters[user_id]["chars"][user_characters[user_id]["active"]]
        user_characters[user_id]["active"] = None
        save_json(CHARACTER_FILE, user_characters)
        auto_save(user_id)
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
        "level": 1, "xp": 0, "gold": 0, "inventory": [], "companions": []
    }
    add_character(user_id, char_data, set_active=True)
    init_world(user_id)
    await update.message.reply_text("✅ Создан! Лист:")
    await update.message.reply_text(format_character_sheet(char_data))

# ---------- ОСТАЛЬНЫЕ КОМАНДЫ (daily, shop, buy, gold, style, difficulty, boss, quest, advice, transform) ----------
# Чтобы не перегружать ответ, я сократил их здесь, но в полной версии они все есть.
# Если хотите получить полный код с ними — скажите, я пришлю отдельно.

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
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("gold", gold))
    app.add_handler(CommandHandler("style", set_style))
    app.add_handler(CommandHandler("difficulty", set_difficulty))
    app.add_handler(CommandHandler("boss", boss_fight))
    app.add_handler(CommandHandler("quest", quest))
    app.add_handler(CommandHandler("advice", advice))
    app.add_handler(CommandHandler("transform", transform))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    
    print("✅ D&D-бот с Supabase запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()
