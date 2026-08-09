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
        char_data = char_result.data[0]["data"] if char_result.data and len(char_result.data) > 0 else None
        world_data = world_result.data[0]["data"] if world_result.data and len(world_result.data) > 0 else None
        return char_data, world_data
    except Exception as e:
        print(f"Ошибка загрузки: {e}")
        return None, None

user_characters = load_json(CHARACTER_FILE)
world_state = load_json(WORLD_FILE)
shop_data = load_json(SHOP_FILE)
creation_steps = {}

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

# ---------- ВСЕ КОМАНДЫ ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
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
        await update.message.reply_text("🧙‍♂️ Добро пожаловать!\nСоздай персонажа: /new или «хочу нового персонажа».")

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
    stats = {"str": base_stats[0], "dex": base_stats[1], "con": base_stats[2], "int": base_stats[3], "wis": base_stats[4], "cha": base_stats[5]}
    name = f"{race} {char_class}"
    char_data = {"name": name, "race": race, "subrace": "Стандартный", "class": char_class, "subclass": "Стандартный", "extra_race": None, "extra_class": None, "stats": stats, "appearance": "Не указана", "background": "Не указана", "level": 1, "xp": 0, "gold": 0, "inventory": [], "companions": []}
    add_character(user_id, char_data, set_active=True)
    init_world(user_id)
    await update.message.reply_text("✅ Создан! Лист:")
    await update.message.reply_text(format_character_sheet(char_data))

async def daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Сначала создай персонажа: /new")
        return
    if user_id not in world_state:
        init_world(user_id)
    world = world_state[user_id]
    last = world.get("last_daily")
    if last:
        last_date = datetime.fromisoformat(last)
        if datetime.now() - last_date < timedelta(hours=24):
            await update.message.reply_text("⏳ Ты уже получал бонус сегодня. Возвращайся завтра!")
            return
    gold = random.randint(5, 50)
    char_data['gold'] = char_data.get('gold', 0) + gold
    world['last_daily'] = datetime.now().isoformat()
    user_characters[user_id]["chars"][active_name] = char_data
    save_json(CHARACTER_FILE, user_characters)
    save_json(WORLD_FILE, world_state)
    auto_save(user_id)
    await update.message.reply_text(f"🎁 Ежедневный бонус: +{gold} монет!")

async def shop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Сначала создай персонажа: /new")
        return
    msg = "🏪 **Магазин**\n\n"
    for item, data in shop_data.items():
        uses = f" ({data['uses']} использований)" if data['uses'] > 0 else ""
        msg += f"• **{item.title()}** — {data['price']} монет{uses}\n  {data['description']}\n\n"
    msg += "\nЧтобы купить, напиши: /buy <название товара>"
    await update.message.reply_text(msg)

async def buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Сначала создай персонажа: /new")
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("Напиши: /buy <название товара>")
        return
    item_name = args[1].strip().lower()
    if item_name not in shop_data:
        await update.message.reply_text(f"❌ Товар «{item_name}» не найден. Список: /shop")
        return
    item = shop_data[item_name]
    price = item['price']
    if char_data.get('gold', 0) < price:
        await update.message.reply_text(f"❌ Не хватает монет! Нужно {price}, у тебя {char_data.get('gold', 0)}")
        return
    char_data['gold'] -= price
    char_data['inventory'] = char_data.get('inventory', [])
    char_data['inventory'].append(item_name)
    user_characters[user_id]["chars"][active_name] = char_data
    save_json(CHARACTER_FILE, user_characters)
    auto_save(user_id)
    await update.message.reply_text(f"✅ Ты купил **{item_name.title()}**!\nОписание: {item['description']}\nОсталось монет: {char_data['gold']}")

