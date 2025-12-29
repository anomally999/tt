# royal_market.py — Royal Market Economy Bot
# Economy-only commands for medieval marketplace
import os
import random
import sqlite3
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from datetime import timedelta, datetime as dt, timezone
from discord.utils import utcnow

# ---------- ENV ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("PREFIX", "!")
DB_NAME = "royal_market.db"
DEBT_INTEREST_RATE = 0.02  # 2% daily
DAYS_BEFORE_PRISON = 3
PRISON_ROLE_NAME = "Debtor"
MAX_DAILY_GOLD = 10  # Maximum daily stipend
DAILY_TAX = 4  # Daily royal tax deduction

# ---------- MEDIEVAL FLAIR ----------
MEDIEVAL_COLORS = {
    "gold": discord.Colour.gold(),
    "red": discord.Colour.dark_red(),
    "green": discord.Colour.dark_green(),
    "blue": discord.Colour.dark_blue(),
    "purple": discord.Colour.purple(),
    "orange": discord.Colour.dark_orange(),
    "teal": discord.Colour.teal(),
    "blurple": discord.Colour.blurple(),
}

MEDIEVAL_PREFIXES = [
    "Hark!", "Verily,", "By mine honour,", "Prithee,", "Forsooth,", "Hear ye, hear ye!",
    "Lo and behold,", "By mine troth,", "Marry,", "Gadzooks!", "Zounds!", "By the saints,",
    "By my halidom,", "In faith,", "By my beard,", "By the rood,", "Alack,", "Alas,", "Fie!",
    "Good my lord,", "Noble sir,", "Fair lady,", "By the mass,", "Gramercy,", "Well met,",
    "God ye good den,", "What ho!", "Avaunt!", "By cock and pie,", "Odds bodikins!",
]

MEDIEVAL_SUFFIXES = [
    "m'lord.", "good sir.", "fair maiden.", "noble knight.", "worthy peasant.", "gentle soul.",
    "brave warrior.", "wise sage.", "royal subject.", "courtier.", "squire.", "yeoman.",
    "varlet.", "knave.", "villager.", "my liege.", "thou valiant soul.", "thou stout yeoman.",
    "thou gracious dame.", "as the saints bear witness.", "upon mine honour.", "by the Virgin's grace.",
]

MEDIEVAL_GREETINGS = [
    "Hail, good traveler!", "Well met in these fair lands!", "God's greeting to thee!",
    "May fortune favor thee this day!", "A joyous day to thee, wanderer!",
    "The realm welcomes thy presence!", "Blessings upon thee, wayfarer!",
]

def get_medieval_prefix():
    return random.choice(MEDIEVAL_PREFIXES)

def get_medieval_suffix():
    return random.choice(MEDIEVAL_SUFFIXES) if random.random() > 0.4 else ""

def medieval_greeting():
    return random.choice(MEDIEVAL_GREETINGS)

def medieval_embed(title="", description="", color_name="gold"):
    color = MEDIEVAL_COLORS.get(color_name, MEDIEVAL_COLORS["gold"])
    embed = discord.Embed(
        title=f"🏰 {title}" if "🏰" not in title and "💰" not in title and "🏪" not in title else title,
        description=description,
        colour=color,
        timestamp=utcnow()
    )
    embed.set_footer(text="By royal decree of the realm")
    return embed

def medieval_response(message, success=True, extra=""):
    prefix = get_medieval_prefix()
    suffix = get_medieval_suffix()
    color = "green" if success else "red"
    full_message = f"{prefix} {message} {suffix}".strip().capitalize()
    if extra:
        full_message += f"\n\n{extra}"
    return medieval_embed(description=full_message, color_name=color)

# ---------- BOT ----------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None, case_insensitive=True)
tree = bot.tree

# ---------- ECONOMY DB ----------
def init_db():
    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS economy (
            user_id INTEGER PRIMARY KEY,
            gold INTEGER DEFAULT 0,
            debt INTEGER DEFAULT 0,
            debt_since TEXT,
            hp INTEGER DEFAULT 100
        )""")
        db.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            item TEXT,
            qty INTEGER,
            equipped INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, item)
        )""")
        db.execute("""
        CREATE TABLE IF NOT EXISTS cooldowns (
            user_id INTEGER PRIMARY KEY,
            last_labour TEXT,
            last_daily TEXT,
            last_gamble TEXT,
            last_slots TEXT,
            last_coinflip TEXT,
            last_battle TEXT
        )""")
        db.execute("""
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            market_channel INTEGER,
            baron_role INTEGER,
            viscount_role INTEGER,
            tax_roles TEXT,
            prison_role INTEGER
        )""")

        # Safe column additions
        columns_to_add = [
            ("guild_config", "baron_role", "INTEGER"),
            ("guild_config", "viscount_role", "INTEGER"),
            ("guild_config", "tax_roles", "TEXT"),
            ("guild_config", "prison_role", "INTEGER"),
            ("economy", "hp", "INTEGER DEFAULT 100"),
            ("inventory", "equipped", "INTEGER DEFAULT 0"),
            ("cooldowns", "last_battle", "TEXT"),
        ]
        
        for table, column, col_type in columns_to_add:
            try:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass

        db.commit()

# ---------- ECONOMY SYSTEM ----------
CAP_GOLD = 5000000
MAX_HP = 100

def get_pouch(user_id, ctx=None):
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT gold, debt, debt_since, hp FROM economy WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            db.execute("INSERT INTO economy (user_id, gold, hp) VALUES (?,?,?)", (user_id, 10, MAX_HP))
            db.commit()
            return 10, 0, None, MAX_HP
        g, d, ds, hp = row
        if ctx and ctx.guild:
            member = ctx.guild.get_member(user_id)
            if member and member.guild_permissions.administrator:
                target_gold = CAP_GOLD // 2
                if g < target_gold:
                    db.execute("UPDATE economy SET gold=? WHERE user_id=?", (target_gold, user_id))
                    db.commit()
                    g = target_gold
        return g, d, ds, hp

def add_coin(user_id, gold=0, ctx=None):
    current_gold, d, ds, hp = get_pouch(user_id, ctx)
    if gold > 0 and d > 0:
        pay_amount = min(gold, d)
        d -= pay_amount
        gold -= pay_amount
        if d == 0:
            ds = None
    new_gold = current_gold + gold
    if new_gold < 0:
        d -= new_gold  # d += abs(new_gold)
        if ds is None:
            ds = utcnow().isoformat()
        new_gold = 0
    new_gold = min(new_gold, CAP_GOLD)
    with sqlite3.connect(DB_NAME) as db:
        db.execute("UPDATE economy SET gold=?, debt=?, debt_since=? WHERE user_id=?", (new_gold, d, ds, user_id))
        db.commit()

def set_debt(user_id, amount):
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT debt_since FROM economy WHERE user_id=?", (user_id,)).fetchone()
        ds = row[0] if row else None
        if amount > 0 and ds is None:
            ds = utcnow().isoformat()
        elif amount <= 0:
            ds = None
        db.execute("UPDATE economy SET debt=?, debt_since=? WHERE user_id=?", (amount, ds, user_id))
        db.commit()

def update_hp(user_id, hp_change):
    current_gold, d, ds, current_hp = get_pouch(user_id)
    new_hp = max(0, min(MAX_HP, current_hp + hp_change))
    with sqlite3.connect(DB_NAME) as db:
        db.execute("UPDATE economy SET hp=? WHERE user_id=?", (new_hp, user_id))
        db.commit()
    return new_hp

# ---------- SEPARATE COOLDOWNS ----------
def get_cooldown(user_id, action_type):
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute(f"SELECT last_{action_type} FROM cooldowns WHERE user_id=?", (user_id,)).fetchone()
        if not row or not row[0]:
            return None
        try:
            return dt.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

def set_cooldown(user_id, action_type):
    with sqlite3.connect(DB_NAME) as db:
        db.execute("INSERT OR IGNORE INTO cooldowns (user_id) VALUES (?)", (user_id,))
        db.execute(f"UPDATE cooldowns SET last_{action_type}=? WHERE user_id=?", (utcnow().isoformat(), user_id))
        db.commit()

# ---------- INVENTORY ----------
def add_item(user_id, item, qty=1, equipped=0):
    with sqlite3.connect(DB_NAME) as db:
        old = db.execute("SELECT qty, equipped FROM inventory WHERE user_id=? AND item=?", (user_id, item)).fetchone()
        old_qty = old[0] if old else 0
        old_equipped = old[1] if old else 0
        db.execute("INSERT OR REPLACE INTO inventory (user_id, item, qty, equipped) VALUES (?,?,?,?)",
                   (user_id, item, old_qty + qty, max(old_equipped, equipped)))
        db.commit()

def remove_item(user_id, item, qty=1):
    with sqlite3.connect(DB_NAME) as db:
        old = db.execute("SELECT qty FROM inventory WHERE user_id=? AND item=?", (user_id, item)).fetchone()
        if not old or old[0] < qty:
            return False
        new_qty = old[0] - qty
        if new_qty <= 0:
            db.execute("DELETE FROM inventory WHERE user_id=? AND item=?", (user_id, item))
        else:
            db.execute("UPDATE inventory SET qty=? WHERE user_id=? AND item=?", (new_qty, user_id, item))
        db.commit()
        return True

def get_inventory(user_id):
    with sqlite3.connect(DB_NAME) as db:
        rows = db.execute("SELECT item, qty FROM inventory WHERE user_id=?", (user_id,)).fetchall()
        return {r[0]: r[1] for r in rows} if rows else {}

def has_item(user_id, item, qty=1):
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT qty FROM inventory WHERE user_id=? AND item=?", (user_id, item)).fetchone()
        return row is not None and row[0] >= qty