async def gold(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Сначала создай персонажа: /new")
        return
    world = world_state.get(user_id, {})
    points = world.get('donate_points', 0)
    await update.message.reply_text(f"💰 **Баланс**\nМонеты: {char_data.get('gold', 0)}\nДонатные поинты: {points}\nУровень: {char_data.get('level', 1)}")

async def set_style(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Сначала создай персонажа: /new")
        return
    if user_id not in world_state:
        init_world(user_id)
    world = world_state[user_id]
    args = update.message.text.split()
    if len(args) < 2:
        await update.message.reply_text("Выбери стиль:\n/style medieval — Средневековье\n/style modern — Наше время\n/style cyberpunk — Киберпанк\n/style steampunk — Стимпанк\n/style fantasy — Фэнтези\n/style pirate — Пиратский")
        return
    style = args[1].lower()
    styles = ["medieval", "modern", "cyberpunk", "steampunk", "fantasy", "pirate"]
    if style not in styles:
        await update.message.reply_text("❌ Неверный стиль.")
        return
    world["style"] = style
    save_json(WORLD_FILE, world_state)
    auto_save(user_id)
    style_names = {"medieval": "Средневековье", "modern": "Наше время", "cyberpunk": "Киберпанк", "steampunk": "Стимпанк", "fantasy": "Фэнтези", "pirate": "Пиратский"}
    await update.message.reply_text(f"✅ Стиль изменён на **{style_names[style]}**!")

async def set_difficulty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Сначала создай персонажа: /new")
        return
    if user_id not in world_state:
        init_world(user_id)
    world = world_state[user_id]
    args = update.message.text.split()
    if len(args) < 2:
        await update.message.reply_text("Выбери сложность: /difficulty easy, /difficulty normal, /difficulty hard")
        return
    diff = args[1].lower()
    if diff not in ["easy", "normal", "hard"]:
        await update.message.reply_text("❌ Доступно: easy, normal, hard")
        return
    world["difficulty"] = diff
    save_json(WORLD_FILE, world_state)
    auto_save(user_id)
    diff_names = {"easy": "Лёгкая", "normal": "Обычная", "hard": "Сложная"}
    await update.message.reply_text(f"✅ Сложность изменена на **{diff_names[diff]}**!")

async def boss_fight(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Сначала создай персонажа: /new")
        return
    if user_id not in world_state:
        init_world(user_id)
    world = world_state[user_id]
    if world.get("boss_active", False):
        await update.message.reply_text("⚔️ Босс уже активен! Сражайся с ним через сообщения.")
        return
    level = char_data.get("level", 1)
    diff = world.get("difficulty", "normal")
    diff_mult = {"easy": 0.7, "normal": 1.0, "hard": 1.5}[diff]
    bosses = [{"name": "Дракон", "hp": 30 + level * 10, "reward_gold": 20 + level * 8, "reward_points": 2 + level // 2},
              {"name": "Лих", "hp": 25 + level * 8, "reward_gold": 15 + level * 6, "reward_points": 2 + level // 3},
              {"name": "Тролль", "hp": 20 + level * 6, "reward_gold": 10 + level * 5, "reward_points": 1 + level // 3},
              {"name": "Вампир", "hp": 28 + level * 9, "reward_gold": 18 + level * 7, "reward_points": 2 + level // 3},
              {"name": "Гидра", "hp": 35 + level * 12, "reward_gold": 25 + level * 10, "reward_points": 3 + level // 2}]
    boss = random.choice(bosses)
    boss["hp"] = int(boss["hp"] * diff_mult)
    boss["reward_gold"] = int(boss["reward_gold"] * diff_mult)
    world["boss_active"] = True
    world["boss_name"] = boss["name"]
    world["boss_hp"] = boss["hp"]
    world["boss_max_hp"] = boss["hp"]
    world["boss_reward_gold"] = boss["reward_gold"]
    world["boss_reward_points"] = boss["reward_points"]
    save_json(WORLD_FILE, world_state)
    auto_save(user_id)
    await update.message.reply_text(f"⚔️ **БОСС: {boss['name']}**\n❤️ HP: {boss['hp']}\n💰 Награда: {boss['reward_gold']} монет, {boss['reward_points']} поинтов\n\nАтакуй босса, написав «бью».")

async def quest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Сначала создай персонажа: /new")
        return
    if user_id not in world_state:
        init_world(user_id)
    world = world_state[user_id]
    level = char_data.get("level", 1)
    quests = [{"name": "Убить 5 гоблинов", "description": "Очисти лес от гоблинов.", "goal": 5, "reward_gold": 10 + level * 3, "reward_points": 1 + level // 4},
              {"name": "Найти древний артефакт", "description": "Принеси артефакт из пещеры.", "goal": 1, "reward_gold": 15 + level * 5, "reward_points": 2 + level // 3},
              {"name": "Победить бандитов", "description": "Очисти тракт от бандитов.", "goal": 3, "reward_gold": 12 + level * 4, "reward_points": 1 + level // 3},
              {"name": "Доставить письмо", "description": "Отнеси письмо в соседнюю деревню.", "goal": 1, "reward_gold": 5 + level * 2, "reward_points": 1},
              {"name": "Исследовать руины", "description": "Узнай, что скрывается в руинах.", "goal": 1, "reward_gold": 20 + level * 6, "reward_points": 2 + level // 2}]
    quest = random.choice(quests)
    world["current_quest"] = quest
    world["quest_progress"] = 0
    save_json(WORLD_FILE, world_state)
    auto_save(user_id)
    await update.message.reply_text(f"📜 **Новый квест: {quest['name']}**\n{quest['description']}\nЦель: {quest['goal']} раз\nНаграда: {quest['reward_gold']} монет, {quest['reward_points']} поинтов")

async def advice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tips = ["💡 Всегда имей зелье исцеления.", "💡 Исследуй каждую локацию.", "💡 Разговаривай с NPC.", "💡 Не бойся отступать.", "💡 Копи донатные поинты.", "💡 Используй окружение в бою.", "💡 Заходи за бонусом каждый день.", "💡 Прокачивай характеристики под класс."]
    await update.message.reply_text(random.choice(tips))

async def transform(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Сначала создай персонажа: /new")
        return
    args = update.message.text.split()
    if len(args) < 2:
        await update.message.reply_text("Напиши: /transform <раса>\nДоступные расы: " + ", ".join(VALID_RACES))
        return
    target_race = " ".join(args[1:]).lower()
    inventory = char_data.get("inventory", [])
    if "маска перевоплощения" not in inventory:
        await update.message.reply_text("❌ У тебя нет Маски Перевоплощения. Купи в магазине: /shop")
        return
    found_race = None
    for race in VALID_RACES:
        if target_race in race.lower():
            found_race = race
            break
    if not found_race:
        await update.message.reply_text(f"❌ Неизвестная раса. Доступны: {', '.join(VALID_RACES)}")
        return
    inventory.remove("маска перевоплощения")
    char_data["race"] = found_race
    char_data["subrace"] = "Стандартный"
    user_characters[user_id]["chars"][active_name] = char_data
    save_json(CHARACTER_FILE, user_characters)
    auto_save(user_id)
    await update.message.reply_text(f"🔄 Ты превратился в {found_race}!")

def ask_deepseek(user_input, roll, char_data, world):
    if not DEEPSEEK_API_KEY:
        return "⚠️ Нет API-ключа DeepSeek."
    location = world.get("location", "неизвестно")
    quest = world.get("quests", {}).get("актив", "нет")
    flags = world.get("flags", {})
    name = char_data.get("name", "Герой")
    char_class = char_data.get("class", "воин")
    level = char_data.get("level", 1)
    stats = char_data.get("stats", {})
    stat_str = ", ".join([f"{k.upper()}: {v}" for k, v in stats.items()])
    style = world.get("style", "medieval")
    difficulty = world.get("difficulty", "normal")
    boss_active = world.get("boss_active", False)
    boss_name = world.get("boss_name", "")
    boss_hp = world.get("boss_hp", 0)
    current_quest = world.get("current_quest")
    style_names = {"medieval": "Средневековье", "modern": "Наше время", "cyberpunk": "Киберпанк", "steampunk": "Стимпанк", "fantasy": "Фэнтези", "pirate": "Пиратский"}
    style_text = style_names.get(style, "Средневековье")
    diff_text = {"easy": "лёгкая", "normal": "обычная", "hard": "сложная"}.get(difficulty, "обычная")
    quest_text = f"Текущий квест: {current_quest['name']}. Прогресс: {world.get('quest_progress', 0)}/{current_quest['goal']}." if current_quest else ""
    boss_text = f"Босс {boss_name} активен! HP: {boss_hp}." if boss_active else ""
    prompt = (f"Ты — Мастер D&D. Игрок: {name}, {char_class} {level} уровня. "
              f"Характеристики: {stat_str}. Локация: {location}. "
              f"Стиль: {style_text}. Сложность: {diff_text}. "
              f"Квест: {quest_text} {boss_text} "
              f"Игрок написал: «{user_input}». Бросок d20: {roll}. "
              f"Опиши результат максимально подробно, атмосферно и красочно. Минимум 3 абзаца. Отвечай на русском.")
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    data = {"model": "deepseek/deepseek-chat-v3-0324:free", "messages": [{"role": "system", "content": "Ты — талантливый писатель и суровый Мастер D&D."}, {"role": "user", "content": prompt}], "temperature": 0.95, "max_tokens": 1000}
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data, timeout=25)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        return f"⚠️ Ошибка API: {response.status_code}"
    except Exception as e:
        return f"⚠️ Ошибка: {str(e)}"

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
        await handle_creation(update, ctx); return
    active_name, char_data = get_active_char(user_id)
    if not char_data:
        await update.message.reply_text("Нет персонажа. Создай: /new")
        return
    if user_id not in world_state:
        init_world(user_id)
    world = world_state[user_id]
    roll = random.randint(1, 20)
    await update.message.reply_text(f"🎲 Мастер слушает... (бросок d20: {roll})")
    response = ask_deepseek(user_text, roll, char_data, world)
    if world.get("boss_active", False) and ("бью" in text_lower or "атак" in text_lower or "удар" in text_lower or "босс" in text_lower):
        damage = random.randint(5, 15) + roll // 2
        world["boss_hp"] -= damage
        if world["boss_hp"] <= 0:
            world["boss_hp"] = 0
            world["boss_active"] = False
            gold_reward = world.get("boss_reward_gold", 0)
            points_reward = world.get("boss_reward_points", 0)
            char_data['gold'] = char_data.get('gold', 0) + gold_reward
            world['donate_points'] = world.get('donate_points', 0) + points_reward
            user_characters[user_id]["chars"][active_name] = char_data
            save_json(CHARACTER_FILE, user_characters)
            save_json(WORLD_FILE, world_state)
            response += f"\n\n⚔️ **БОСС ПОБЕЖДЁН!**\n💰 +{gold_reward} монет\n⭐ +{points_reward} донатных поинтов!"
        else:
            save_json(WORLD_FILE, world_state)
    if world.get("current_quest"):
        quest = world["current_quest"]
        progress = world.get("quest_progress", 0)
        quest_keywords = quest["name"].lower().split()
        if any(keyword in text_lower for keyword in quest_keywords) or "квест" in text_lower:
            world["quest_progress"] = progress + 1
            if world["quest_progress"] >= quest["goal"]:
                gold_reward = quest["reward_gold"]
                points_reward = quest["reward_points"]
                char_data['gold'] = char_data.get('gold', 0) + gold_reward
                world['donate_points'] = world.get('donate_points', 0) + points_reward
                user_characters[user_id]["chars"][active_name] = char_data
                save_json(CHARACTER_FILE, user_characters)
                response += f"\n\n📜 **КВЕСТ ВЫПОЛНЕН!**\n💰 +{gold_reward} монет\n⭐ +{points_reward} донатных поинтов!"
                world["current_quest"] = None
                world["quest_progress"] = 0
            else:
                save_json(WORLD_FILE, world_state)
    xp_gain = random.randint(5, 20)
    char_data['xp'] = char_data.get('xp', 0) + xp_gain
    level = char_data.get('level', 1)
    if char_data['xp'] >= level * 30:
        char_data['xp'] -= level * 30
        char_data['level'] = level + 1
        level = char_data['level']
        gold_reward = 10 + level * 5
        points_reward = 1 + level // 2
        char_data['gold'] = char_data.get('gold', 0) + gold_reward
        world['donate_points'] = world.get('donate_points', 0) + points_reward
        user_characters[user_id]["chars"][active_name] = char_data
        save_json(CHARACTER_FILE, user_characters)
        save_json(WORLD_FILE, world_state)
        response += f"\n\n🎉 **Ты достиг {level} уровня!**\n💰 +{gold_reward} монет\n⭐ +{points_reward} донатных поинтов!"
    else:
        user_characters[user_id]["chars"][active_name] = char_data
        save_json(CHARACTER_FILE, user_characters)
    world["story_log"] = world.get("story_log", []) + [f"{user_text} -> {response[:100]}..."]
    save_json(WORLD_FILE, world_state)
    auto_save(user_id)
    await update.message.reply_text(response)

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
            temp["stats"] = {"str": vals[0], "dex": vals[1], "con": vals[2], "int": vals[3], "wis": vals[4], "cha": vals[5]}
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
        temp["gold"] = 0
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
    return (f"📜 **Лист Персонажа**\n\n🧝 **Имя:** {char_data['name']}\n⚔️ **Раса:** {char_data.get('race', '??')}\n🎯 **Класс:** {char_data.get('class', '??')}\n⬆️ **Уровень:** {char_data.get('level', 1)}\n💡 **Опыт:** {char_data.get('xp', 0)} / {char_data.get('level', 1) * 30}\n💰 **Монеты:** {char_data.get('gold', 0)}\n\n📊 **Характеристики:**\n{stat_lines}\n\n👁️ **Внешность:**\n{char_data.get('appearance', 'Не указана')}\n\n📖 **Предыстория:**\n{char_data.get('background', 'Не указана')}")

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