def equip_item(user_id, item):
    item_data = ROYAL_MARKET.get(item, {})
    item_type = item_data.get("type")
    if item_type not in ["weapon", "armor"] or not has_item(user_id, item):
        return False
    
    # Get all items of the same type
    same_type_items = []
    for item_key, data in ROYAL_MARKET.items():
        if data.get("type") == item_type:
            same_type_items.append(item_key)
    
    with sqlite3.connect(DB_NAME) as db:
        # Unequip other items of same type
        if same_type_items:
            placeholders = ','.join(['?'] * len(same_type_items))
            db.execute(f"""
                UPDATE inventory SET equipped=0
                WHERE user_id=? AND item IN ({placeholders}) AND item !=?
            """, (user_id, *same_type_items, item))
        
        # Equip the new item
        db.execute("UPDATE inventory SET equipped=1 WHERE user_id=? AND item=?", (user_id, item))
        db.commit()
    return True

def get_equipped(user_id):
    with sqlite3.connect(DB_NAME) as db:
        rows = db.execute("SELECT item FROM inventory WHERE user_id=? AND equipped=1", (user_id,)).fetchall()
        return [row[0] for row in rows] if rows else []

# ---------- ROYAL MARKETPLACE ----------
ROYAL_MARKET = {
    # Food & Drink (provisions, no bonuses)
    "bread": {"price": 1, "desc": "A hearty loaf to fill a peasant's belly", "type": "food", "use": "Restores vigor"},
    "ale": {"price": 1, "desc": "Foaming tankard of barley brew", "type": "drink", "use": "Cheers the spirit"},
    "cheese": {"price": 1, "desc": "Wheel of aged goat cheese", "type": "food", "use": "Sustains on long journeys"},
    "roast_chicken": {"price": 2, "desc": "Whole roasted fowl with herbs", "type": "food", "use": "Feasts the hungry"},
    "mead": {"price": 1, "desc": "Honey wine of the northlands", "type": "drink", "use": "Warms the bones"},
    # Weapons
    "dagger": {"price": 25, "desc": "Small blade for close encounters", "type": "weapon", "use": "+2 to stealth", "atk_bonus": 2},
    "shortsword": {"price": 50, "desc": "Reliable blade for any fighter", "type": "weapon", "use": "+3 to combat", "atk_bonus": 3},
    "longbow": {"price": 40, "desc": "Yew bow with quiver of arrows", "type": "weapon", "use": "+4 to ranged attacks", "atk_bonus": 4},
    "battleaxe": {"price": 75, "desc": "Heavy axe for strong warriors", "type": "weapon", "use": "+5 to damage", "atk_bonus": 5},
    "warhammer": {"price": 65, "desc": "Crushing weapon of knights", "type": "weapon", "use": "Shatters armor", "atk_bonus": 5},
    # Armor
    "leather_armor": {"price": 45, "desc": "Light protection for travelers", "type": "armor", "use": "+2 defense", "def_bonus": 2},
    "chainmail": {"price": 90, "desc": "Interlocking metal rings", "type": "armor", "use": "+5 defense", "def_bonus": 5},
    "plate_armor": {"price": 200, "desc": "Full steel plate of knights", "type": "armor", "use": "+8 defense", "def_bonus": 8},
    "shield": {"price": 30, "desc": "Wooden shield with iron boss", "type": "armor", "use": "Blocks arrows", "def_bonus": 3},
    "helmet": {"price": 25, "desc": "Steel helmet with nasal guard", "type": "armor", "use": "Protects head", "def_bonus": 2},
    # Magic Items
    "healing_potion": {"price": 15, "desc": "Restores vitality in dire times", "type": "potion", "use": "Heals wounds", "heal": 30},
    "mana_potion": {"price": 20, "desc": "Restores magical energy", "type": "potion", "use": "Refreshes spells", "heal": 0},
    "enchanted_ring": {"price": 500, "desc": "Magical ring with unknown powers", "type": "magic", "use": "Mystical aura"},
    "crystal_ball": {"price": 300, "desc": "For fortune telling and scrying", "type": "magic", "use": "See future"},
    "phoenix_feather": {"price": 1000, "desc": "Legendary feather with magic", "type": "magic", "use": "Rebirth chance"},
    # Tools
    "lantern": {"price": 8, "desc": "Light for dark dungeons", "type": "tool", "use": "Illuminates darkness"},
    "rope": {"price": 2, "desc": "Strong hemp rope, 50 feet", "type": "tool", "use": "Climbing aid"},
    "lockpicks": {"price": 20, "desc": "Tools for discreet entry", "type": "tool", "use": "Opens locks"},
    "spyglass": {"price": 35, "desc": "See distant lands and foes", "type": "tool", "use": "Long vision"},
    "map": {"price": 5, "desc": "Chart of surrounding lands", "type": "tool", "use": "Navigation aid"},
    # Luxuries
    "golden_goblet": {"price": 500, "desc": "Gilded cup for showing riches", "type": "luxury", "use": "Impression +5"},
    "silver_locket": {"price": 30, "desc": "Ornate locket with compartment", "type": "luxury", "use": "Stores secrets"},
    "royal_seal": {"price": 1000, "desc": "Official seal of kingdom", "type": "luxury", "use": "Authority symbol"},
    "chess_set": {"price": 15, "desc": "Royal game of strategy", "type": "luxury", "use": "Intelligence +3"},
    "silver_flute": {"price": 25, "desc": "Musical instrument for bards", "type": "luxury", "use": "Charisma +4"},
    # Companions & Mounts
    "hunting_hound": {"price": 50, "desc": "Loyal beast for the trail", "type": "companion", "use": "Tracking aid"},
    "falcon": {"price": 60, "desc": "Noble bird for hunting", "type": "companion", "use": "Scouting eyes"},
    "warhorse": {"price": 100, "desc": "Sturdy steed for battle", "type": "mount", "use": "Speed +10"},
    "pack_mule": {"price": 40, "desc": "Beast of burden for goods", "type": "mount", "use": "Carry capacity +50"},
    # Resources
    "iron_ore": {"price": 2, "desc": "Unrefined iron from mines", "type": "resource", "use": "Crafting material"},
    "herbs": {"price": 5, "desc": "Medicinal herbs for healing", "type": "resource", "use": "Potion ingredient"},
    "furs": {"price": 8, "desc": "Warm pelts from forest", "type": "resource", "use": "Clothing material"},
    "gemstones": {"price": 50, "desc": "Precious stones for trade", "type": "resource", "use": "High value trade"},
    # Titles
    "baron_title": {"price": 100000, "desc": "Noble title of Baron", "type": "title", "use": "Grants noble privileges"},
    "viscount_title": {"price": 700000, "desc": "Noble title of Viscount", "type": "title", "use": "Grants higher noble privileges"},
}
ITEMS_PER_PAGE = 8

# ---------- GUILD CONFIG FUNCTIONS ----------
def set_market_channel(guild_id, channel_id):
    with sqlite3.connect(DB_NAME) as db:
        db.execute("INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,))
        db.execute("UPDATE guild_config SET market_channel=? WHERE guild_id=?", (channel_id, guild_id))
        db.commit()

def get_market_channel(guild_id):
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT market_channel FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
        return row[0] if row else None

def set_title_role(guild_id, title, role_id):
    column = "baron_role" if title == "baron" else "viscount_role" if title == "viscount" else None
    if column:
        with sqlite3.connect(DB_NAME) as db:
            db.execute("INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,))
            db.execute(f"UPDATE guild_config SET {column}=? WHERE guild_id=?", (role_id, guild_id))
            db.commit()

def get_title_role(guild_id, title):
    column = "baron_role" if title == "baron" else "viscount_role" if title == "viscount" else None
    if column:
        with sqlite3.connect(DB_NAME) as db:
            row = db.execute(f"SELECT {column} FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
            return row[0] if row else None
    return None

def set_tax_roles(guild_id, role_ids):
    roles_str = ",".join(map(str, role_ids))
    with sqlite3.connect(DB_NAME) as db:
        db.execute("INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,))
        db.execute("UPDATE guild_config SET tax_roles=? WHERE guild_id=?", (roles_str, guild_id))
        db.commit()

def get_tax_roles(guild_id):
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT tax_roles FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
        return row[0] if row else None

def set_prison_role(guild_id, role_id):
    with sqlite3.connect(DB_NAME) as db:
        db.execute("INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,))
        db.execute("UPDATE guild_config SET prison_role=? WHERE guild_id=?", (role_id, guild_id))
        db.commit()

def get_prison_role(guild_id):
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT prison_role FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
        return row[0] if row else None

# ---------- DEBT & PRISON ----------
@tasks.loop(hours=24)
async def levy_debt_interest():
    with sqlite3.connect(DB_NAME) as db:
        rows = db.execute("SELECT user_id, debt FROM economy WHERE debt > 0").fetchall()
        for uid, debt in rows:
            new_debt = int(debt * (1 + DEBT_INTEREST_RATE))
            db.execute("UPDATE economy SET debt=? WHERE user_id=?", (new_debt, uid))
        db.commit()
    await check_prison_sentences()

async def check_prison_sentences():
    now = utcnow()
    with sqlite3.connect(DB_NAME) as db:
        rows = db.execute("SELECT user_id, debt_since FROM economy WHERE debt > 0 AND debt_since IS NOT NULL").fetchall()
        for uid, since_str in rows:
            try:
                since = dt.fromisoformat(since_str).replace(tzinfo=timezone.utc)
                if (now - since).days >= DAYS_BEFORE_PRISON:
                    for guild in bot.guilds:
                        member = guild.get_member(uid)
                        if not member:
                            continue
                        
                        # Get prison role from config or fallback to name
                        prison_role_id = get_prison_role(guild.id)
                        if prison_role_id:
                            role = guild.get_role(prison_role_id)
                        else:
                            role = discord.utils.get(guild.roles, name=PRISON_ROLE_NAME)
                            
                        if role and role not in member.roles:
                            try:
                                await member.add_roles(role)
                                market_chan_id = get_market_channel(guild.id)
                                if market_chan_id:
                                    chan = guild.get_channel(market_chan_id)
                                    if chan:
                                        await chan.send(
                                            f"⚖️ **Hear ye!** {member.display_name} hath been cast into debtor's prison "
                                            f"for failing to settle debts to the Crown!"
                                        )
                            except discord.Forbidden:
                                pass
            except ValueError:
                continue

@levy_debt_interest.before_loop
async def before_interest():
    await bot.wait_until_ready()

# ---------- DAILY TAX COLLECTION ----------
@tasks.loop(hours=24)
async def collect_royal_tax():
    for guild in bot.guilds:
        tax_roles_str = get_tax_roles(guild.id)
        if not tax_roles_str:
            continue
        tax_role_ids = [int(r) for r in tax_roles_str.split(',') if r]
        if not tax_role_ids:
            continue

        # Collect tax from all non-bot members
        total_tax = 0
        taxed_members = []
        for member in guild.members:
            if member.bot:
                continue
            gold_before = get_pouch(member.id)[0]
            add_coin(member.id, -DAILY_TAX)
            gold_after = get_pouch(member.id)[0]
            deducted = gold_before - gold_after
            total_tax += deducted
            if deducted > 0:
                taxed_members.append((member, deducted))

        # Find recipients
        recipients = [m for m in guild.members if any(r.id in tax_role_ids for r in m.roles)]
        if recipients:
            share = total_tax // len(recipients)
            remainder = total_tax % len(recipients)
            for i, recipient in enumerate(recipients):
                add_share = share + (1 if i < remainder else 0)
                add_coin(recipient.id, add_share)

            # Announce in market channel
            market_chan_id = get_market_channel(guild.id)
            if market_chan_id:
                chan = guild.get_channel(market_chan_id)
                if chan:
                    embed = medieval_embed(
                        title="🏰 Royal Tax Collection",
                        description=f"**{total_tax}** gold hath been collected and distributed amongst the nobles!",
                        color_name="gold"
                    )
                    if taxed_members:
                        taxed_list = "\n".join([f"• {m.display_name}: {g}g" for m, g in taxed_members[:10]])
                        if len(taxed_members) > 10:
                            taxed_list += f"\n• ...and {len(taxed_members) - 10} more"
                        embed.add_field(name="Taxed Subjects", value=taxed_list, inline=False)
                    
                    recipients_list = ", ".join([r.display_name for r in recipients[:5]])
                    if len(recipients) > 5:
                        recipients_list += f", and {len(recipients) - 5} more"
                    embed.add_field(name="Noble Recipients", value=recipients_list, inline=False)
                    
                    await chan.send(embed=embed)

@collect_royal_tax.before_loop
async def before_tax():
    await bot.wait_until_ready()

# ---------- SHOP VIEW ----------
class MarketView(discord.ui.View):
    def __init__(self, ctx, current_page=0, titles_only=False):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.current_page = current_page
        self.titles_only = titles_only
        items = {k: v for k, v in ROYAL_MARKET.items() if not titles_only or v.get("type") == "title"}
        self.total_pages = (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        prev_button = discord.ui.Button(emoji="◀️", style=discord.ButtonStyle.gray, disabled=self.current_page == 0)
        next_button = discord.ui.Button(emoji="▶️", style=discord.ButtonStyle.gray, disabled=self.current_page >= self.total_pages - 1)
        prev_button.callback = self.prev_callback
        next_button.callback = self.next_callback
        self.add_item(prev_button)
        self.add_item(next_button)

    async def prev_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("🚫 This market stall is not meant for thee, good sir!", ephemeral=True)
            return
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_page_embed(), view=self)

    async def next_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("🚫 This market stall is not meant for thee, fair maiden!", ephemeral=True)
            return
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_page_embed(), view=self)

    def get_page_embed(self):
        items = {k: v for k, v in ROYAL_MARKET.items() if not self.titles_only or v.get("type") == "title"}
        item_list = list(items.items())
        start_idx = self.current_page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = item_list[start_idx:end_idx]
        title = "🏪 Royal Titles Shop" if self.titles_only else f"🏪 Royal Marketplace - Page {self.current_page + 1} of {self.total_pages}"
        embed = medieval_embed(
            title=title,
            color_name="gold"
        )
        for item_key, data in page_items:
            price = data["price"]
            price_str = f"**{price}** gold"
            type_icons = {
                "weapon": "⚔️",
                "armor": "🛡️",
                "potion": "🧪",
                "magic": "🔮",
                "food": "🍞",
                "drink": "🍺",
                "tool": "🛠️",
                "luxury": "💎",
                "companion": "🐕",
                "mount": "🐎",
                "resource": "⛏️",
                "title": "👑"
            }
            icon = type_icons.get(data["type"], "📦")
            item_name = item_key.replace('_', ' ').title()
            embed.add_field(
                name=f"{icon} {item_name} - {price_str}",
                value=f"{data['desc']}\n*Use: {data['use']}*",
                inline=False
            )
        embed.set_footer(text=f"Use {PREFIX}buy <item_name> to purchase • {len(items)} total wares")
        embed.description = "**Noble titles and privileges!**" if self.titles_only else "**Fine wares from across the realm!**"
        return embed

# ---------- PREFIX COMMANDS ----------
@bot.command(name="help")
@commands.guild_only()
async def _help(ctx):
    embed = medieval_embed(
        title="📜 The Royal Charter of Commands",
        description=f"{medieval_greeting()}\n\nHere be the edicts and privileges granted by His Majesty:",
        color_name="purple"
    )
    cmds = {
        "labour": "Toil in the king's works for honest coin (once per hour)",
        "daily": f"Receive thy daily bounty from the royal coffers ({MAX_DAILY_GOLD} gold, once per day)",
        "market": "Peruse the wares of the grand marketplace",
        "titleshop": "Behold the exalted shop of noble titles",
        "buy": "Acquire goods or honours from the merchants",
        "pouch": "Examine the weight of thy purse",
        "sack": "Survey the contents of thy travelling sack",
        "use": "Employ an item from thine inventory",
        "pay": "Bestow coin upon another subject of the realm",
        "gamble • slots • coinflip": "Test thy fortune in games of chance",
        "paydebt": "Settle thy obligations to the Crown",
        "battle": "Challenge another to a duel of honour",
        "equip": "Arm thyself with weapon or armor",
        "use_potion": "Quaff a healing potion to mend wounds",
    }
    for name, desc in cmds.items():
        embed.add_field(name=f"**{PREFIX}{name}**", value=f"_{desc}_", inline=False)
    embed.add_field(
        name="⚖️ Laws of the Realm",
        value=(
            f"• Daily toil: once per hour\n"
            f"• Royal stipend: once per day\n"
            f"• A tax of {DAILY_TAX} gold is levied daily upon all subjects\n"
            f"• Debts accrue 2% interest each day\n"
            f"• Unpaid debt for {DAYS_BEFORE_PRISON} days leads to the debtor's prison"
        ),
        inline=False
    )
    embed.add_field(
        name="🔗 Slash Commands",
        value="All commands are also available as modern `/` commands!",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command(aliases=['work', 'toil'])
@commands.guild_only()
async def labour(ctx):
    cd = get_cooldown(ctx.author.id, "labour")
    if cd and utcnow() - cd < timedelta(hours=1):
        remain = timedelta(hours=1) - (utcnow() - cd)
        m = remain.seconds // 60
        s = remain.seconds % 60
        return await ctx.send(embed=medieval_response(
            f"Thou must rest thy weary bones! Return in **{m}** minutes and **{s}** seconds.",
            success=False
        ))
    jobs = {
        "mining": {
            "gold": (5, 20),
            "desc": "⛏️ Mining ore in the deep mines",
            "flair": ["The earth yielded its treasures!", "A rich vein was struck!", "The pickaxe rang true in the depths!"]
        },
        "farming": {
            "gold": (3, 10),
            "desc": "🌾 Tilling the royal fields",
            "flair": ["The harvest was bountiful!", "The soil yielded good crop!", "The fields were fertile this day!"]
        },
        "blacksmith": {
            "gold": (5, 15),
            "desc": "🔥 Forging at the royal smithy",
            "flair": ["The anvil sang with each strike!", "Steel was tempered to perfection!", "The forge burned bright and hot!"]
        },
        "carpentry": {
            "gold": (4, 12),
            "desc": "🪵 Crafting in the royal workshop",
            "flair": ["Wood was shaped with master skill!", "Joints were fitted without flaw!", "The saw made sweet music!"]
        },
        "merchant": {
            "gold": (6, 25),
            "desc": "💰 Trading in the market square",
            "flair": ["A shrewd bargain was struck!", "Goods changed hands profitably!", "The market favored thy trade!"]
        },
        "guard": {
            "gold": (4, 15),
            "desc": "🛡️ Standing watch on castle walls",
            "flair": ["The watch was uneventful but paid!", "No invaders this shift!", "The walls were well defended!"]
        }
    }
    job_name, job_data = random.choice(list(jobs.items()))
    gold = random.randint(job_data["gold"][0], job_data["gold"][1])
    add_coin(ctx.author.id, gold, ctx)
    set_cooldown(ctx.author.id, "labour")
    coin_str = f"**{gold}** gold piece{'s' if gold > 1 else ''}"
    flair = random.choice(job_data["flair"])
    embed = medieval_embed(
        title="🔨 Honest Labour",
        description=f"**{job_data['desc']}**\n\n{flair}\n\nThou hast earned: {coin_str}.",
        color_name="green"
    )
    if ctx.author.guild_permissions.administrator:
        g, _, _, hp = get_pouch(ctx.author.id, ctx)
        admin_status = f"👑 **Royal Administrator:** {g}/{CAP_GOLD} gold"
        embed.set_footer(text=admin_status)
    else:
        embed.set_footer(text="Return in one hour for more work at the royal works")
    await ctx.send(embed=embed)

@bot.command(aliases=['stipend', 'allowance'])
@commands.guild_only()
async def daily(ctx):
    """Claim thy daily royal stipend (24 hour cooldown, max 10g)"""
    cd = get_cooldown(ctx.author.id, "daily")
    if cd and utcnow() - cd < timedelta(days=1):
        remain = timedelta(days=1) - (utcnow() - cd)
        h = remain.seconds // 3600
        m = (remain.seconds % 3600) // 60
        return await ctx.send(embed=medieval_response(
            f"Thou hast already claimed today's stipend! Return in **{h}** hours and **{m}** minutes.",
            success=False
        ))
    # Daily reward - fixed at 10 gold maximum
    total_gold = MAX_DAILY_GOLD
    add_coin(ctx.author.id, total_gold, ctx)
    set_cooldown(ctx.author.id, "daily")
    daily_messages = [
        f"The Crown grants thee thy daily stipend!",
        f"Thy loyalty is rewarded with coin!",
        f"The royal treasury provides for its subjects!",
        f"A day's allowance for a loyal subject!",
    ]
    embed = medieval_embed(
        title="🏦 Daily Royal Stipend",
        description=f"{random.choice(daily_messages)}\n\nThou receivest: **{total_gold}** gold pieces.",
        color_name="green"
    )
    # Check admin status
    if ctx.author.guild_permissions.administrator:
        g, _, _, hp = get_pouch(ctx.author.id, ctx)
        admin_note = f"👑 **Royal Purse:** {g}/{CAP_GOLD} gold"
        embed.set_footer(text=admin_note)
    else:
        next_daily = utcnow() + timedelta(days=1)
        embed.set_footer(text=f"Next stipend: <t:{int(next_daily.timestamp())}:R> • Max: {MAX_DAILY_GOLD}g daily")
    await ctx.send(embed=embed)

@bot.command(aliases=['shop', 'wares'])
@commands.guild_only()
async def market(ctx):
    """Browse the royal marketplace wares"""
    view = MarketView(ctx)
    embed = view.get_page_embed()
    await ctx.send(embed=embed, view=view)

@bot.command(aliases=['titles', 'nobleshop'])
@commands.guild_only()
async def titleshop(ctx):
    """Browse the noble titles shop"""
    view = MarketView(ctx, titles_only=True)
    embed = view.get_page_embed()
    await ctx.send(embed=embed, view=view)

@bot.command(aliases=['purchase', 'acquire'])
@commands.guild_only()
async def buy(ctx, *, item_name: str):
    """Purchase an item from the market"""
    item_key = item_name.lower().replace(" ", "_")
    if item_key not in ROYAL_MARKET:
        # Try to find similar items
        similar = [i for i in ROYAL_MARKET.keys() if item_key in i or item_name.lower() in i.replace('_', ' ')]
        if similar:
            suggestion = random.choice(similar)
            embed = medieval_response(
                f"I know not of '{item_name}'. Didst thou mean **{suggestion.replace('_', ' ').title()}**?",
                success=False,
                extra=f"Use `{PREFIX}market` to browse all wares."
            )
        else:
            embed = medieval_response(
                f"No such ware as '{item_name}' exists in the royal market!",
                success=False,
                extra=f"Use `{PREFIX}market` to see what wares we offer."
            )
        return await ctx.send(embed=embed)
    
    item_data = ROYAL_MARKET[item_key]
    price = item_data["price"]
    
    # Check if user has enough gold
    g, debt, _, hp = get_pouch(ctx.author.id, ctx)
    if g < price:
        return await ctx.send(embed=medieval_response(
            f"Thou hast only **{g}** gold, but needest **{price}** for this purchase!",
            success=False
        ))
    
    # Make purchase
    add_coin(ctx.author.id, -price, ctx)
    if item_data.get("type") == "title":
        title = "baron" if "baron" in item_key else "viscount" if "viscount" in item_key else None
        if title:
            role_id = get_title_role(ctx.guild.id, title)
            if role_id:
                role = ctx.guild.get_role(role_id)
                if role:
                    await ctx.author.add_roles(role)
    else:
        add_item(ctx.author.id, item_key)
    
    # Success message
    item_display = item_key.replace('_', ' ').title()
    price_str = f"**{price}** gold"
    purchase_flairs = [
        f"A fine choice! The {item_display} is now thine!",
        f"Excellent purchase! The {item_display} shall serve thee well!",
        f"Thou hast acquired the {item_display}! May it bring thee fortune!",
        f"The {item_display} is wrapped and ready! A wise investment!",
        f"The merchant smiles! The {item_display} is thine for {price_str}!",
    ]
    embed = medieval_embed(
        title="🏪 Purchase Complete!",
        description=f"{random.choice(purchase_flairs)}\n\n**Item:** {item_display}\n**Cost:** {price_str}\n**Use:** {item_data['use']}",
        color_name="green"
    )
    # Show remaining balance
    g, debt, _, hp = get_pouch(ctx.author.id, ctx)
    balance_desc = f"**{g}** gold"
    embed.add_field(name="Remaining Purse", value=balance_desc, inline=False)
    embed.set_footer(text=f"Use {PREFIX}use {item_display.lower()} to employ thy new ware")
    await ctx.send(embed=embed)

@bot.command(aliases=['purse', 'coins', 'wealth'])
@commands.guild_only()
async def pouch(ctx, member: discord.Member = None):
    """Count the coin in thy purse"""
    member = member or ctx.author
    g, debt, debt_since, hp = get_pouch(member.id, ctx)
    # Coin descriptions
    coin_desc = f"**{g}** gold piece{'s' if g > 1 else ''}" if g > 0 else "**naught but dust and dreams**"
    embed = medieval_embed(
        title=f"💰 Purse of {member.display_name}",
        description=f"**Contents:** {coin_desc}\n**Vitality:** {hp}/{MAX_HP} ❤️",
        color_name="gold"
    )
    # Add debt information if applicable
    if debt > 0:
        embed.add_field(
            name="⚖️ Debt to the Crown",
            value=f"**{debt:,}** gold\n*Interest: {DEBT_INTEREST_RATE*100}% daily*\n*Prison in: {DAYS_BEFORE_PRISON} days unpaid*",
            inline=False
        )
        if debt_since:
            try:
                since = dt.fromisoformat(debt_since).replace(tzinfo=timezone.utc)
                days_in_debt = (utcnow() - since).days
                embed.add_field(
                    name="📅 Days in Debt",
                    value=f"**{days_in_debt}** day{'s' if days_in_debt != 1 else ''}",
                    inline=True
                )
            except ValueError:
                pass
    # Add wallet capacity
    capacity = f"**{g}/{CAP_GOLD}** gold"
    embed.add_field(name="📊 Purse Capacity", value=capacity, inline=False)
    # Show admin status if applicable
    if member.guild_permissions.administrator:
        embed.set_footer(text="👑 Royal Administrator • Purse fortified by 50%")
    else:
        embed.set_footer(text=f"Use {PREFIX}labour or {PREFIX}daily to earn coin")
    await ctx.send(embed=embed)

@bot.command(aliases=['inventory', 'possessions', 'bag'])
@commands.guild_only()
async def sack(ctx, member: discord.Member = None):
    """Check thy possessions and inventory"""
    member = member or ctx.author
    inventory = get_inventory(member.id)
    if not inventory:
        embed = medieval_response(
            "Thy sack is empty as a beggar's bowl!",
            success=False,
            extra=f"Visit the {PREFIX}market to purchase wares."
        )
        return await ctx.send(embed=embed)
    
    # Categorize items
    categories = {
        "⚔️ Weapons": {},
        "🛡️ Armor": {},
        "🔮 Magic": {},
        "🧪 Potions": {},
        "🍞 Provisions": {},
        "🛠️ Tools": {},
        "💎 Luxuries": {},
        "🐕 Companions": {},
        "⛏️ Resources": {},
        "👑 Titles": {},
        "📦 Miscellaneous": {}
    }
    
    # Initialize all categories first
    for item_key, qty in inventory.items():
        item_data = ROYAL_MARKET.get(item_key, {})
        item_type = item_data.get("type", "misc")
        item_name = item_key.replace('_', ' ').title()
        if item_type == "weapon":
            categories["⚔️ Weapons"][item_name] = qty
        elif item_type == "armor":
            categories["🛡️ Armor"][item_name] = qty
        elif item_type == "magic":
            categories["🔮 Magic"][item_name] = qty
        elif item_type == "potion":
            categories["🧪 Potions"][item_name] = qty
        elif item_type in ["food", "drink"]:
            categories["🍞 Provisions"][item_name] = qty
        elif item_type == "tool":
            categories["🛠️ Tools"][item_name] = qty
        elif item_type == "luxury":
            categories["💎 Luxuries"][item_name] = qty
        elif item_type in ["companion", "mount"]:
            categories["🐕 Companions"][item_name] = qty
        elif item_type == "resource":
            categories["⛏️ Resources"][item_name] = qty
        elif item_type == "title":
            categories["👑 Titles"][item_name] = qty
        else:
            categories["📦 Miscellaneous"][item_name] = qty
    
    total_items = sum(inventory.values())
    embed = medieval_embed(
        title=f"🎒 Sack of {member.display_name}",
        description=f"**Total Items:** {total_items}\n**Unique Wares:** {len(inventory)}",
        color_name="blue"
    )
    
    for category_name, items in categories.items():
        if items:
            items_list = "\n".join([f"• {k}: **{v}**" for k, v in items.items()])
            embed.add_field(name=category_name, value=items_list, inline=False)
    
    # Show equipped items
    equipped = get_equipped(member.id)
    if equipped:
        equipped_list = ", ".join([e.replace('_', ' ').title() for e in equipped])
        embed.add_field(name="⚔️ Equipped", value=equipped_list, inline=False)
    
    if member.guild_permissions.administrator:
        embed.set_footer(text="👑 Royal Administrator's Possessions")
    elif total_items > 20:
        embed.set_footer(text="A well-stocked adventurer indeed!")
    elif total_items > 10:
        embed.set_footer(text="Thy sack grows heavy with wares!")
    else:
        embed.set_footer(text="More room for treasures and trinkets!")
    
    await ctx.send(embed=embed)

@bot.command(aliases=['employ', 'consume', 'drink', 'eat'])
@commands.guild_only()
async def use(ctx, *, item_name: str):
    """Use an item from thy inventory"""
    item_key = item_name.lower().replace(" ", "_")
    if not has_item(ctx.author.id, item_key):
        embed = medieval_response(
            f"Thou dost not possess '{item_name}' in thy sack!",
            success=False,
            extra=f"Use {PREFIX}sack to check thy possessions."
        )
        return await ctx.send(embed=embed)
    
    item_data = ROYAL_MARKET.get(item_key, {})
    item_display = item_key.replace('_', ' ').title()
    
    # Different effects based on item type
    item_type = item_data.get("type", "misc")
    effect = item_data.get("use", "Mystical effect")
    
    # Handle specific item types
    if item_type == "potion" and "healing" in item_key:
        # Healing potion
        heal_amount = item_data.get("heal", 30)
        new_hp = update_hp(ctx.author.id, heal_amount)
        effect = f"Restores **{heal_amount}** HP! Thy vitality is now {new_hp}/{MAX_HP}"
    
    use_messages = {
        "food": [
            f"Thou consumest the {item_display}. {effect}!",
            f"The {item_display} fills thy belly. {effect}!",
            f"Thou feastest upon the {item_display}. {effect}!",
        ],
        "drink": [
            f"Thou drinkest the {item_display}. {effect}!",
            f"The {item_display} quenches thy thirst. {effect}!",
            f"Thou raisest the {item_display} in toast. {effect}!",
        ],
        "potion": [
            f"Thou drinkest the {item_display}. {effect}!",
            f"The {item_display} takes effect. {effect}!",
            f"Thou consumest the mystical {item_display}. {effect}!",
        ],
        "weapon": [
            f"Thou wieldest the {item_display}. {effect}!",
            f"The {item_display} feels balanced in thy hand. {effect}!",
            f"Thou brandishest the {item_display}. {effect}!",
        ],
        "armor": [
            f"Thou donnest the {item_display}. {effect}!",
            f"The {item_display} protects thee. {effect}!",
            f"Thou equippest the protective {item_display}. {effect}!",
        ],
        "magic": [
            f"Thou channelest the {item_display}'s power. {effect}!",
            f"The {item_display} glows with energy. {effect}!",
            f"Thou employest the magical {item_display}. {effect}!",
        ],
        "tool": [
            f"Thou usest the {item_display}. {effect}!",
            f"The {item_display} serves thee well. {effect}!",
            f"Thou employest the practical {item_display}. {effect}!",
        ],
        "title": [
            f"Thou assumest the {item_display}. {effect}!",
            f"The {item_display} elevates thy status. {effect}!",
        ]
    }
    
    # Get appropriate message
    messages = use_messages.get(item_type, [f"Thou usest the {item_display}. {effect}!"])
    message = random.choice(messages)
    
    # Remove item after use (for consumables)
    if item_type in ["food", "drink", "potion"]:
        remove_item(ctx.author.id, item_key, 1)
        message += "\n\n*The item is consumed.*"
    
    embed = medieval_embed(
        title=f"✨ Using {item_display}",
        description=message,
        color_name="purple"
    )
    
    if item_type in ["food", "drink", "potion"]:
        # Check remaining quantity
        remaining = get_inventory(ctx.author.id).get(item_key, 0)
        if remaining > 0:
            embed.add_field(name="Remaining", value=f"**{remaining}** left in thy sack", inline=False)
        else:
            embed.set_footer(text="Thou hast no more of this item")
    
    await ctx.send(embed=embed)

@bot.command()
@commands.guild_only()
async def equip(ctx, *, item_name: str):
    """Equip a weapon or armor"""
    item_key = item_name.lower().replace(" ", "_")
    if not has_item(ctx.author.id, item_key):
        embed = medieval_response(
            f"Thou dost not possess '{item_name}'!",
            success=False,
            extra=f"Use {PREFIX}sack to check thy possessions."
        )
        return await ctx.send(embed=embed)
    
    if equip_item(ctx.author.id, item_key):
        item_display = item_key.replace('_', ' ').title()
        embed = medieval_embed(
            title="⚔️ Item Equipped",
            description=f"Thou hast equipped the **{item_display}**!",
            color_name="green"
        )
    else:
        embed = medieval_response(
            f"Thou canst only equip weapons or armor!",
            success=False
        )
    
    await ctx.send(embed=embed)

@bot.command()
@commands.guild_only()
async def unequip(ctx, *, item_name: str):
    """Unequip a weapon or armor"""
    item_key = item_name.lower().replace(" ", "_")
    
    with sqlite3.connect(DB_NAME) as db:
        db.execute("UPDATE inventory SET equipped=0 WHERE user_id=? AND item=?", (ctx.author.id, item_key))
        db.commit()
    
    item_display = item_key.replace('_', ' ').title()
    embed = medieval_embed(
        title="⚔️ Item Unequipped",
        description=f"Thou hast unequipped the **{item_display}**!",
        color_name="blue"
    )
    await ctx.send(embed=embed)

# ---------- PAY COMMAND ----------
@bot.command(aliases=['send', 'give', 'transfer'])
@commands.guild_only()
async def pay(ctx, member: discord.Member, amount: str, *, note: str = ""):
    """Send coin to another soul"""
    if member == ctx.author:
        embed = medieval_response(
            "Thou cannot pay coin to thyself! That would be wizardry!",
            success=False
        )
        return await ctx.send(embed=embed)
    if member.bot:
        embed = medieval_response(
            "Thou cannot pay coin to automatons or spirits!",
            success=False
        )
        return await ctx.send(embed=embed)
    try:
        # Parse amount
        if amount.lower() in ["all", "max"]:
            g, debt, _, hp = get_pouch(ctx.author.id, ctx)
            amount_gold = g
            amount_desc = "all thy gold"
        else:
            amount_gold = int(amount)
            amount_desc = f"**{amount_gold}** gold"
        if amount_gold <= 0:
            return await ctx.send(embed=medieval_response(
                "Thou must send a positive amount of coin!",
                success=False
            ))
        if amount_gold > get_pouch(ctx.author.id, ctx)[0]:
            return await ctx.send(embed=medieval_response(
                f"Thou hast not enough gold for this payment!",
                success=False
            ))
        # Make the payment - remove from sender
        add_coin(ctx.author.id, -amount_gold, ctx)
        # Add to receiver
        add_coin(member.id, amount_gold, ctx)
        # Create response
        payment_messages = [
            f"Thou hast paid {amount_desc} to {member.display_name}!",
            f"{amount_desc} changes hands from thee to {member.display_name}!",
            f"Thou transferrest {amount_desc} to {member.display_name}'s purse!",
            f"The coin hath been sent! {amount_desc} to {member.display_name}!",
        ]
        embed = medieval_embed(
            title="💰 Royal Payment",
            description=f"{random.choice(payment_messages)}",
            color_name="green"
        )
        if note:
            embed.add_field(name="📝 Note", value=note, inline=False)
        # Show sender's remaining balance
        g, debt, _, hp = get_pouch(ctx.author.id, ctx)
        remaining_desc = f"**{g}** gold"
        embed.add_field(name="Thy Remaining Purse", value=remaining_desc, inline=False)
        # Check if receiver is admin
        if member.guild_permissions.administrator:
            embed.set_footer(text=f"👑 Paid to Royal Administrator • {member.display_name}")
        else:
            embed.set_footer(text=f"Payment recorded in royal ledgers")
        await ctx.send(embed=embed)
        # Send DM to receiver if possible
        try:
            dm_embed = medieval_embed(
                title="💰 Coin Received!",
                description=f"**{ctx.author.display_name}** hath paid thee {amount_desc} in **{ctx.guild.name}**!",
                color_name="green"
            )
            if note:
                dm_embed.add_field(name="📝 Note", value=note, inline=False)
            await member.send(embed=dm_embed)
        except:
            pass # Cannot send DM, but that's okay
    except ValueError:
        embed = medieval_response(
            "Prithee, enter a valid amount or 'all' for thy payment.",
            success=False
        )
        await ctx.send(embed=embed)

# ---------- GAMBLING COMMANDS ----------
@bot.command(aliases=['dice', 'wager'])
@commands.guild_only()
async def gamble(ctx, wager: str = "10"):
    """Wager coin at the dice game (no cooldown)"""
    try:
        # Parse wager
        if wager.lower() in ["all", "max"]:
            g, debt, _, hp = get_pouch(ctx.author.id, ctx)
            wager_amount = g
            wager_desc = "all thy gold"
        else:
            wager_amount = int(wager)
            wager_desc = f"**{wager_amount}** gold"
        if wager_amount <= 0:
            return await ctx.send(embed=medieval_response(
                "Thou must wager a positive amount of coin, good sir!",
                success=False
            ))
        if wager_amount > get_pouch(ctx.author.id, ctx)[0]:
            return await ctx.send(embed=medieval_response(
                f"Thou hast not enough gold for this wager!",
                success=False
            ))
        # Roll the dice with medieval flair
        player_roll = random.randint(1, 12)
        house_roll = random.randint(1, 12)
        dice_names = {
            1: "The Snake Eyes", 2: "The Deuce", 3: "The Trey", 4: "The Square",
            5: "The Cinque", 6: "The Six", 7: "The Seven", 8: "The Eight",
            9: "The Nine", 10: "The Ten", 11: "The Eleven", 12: "The Dozen"
        }
        player_name = dice_names.get(player_roll, f"The {player_roll}")
        house_name = dice_names.get(house_roll, f"The {house_roll}")
        if player_roll > house_roll:
            outcome = "VICTORY! 🏆"
            result_desc = f"Thy **{player_name}** bested the house's **{house_name}**!"
            add_coin(ctx.author.id, wager_amount, ctx)
            color = "green"
            win_lose = f"Thou gainest **{wager_amount}** gold!"
            flair = random.choice([
                "The dice favor the bold!",
                "Fortune smiles upon thee!",
                "A most excellent roll!",
                "Thy luck holds strong!",
            ])
        elif player_roll < house_roll:
            outcome = "DEFEAT! 💀"
            result_desc = f"The house's **{house_name}** bested thy **{player_name}**!"
            add_coin(ctx.author.id, -wager_amount, ctx)
            color = "red"
            win_lose = f"Thou losest **{wager_amount}** gold."
            flair = random.choice([
                "The fickle finger of fate points elsewhere!",
                "Better luck next time, good sir!",
                "The dice have betrayed thee!",
                "Fortune is a cruel mistress this day!",
            ])
        else:
            outcome = "A STANDOFF! 🤝"
            result_desc = f"Both rolled **{player_name}**! A rare occurrence!"
            color = "gold"
            win_lose = "Thy coin is returned unto thee."
            flair = "The dice show neither favor nor disdain!"
        embed = medieval_embed(
            title=f"🎲 {outcome}",
            description=f"**{result_desc}**\n\n{flair}\n\n{win_lose}",
            color_name=color
        )
        embed.add_field(name="Thy Roll", value=f"**{player_roll}** - {player_name}", inline=True)
        embed.add_field(name="House Roll", value=f"**{house_roll}** - {house_name}", inline=True)
        embed.add_field(name="Wager", value=wager_desc, inline=False)
    except ValueError:
        embed = medieval_response(
            "Prithee, enter a valid number, 'all', or 'max' for thy wager.",
            success=False
        )
    await ctx.send(embed=embed)

@bot.command(aliases=['machines', 'fortunewheel'])
@commands.guild_only()
async def slots(ctx):
    """Try thy luck at the royal slots (no cooldown)"""
    cost = 1
    if get_pouch(ctx.author.id, ctx)[0] < cost:
        return await ctx.send(embed=medieval_response(
            f"Thou needest at least **{cost}** gold to play the slots!",
            success=False
        ))
    
    add_coin(ctx.author.id, -cost, ctx)
    symbols = ["🍒", "⭐", "🔔", "👑", "💎", "⚔️", "🛡️", "🐉", "⚜️", "🏰"]
    slot1 = random.choice(symbols)
    slot2 = random.choice(symbols)
    slot3 = random.choice(symbols)
    result = f"**[ {slot1} | {slot2} | {slot3} ]**"
    # Medieval slot outcomes
    if slot1 == slot2 == slot3:
        if slot1 == "💎":
            win = 40
            msg = "**JACKPOT! DIAMONDS OF LEGEND!** 💎"
            flavor = "The gods of fortune shower thee with riches!"
        elif slot1 == "👑":
            win = 20
            msg = "**ROYAL FLUSH!** 👑"
            flavor = "A king's ransom is thine!"
        elif slot1 == "🐉":
            win = 30
            msg = "**DRAGON'S HOARD!** 🐉"
            flavor = "Thou hast found a dragon's treasure trove!"
        elif slot1 == "🏰":
            win = 16
            msg = "**CASTLE FORTUNE!** 🏰"
            flavor = "The castle treasury opens for thee!"
        else:
            win = 8
            msg = "**THREE OF A KIND!**"
            flavor = "A most fortunate alignment of symbols!"
    elif slot1 == slot2 or slot2 == slot3 or slot1 == slot3:
        win = 2
        msg = "**PAIR WIN!**"
        flavor = "Not the grand prize, but coin nonetheless!"
    else:
        win = 0
        msg = "**NO WIN**"
        flavor = "Fortune favors not the bold this day..."
    if win > 0:
        add_coin(ctx.author.id, win, ctx)
        color = "green"
        result_msg = f"**{msg}**\n{flavor}\n\nThou hast won **{win}** gold!"
    else:
        color = "red"
        result_msg = f"**{msg}**\n{flavor}\n\nThou hast lost **{cost}** gold."
    embed = medieval_embed(
        title="🎰 Royal Slot Machine",
        description=f"**{result}**\n\n{result_msg}",
        color_name=color
    )
    if win >= 20:
        embed.set_footer(text="🎉 A truly legendary win!")
    elif win > 0:
        embed.set_footer(text="🎊 Fortune smiles upon thee!")
    await ctx.send(embed=embed)

@bot.command(aliases=['headsails', 'bet'])
@commands.guild_only()
async def coinflip(ctx, choice: str = "", wager: str = "10"):
    """Heads or tails bet with fortune (no cooldown)"""
    if choice.lower() not in ["heads", "tails", "h", "t"]:
        embed = medieval_embed(
            title="🪙 Royal Coin Flip",
            description=f"**Usage:** `{PREFIX}coinflip <heads/tails> [wager]`\n\n**Examples:**\n`{PREFIX}coinflip heads 50`\n`{PREFIX}coinflip tails max`\n`{PREFIX}coinflip h all`",
            color_name="orange"
        )
        embed.set_footer(text="Heads bears the King's likeness, tails the Royal Crest")
        return await ctx.send(embed=embed)
    try:
        if wager.lower() in ["all", "max"]:
            g, debt, _, hp = get_pouch(ctx.author.id, ctx)
            wager_amount = g
            wager_desc = "all thy gold"
        else:
            wager_amount = int(wager)
            wager_desc = f"**{wager_amount}** gold"
        if wager_amount <= 0:
            return await ctx.send(embed=medieval_response(
                "A wager must be positive coin, good sirrah!",
                success=False
            ))
        if wager_amount > get_pouch(ctx.author.id, ctx)[0]:
            return await ctx.send(embed=medieval_response(
                f"Thou hast not enough gold for this wager!",
                success=False
            ))
        # Convert short forms
        if choice.lower() in ["h", "heads"]:
            player_choice = "heads"
            choice_desc = "**Heads** (the King's likeness)"
        else:
            player_choice = "tails"
            choice_desc = "**Tails** (the Royal Crest)"
        result = random.choice(["heads", "tails"])
        result_desc = "**Heads** (the King's likeness)" if result == "heads" else "**Tails** (the Royal Crest)"
        # Medieval coin flip descriptions
        if player_choice == result:
            outcome = "VICTORY! 🏆"
            result_text = f"Thou guessed correctly, noble sir!"
            add_coin(ctx.author.id, wager_amount, ctx)
            color = "green"
            win_lose = f"Thou gainest **{wager_amount}** gold!"
            flair = random.choice([
                "The King smiles upon thee!",
                "Fortune favors the bold!",
                "A most excellent guess!",
                "Thy wisdom in gambling shows!",
            ])
        else:
            outcome = "DEFEAT! 💀"
            result_text = f"Alas, thy guess was wrong!"
            add_coin(ctx.author.id, -wager_amount, ctx)
            color = "red"
            win_lose = f"Thou losest **{wager_amount}** gold."
            flair = random.choice([
                "The fickle finger of fate points elsewhere!",
                "Better luck next time, good sir!",
                "The coin hath betrayed thee!",
                "Fortune is a cruel mistress this day!",
            ])
        embed = medieval_embed(
            title=f"🪙 {outcome}",
            description=f"**{result_text}**\n\n{flair}\n\n{win_lose}",
            color_name=color
        )
        embed.add_field(name="Thy Choice", value=choice_desc, inline=True)
        embed.add_field(name="Coin Landed", value=result_desc, inline=True)
        embed.add_field(name="Wager", value=wager_desc, inline=False)
    except ValueError:
        embed = medieval_response(
            "Prithee, enter a valid number, 'all', or 'max' for thy wager.",
            success=False
        )
    await ctx.send(embed=embed)

@bot.command(aliases=['repay', 'settle'])
@commands.guild_only()
async def paydebt(ctx, amount: str = "all"):
    """Repay debt to the Crown (no cooldown)"""
    g, debt, _, hp = get_pouch(ctx.author.id, ctx)
    if debt <= 0:
        return await ctx.send(embed=medieval_response(
            "Thou hast no debt to the Crown! Thy ledger is clean.",
            success=True
        ))
    try:
        if amount.lower() in ["all", "max"]:
            pay_amount = min(debt, g)
        else:
            pay_amount = int(amount)
        if pay_amount <= 0:
            return await ctx.send(embed=medieval_response(
                "Thou must pay a positive amount to settle thy debt!",
                success=False
            ))
        if pay_amount > g:
            return await ctx.send(embed=medieval_response(
                f"Thou hast only **{g}** gold, but wishest to pay **{pay_amount}**!",
                success=False
            ))
        if pay_amount > debt:
            pay_amount = debt
        # Pay the debt
        add_coin(ctx.author.id, -pay_amount, ctx)
        new_debt = debt - pay_amount
        set_debt(ctx.author.id, new_debt)
        if new_debt <= 0:
            message = f"Thy debt to the Crown is fully settled! Thou art free of obligation!"
            extra = "The royal scribe stamps thy ledger CLEAR."
        else:
            message = f"Thou hast paid **{pay_amount}** gold toward thy debt!"
            extra = f"Remaining debt: **{new_debt}** gold"
        embed = medieval_response(message, success=True, extra=extra)
        # Check if user was in prison and should be released
        if new_debt <= 0:
            for guild in bot.guilds:
                member = guild.get_member(ctx.author.id)
                if member:
                    prison_role_id = get_prison_role(guild.id)
                    if prison_role_id:
                        role = guild.get_role(prison_role_id)
                    else:
                        role = discord.utils.get(guild.roles, name=PRISON_ROLE_NAME)
                    
                    if role and role in member.roles:
                        try:
                            await member.remove_roles(role)
                            market_chan_id = get_market_channel(guild.id)
                            if market_chan_id:
                                chan = guild.get_channel(market_chan_id)
                                if chan:
                                    await chan.send(
                                        f"🏰 **Hear ye!** {member.display_name} hath settled all debts "
                                        f"and is released from debtor's prison!"
                                    )
                        except discord.Forbidden:
                            pass
    except ValueError:
        embed = medieval_response(
            "Prithee, enter a valid number or 'all' to pay thy debt.",
            success=False
        )
    await ctx.send(embed=embed)

# ---------- ADMIN COMMANDS ----------
@bot.command(aliases=['setmarkethall'])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def setmarket(ctx, channel: discord.TextChannel):
    """Set the market announcement hall"""
    set_market_channel(ctx.guild.id, channel.id)
    embed = medieval_response(
        f"The royal market announcements shall now echo in {channel.mention}!",
        success=True
    )
    await ctx.send(embed=embed)

@bot.command(aliases=['settitle'])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def ntset(ctx, title: str, role: discord.Role):
    """Set noble title role (Admin)"""
    title_lower = title.lower()
    if title_lower not in ["baron", "viscount"]:
        embed = medieval_response("Invalid title! Use 'baron' or 'viscount'.", success=False)
        return await ctx.send(embed=embed)
    set_title_role(ctx.guild.id, title_lower, role.id)
    embed = medieval_response(f"The {title} title role set to {role.mention}!", success=True)
    await ctx.send(embed=embed)

@bot.command(aliases=['settaxroles'])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def taxrset(ctx, *roles: discord.Role):
    """Set tax recipient roles (Admin)"""
    if not roles:
        embed = medieval_response("Thou must specify at least one role!", success=False)
        return await ctx.send(embed=embed)
    role_ids = [r.id for r in roles]
    set_tax_roles(ctx.guild.id, role_ids)
    role_mentions = " ".join(r.mention for r in roles)
    embed = medieval_response(f"Tax recipients set to: {role_mentions}!", success=True)
    await ctx.send(embed=embed)

@bot.command(aliases=['setprison'])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def prisonrole(ctx, role: discord.Role):
    """Set prison role for debtors (Admin)"""
    set_prison_role(ctx.guild.id, role.id)
    embed = medieval_response(f"Prison role set to {role.mention}!", success=True)
    await ctx.send(embed=embed)

@bot.command(aliases=['collect', 'seize', 'confiscate'])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def take(ctx, member: discord.Member, amount: str, *, reason: str = ""):
    """Take coin from another soul (Admin only)"""
    try:
        # Parse amount
        if amount.lower() in ["all", "max"]:
            g, debt, _, hp = get_pouch(member.id, ctx)
            amount_gold = g
            amount_desc = "all their gold"
        else:
            amount_gold = int(amount)
            amount_desc = f"**{amount_gold}** gold"
        if amount_gold <= 0:
            return await ctx.send(embed=medieval_response(
                "Thou must take a positive amount of coin!",
                success=False
            ))
        # Take the coin - remove from target
        add_coin(member.id, -amount_gold, ctx)
        # Optional: Add to treasury or keep it
        # For now, just remove it from circulation
        # Create response
        take_messages = [
            f"Thou hast taken {amount_desc} from {member.display_name}!",
            f"The royal tax collector hath seized {amount_desc} from {member.display_name}!",
            f"{amount_desc} confiscated from {member.display_name} by royal decree!",
            f"The Crown claims {amount_desc} from {member.display_name}!",
        ]
        embed = medieval_embed(
            title="⚖️ Royal Collection",
            description=f"{random.choice(take_messages)}",
            color_name="orange"
        )
        if reason:
            embed.add_field(name="📜 Reason", value=reason, inline=False)
        # Show target's remaining balance
        g, debt, _, hp = get_pouch(member.id, ctx)
        remaining_desc = f"**{g}** gold" if g > 0 else "**Empty**"
        embed.add_field(name="Their Remaining Purse", value=remaining_desc, inline=False)
        embed.set_footer(text=f"👑 Royal Authority exercised by {ctx.author.display_name}")
        await ctx.send(embed=embed)
    except ValueError as e:
        embed = medieval_response(
            "Prithee, enter a valid amount or 'all' for the collection.",
            success=False
        )
        await ctx.send(embed=embed)

# ---------- SLASH COMMANDS ----------
@tree.command(name="help", description="View the royal charter of commands")
@app_commands.guild_only
async def slash_help(interaction: discord.Interaction):
    embed = medieval_embed(
        title="📜 The Royal Charter of Commands",
        description=f"{medieval_greeting()}\n\nHere be the edicts and privileges granted by His Majesty:",
        color_name="purple"
    )
    cmds = {
        "labour": "Toil in the king's works for honest coin (once per hour)",
        "daily": f"Receive thy daily bounty from the royal coffers ({MAX_DAILY_GOLD} gold, once per day)",
        "market": "Peruse the wares of the grand marketplace",
        "titleshop": "Behold the exalted shop of noble titles",
        "buy": "Acquire goods or honours from the merchants",
        "pouch": "Examine the weight of thy purse",
        "sack": "Survey the contents of thy travelling sack",
        "use": "Employ an item from thine inventory",
        "pay": "Bestow coin upon another subject of the realm",
        "gamble": "Wager coin at the dice game",
        "slots": "Try thy luck at the royal slots",
        "coinflip": "Heads or tails bet with fortune",
        "paydebt": "Settle thy obligations to the Crown",
        "equip": "Arm thyself with weapon or armor",
        "unequip": "Remove equipment",
    }
    for name, desc in cmds.items():
        embed.add_field(name=f"**/{name}**", value=f"_{desc}_", inline=False)
    embed.add_field(
        name="⚖️ Laws of the Realm",
        value=(
            f"• Daily toil: once per hour\n"
            f"• Royal stipend: once per day\n"
            f"• A tax of {DAILY_TAX} gold is levied daily upon all subjects\n"
            f"• Debts accrue 2% interest each day\n"
            f"• Unpaid debt for {DAYS_BEFORE_PRISON} days leads to the debtor's prison"
        ),
        inline=False
    )
    await interaction.response.send_message(embed=embed)

@tree.command(name="labour", description="Toil in the king's works for honest coin (once per hour)")
@app_commands.guild_only
async def slash_labour(interaction: discord.Interaction):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await labour(ctx)

@tree.command(name="daily", description="Receive thy daily bounty from the royal coffers")
@app_commands.guild_only
async def slash_daily(interaction: discord.Interaction):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await daily(ctx)

@tree.command(name="market", description="Peruse the wares of the grand marketplace")
@app_commands.guild_only
async def slash_market(interaction: discord.Interaction):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await market(ctx)

@tree.command(name="titleshop", description="Behold the exalted shop of noble titles")
@app_commands.guild_only
async def slash_titleshop(interaction: discord.Interaction):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await titleshop(ctx)

@tree.command(name="buy", description="Acquire goods or honours from the merchants")
@app_commands.describe(item="The item to purchase")
@app_commands.guild_only
async def slash_buy(interaction: discord.Interaction, item: str):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await buy(ctx, item_name=item)

@tree.command(name="pouch", description="Examine the weight of thy purse")
@app_commands.describe(member="The member to check (optional)")
@app_commands.guild_only
async def slash_pouch(interaction: discord.Interaction, member: discord.Member = None):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await pouch(ctx, member=member)

@tree.command(name="sack", description="Survey the contents of thy travelling sack")
@app_commands.describe(member="The member to check (optional)")
@app_commands.guild_only
async def slash_sack(interaction: discord.Interaction, member: discord.Member = None):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await sack(ctx, member=member)

@tree.command(name="use", description="Employ an item from thine inventory")
@app_commands.describe(item="The item to use")
@app_commands.guild_only
async def slash_use(interaction: discord.Interaction, item: str):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await use(ctx, item_name=item)

@tree.command(name="equip", description="Arm thyself with weapon or armor")
@app_commands.describe(item="The item to equip")
@app_commands.guild_only
async def slash_equip(interaction: discord.Interaction, item: str):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await equip(ctx, item_name=item)

@tree.command(name="unequip", description="Remove equipment")
@app_commands.describe(item="The item to unequip")
@app_commands.guild_only
async def slash_unequip(interaction: discord.Interaction, item: str):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await unequip(ctx, item_name=item)

@tree.command(name="pay", description="Bestow coin upon another subject of the realm")
@app_commands.describe(member="The member to pay", amount="Amount to pay (number or 'all')", note="Optional note")
@app_commands.guild_only
async def slash_pay(interaction: discord.Interaction, member: discord.Member, amount: str, note: str = ""):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await pay(ctx, member=member, amount=amount, note=note)

@tree.command(name="gamble", description="Wager coin at the dice game")
@app_commands.describe(wager="Amount to wager (number or 'all')")
@app_commands.guild_only
async def slash_gamble(interaction: discord.Interaction, wager: str = "10"):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await gamble(ctx, wager=wager)

@tree.command(name="slots", description="Try thy luck at the royal slots")
@app_commands.guild_only
async def slash_slots(interaction: discord.Interaction):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await slots(ctx)

@tree.command(name="coinflip", description="Heads or tails bet with fortune")
@app_commands.describe(choice="Heads or tails", wager="Amount to wager (number or 'all')")
@app_commands.choices(choice=[
    app_commands.Choice(name="Heads", value="heads"),
    app_commands.Choice(name="Tails", value="tails")
])
@app_commands.guild_only
async def slash_coinflip(interaction: discord.Interaction, choice: app_commands.Choice[str], wager: str = "10"):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await coinflip(ctx, choice=choice.value, wager=wager)

@tree.command(name="paydebt", description="Settle thy obligations to the Crown")
@app_commands.describe(amount="Amount to pay (number or 'all')")
@app_commands.guild_only
async def slash_paydebt(interaction: discord.Interaction, amount: str = "all"):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await paydebt(ctx, amount=amount)

# ---------- ADMIN SLASH COMMANDS ----------
@tree.command(name="setmarket", description="Set the market announcement hall (Admin)")
@app_commands.describe(channel="The channel for market announcements")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only
async def slash_setmarket(interaction: discord.Interaction, channel: discord.TextChannel):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await setmarket(ctx, channel=channel)

@tree.command(name="ntset", description="Set noble title role (Admin)")
@app_commands.describe(title="The title (baron or viscount)", role="The role to assign")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only
async def slash_ntset(interaction: discord.Interaction, title: str, role: discord.Role):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await ntset(ctx, title=title, role=role)

@tree.command(name="taxrset", description="Set tax recipient roles (Admin)")
@app_commands.describe(roles="The roles to receive taxes")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only
async def slash_taxrset(interaction: discord.Interaction, roles: str):
    # Parse role mentions
    role_objects = []
    for role_id in roles.split():
        if role_id.startswith('<@&') and role_id.endswith('>'):
            role_id = int(role_id[3:-1])
            role = interaction.guild.get_role(role_id)
            if role:
                role_objects.append(role)
    
    if not role_objects:
        await interaction.response.send_message("No valid roles found!", ephemeral=True)
        return
    
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await taxrset(ctx, *role_objects)

@tree.command(name="prisonrole", description="Set prison role for debtors (Admin)")
@app_commands.describe(role="The prison role")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only
async def slash_prisonrole(interaction: discord.Interaction, role: discord.Role):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await prisonrole(ctx, role=role)

@tree.command(name="take", description="Take coin from another soul (Admin only)")
@app_commands.describe(member="The member to take from", amount="Amount to take (number or 'all')", reason="Reason for taking (optional)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only
async def slash_take(interaction: discord.Interaction, member: discord.Member, amount: str, reason: str = ""):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await take(ctx, member=member, amount=amount, reason=reason)

# ---------- BATTLE COMMAND (Basic Implementation) ----------
@bot.command()
@commands.guild_only()
async def battle(ctx, opponent: discord.Member):
    """Challenge another to a duel of honour"""
    if opponent == ctx.author:
        embed = medieval_response("Thou cannot battle thyself!", success=False)
        return await ctx.send(embed=embed)
    if opponent.bot:
        embed = medieval_response("Thou cannot battle automatons!", success=False)
        return await ctx.send(embed=embed)
    
    # Check cooldown
    cd = get_cooldown(ctx.author.id, "battle")
    if cd and utcnow() - cd < timedelta(hours=1):
        remain = timedelta(hours=1) - (utcnow() - cd)
        m = remain.seconds // 60
        s = remain.seconds % 60
        embed = medieval_response(f"Thou must rest between battles! Return in **{m}** minutes and **{s}** seconds.", success=False)
        return await ctx.send(embed=embed)
    
    # Get HP and equipment
    p1_gold, p1_debt, _, p1_hp = get_pouch(ctx.author.id, ctx)
    p2_gold, p2_debt, _, p2_hp = get_pouch(opponent.id, ctx)
    
    # Calculate bonuses from equipment
    p1_atk_bonus = 0
    p1_def_bonus = 0
    p2_atk_bonus = 0
    p2_def_bonus = 0
    
    for item in get_equipped(ctx.author.id):
        item_data = ROYAL_MARKET.get(item, {})
        p1_atk_bonus += item_data.get("atk_bonus", 0)
        p1_def_bonus += item_data.get("def_bonus", 0)
    
    for item in get_equipped(opponent.id):
        item_data = ROYAL_MARKET.get(item, {})
        p2_atk_bonus += item_data.get("atk_bonus", 0)
        p2_def_bonus += item_data.get("def_bonus", 0)
    
    # Battle calculation
    p1_roll = random.randint(1, 20) + p1_atk_bonus
    p2_roll = random.randint(1, 20) + p2_atk_bonus
    
    # Apply defense
    p1_damage = max(1, p2_roll - p1_def_bonus)
    p2_damage = max(1, p1_roll - p2_def_bonus)
    
    # Update HP
    new_p1_hp = update_hp(ctx.author.id, -p1_damage)
    new_p2_hp = update_hp(opponent.id, -p2_damage)
    
    # Determine winner
    if new_p1_hp <= 0 and new_p2_hp <= 0:
        winner = None
        result = "A DRAW! Both warriors fall! ⚔️"
        reward = 0
    elif new_p1_hp <= 0:
        winner = opponent
        result = f"**{opponent.display_name}** VICTORIOUS! 🏆"
        reward = min(50, p1_gold // 10)
        if reward > 0:
            add_coin(opponent.id, reward)
            add_coin(ctx.author.id, -reward)
    elif new_p2_hp <= 0:
        winner = ctx.author
        result = f"**{ctx.author.display_name}** VICTORIOUS! 🏆"
        reward = min(50, p2_gold // 10)
        if reward > 0:
            add_coin(ctx.author.id, reward)
            add_coin(opponent.id, -reward)
    else:
        winner = ctx.author if p1_roll > p2_roll else opponent if p2_roll > p1_roll else None
        result = "The battle continues! ⚔️"
        reward = 0
    
    # Create embed
    embed = medieval_embed(
        title="⚔️ Royal Duel",
        description=f"**{ctx.author.display_name}** challenges **{opponent.display_name}** to honorable combat!\n\n{result}",
        color_name="red"
    )
    
    embed.add_field(
        name=f"{ctx.author.display_name}",
        value=f"Roll: **{p1_roll}** (Atk+{p1_atk_bonus}, Def+{p1_def_bonus})\nDamage taken: **{p1_damage}**\nHP: {new_p1_hp}/{MAX_HP}",
        inline=True
    )
    
    embed.add_field(
        name=f"{opponent.display_name}",
        value=f"Roll: **{p2_roll}** (Atk+{p2_atk_bonus}, Def+{p2_def_bonus})\nDamage taken: **{p2_damage}**\nHP: {new_p2_hp}/{MAX_HP}",
        inline=True
    )
    
    if reward > 0 and winner:
        embed.add_field(name="🏆 Spoils of War", value=f"**{winner.display_name}** claims **{reward}** gold!", inline=False)
    
    if new_p1_hp <= 0 or new_p2_hp <= 0:
        embed.add_field(name="💀 Defeated", value="The fallen warrior must use healing potions or wait for natural recovery.", inline=False)
    
    embed.set_footer(text="Battle again in 1 hour")
    set_cooldown(ctx.author.id, "battle")
    set_cooldown(opponent.id, "battle")
    
    await ctx.send(embed=embed)

@tree.command(name="battle", description="Challenge another to a duel of honour")
@app_commands.describe(opponent="The opponent to battle")
@app_commands.guild_only
async def slash_battle(interaction: discord.Interaction, opponent: discord.Member):
    class MockCtx:
        def __init__(self, interaction):
            self.author = interaction.user
            self.guild = interaction.guild
            self.send = interaction.response.send_message
    
    ctx = MockCtx(interaction)
    await battle(ctx, opponent=opponent)

# ---------- ON READY ----------
@bot.event
async def on_ready():
    print(f'🏪 Royal Market Bot hath awakened as {bot.user} (ID: {bot.user.id})')
    print('💰 Ready to manage the kingdom\'s economy!')
    print('🏰 Market stalls stocked and ready for trade!')
    print('⚖️ Debt collectors armed with quills!')
    print(f'👑 Administrators receive 50% purse fortification!')
    print(f'📅 Daily stipend: {MAX_DAILY_GOLD}g maximum')
    print('⏰ Cooldowns: Labour (1h), Daily (24h), Battle (1h), Gambling (none)')
    print('🔗 Slash commands loaded!')
    print('------')
    
    # Sync slash commands
    try:
        synced = await tree.sync()
        print(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")
    
    # Start the background tasks after bot is ready
    if not levy_debt_interest.is_running():
        levy_debt_interest.start()
    if not collect_royal_tax.is_running():
        collect_royal_tax.start()

# ---------- ERROR HANDLER ----------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    
    # Medieval error messages
    error_messages = {
        commands.BadArgument: {
            "wager": "Prithee, enter a valid number, 'all', or 'max' for thy wager.",
            "Member": "I know not of that soul in our realm. Use @mention or exact name.",
            "TextChannel": "I know not of that hall. Use #channel or exact name.",
            "Role": "I know not of that role. Use @role or exact name.",
            "default": "Thy argument is flawed, good sir. Check thy command usage."
        },
        commands.MissingPermissions: "🚫 Thou lacketh the merchant's seal for this command!",
        commands.NoPrivateMessage: "⚠️ Market commands may not be used in private chambers!",
        commands.MissingRequiredArgument: {
            "member": "Thou must name a soul to pay!",
            "amount": "Thou must specify an amount!",
            "item_name": "Thou must name an item!",
            "choice": "Thou must choose heads or tails!",
            "channel": "Thou must name a market hall!",
            "title": "Thou must specify the title!",
            "role": "Thou must specify the role!",
            "opponent": "Thou must name an opponent!",
            "default": "Thou hast forgotten a required argument!"
        }
    }
    
    # Find appropriate error message
    error_msg = None
    error_type = type(error)
    if error_type in error_messages:
        if error_type == commands.BadArgument:
            err_str = str(error)
            for key in error_messages[commands.BadArgument]:
                if key in err_str:
                    error_msg = error_messages[commands.BadArgument][key]
                    break
            if not error_msg:
                error_msg = error_messages[commands.BadArgument]["default"]
        elif error_type == commands.MissingRequiredArgument:
            param = str(error.param)
            for key in error_messages[commands.MissingRequiredArgument]:
                if key in param.lower():
                    error_msg = error_messages[commands.MissingRequiredArgument][key]
                    break
            if not error_msg:
                error_msg = error_messages[commands.MissingRequiredArgument]["default"]
        else:
            error_msg = error_messages[error_type]
    
    if error_msg:
        embed = medieval_response(error_msg, success=False)
        await ctx.send(embed=embed)
    else:
        embed = medieval_response(
            "An ill omen befell the royal merchants! They have been informed.",
            success=False
        )
        await ctx.send(embed=embed)
        print("🏪 Unhandled error:", type(error).__name__, error)

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("🚫 Thou lacketh the merchant's seal for this command!", ephemeral=True)
    elif isinstance(error, app_commands.CommandNotFound):
        return
    else:
        await interaction.response.send_message("An ill omen befell the royal merchants!", ephemeral=True)
        print("🏪 Slash command error:", type(error).__name__, error)

# ---------- RUN ----------
if __name__ == "__main__":
    init_db()
    print("🏪 Initializing Royal Market Economy Bot...")
    print("💰 Loading coin purses and ledgers...")
    print("🏰 Stocking the marketplace with fine wares...")
    print("⚖️ Preparing debt collection systems...")
    print("🎰 Setting up games of chance...")
    print("⚔️ Preparing battle arena...")
    print(f"👑 Administrators will receive {CAP_GOLD//2}/{CAP_GOLD} gold")
    print(f"📅 Daily stipend: {MAX_DAILY_GOLD}g maximum")
    print("⏰ Cooldown system: Labour (1 hour), Daily (24 hours), Battle (1 hour), Gambling (no cooldown)")
    print("🔗 Loading slash commands...")
    bot.run(TOKEN)
