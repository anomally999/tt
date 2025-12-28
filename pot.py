# royal_market.py — Royal Market Economy Bot with Battle System
# Complete medieval marketplace with economy and battle system
import os
import random
import sqlite3
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import timedelta, datetime as dt, timezone
from discord.utils import utcnow
from enum import Enum
import asyncio

# ---------- ENV ----------
load_dotenv()
TOKEN  = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("PREFIX", "!")
DB_NAME = "royal_market.db"
DEBT_INTEREST_RATE = 0.02  # 2% daily
DAYS_BEFORE_PRISON = 3
PRISON_ROLE_NAME = "Debtor"

# ---------- MEDIEVAL FLAIR ----------
MEDIEVAL_COLORS = {
    "gold": discord.Colour.gold(),
    "dark_gold": discord.Colour.dark_gold(),
    "red": discord.Colour.dark_red(),
    "green": discord.Colour.dark_green(),
    "blue": discord.Colour.dark_blue(),
    "purple": discord.Colour.purple(),
    "orange": discord.Colour.dark_orange(),
    "teal": discord.Colour.teal(),
    "blurple": discord.Colour.blurple(),
    "battle": discord.Colour.dark_purple(),
}

MEDIEVAL_PREFIXES = [
    "Hark!",
    "Verily,",
    "By mine honour,",
    "Prithee,",
    "Forsooth,",
    "Hear ye, hear ye!",
    "Lo and behold,",
    "By mine troth,",
    "Marry,",
    "Gadzooks!",
    "Zounds!",
    "By the saints,",
    "By my halidom,",
    "In faith,",
    "By my beard,",
    "By the rood,",
    "Alack,",
    "Alas,",
    "Fie upon it!",
]

MEDIEVAL_SUFFIXES = [
    "m'lord.",
    "good sir.",
    "fair maiden.",
    "noble knight.",
    "worthy peasant.",
    "gentle soul.",
    "brave warrior.",
    "wise sage.",
    "royal subject.",
    "courtier.",
    "squire.",
    "yeoman.",
    "varlet.",
    "knave.",
    "villager.",
]

def get_medieval_prefix():
    return random.choice(MEDIEVAL_PREFIXES)

def get_medieval_suffix():
    return random.choice(MEDIEVAL_SUFFIXES)

def medieval_embed(title="", description="", color_name="gold"):
    """Create an embed with medieval styling"""
    color = MEDIEVAL_COLORS.get(color_name, MEDIEVAL_COLORS["gold"])
    embed = discord.Embed(
        title=f"💰  {title}" if "💰" not in title and "🏪" not in title and "⚔️" not in title else title,
        description=description,
        colour=color
    )
    return embed

def medieval_response(message, success=True, extra=""):
    """Create a medieval-style response message"""
    prefix = get_medieval_prefix()
    suffix = get_medieval_suffix() if random.random() > 0.5 else ""
    color = "green" if success else "red"

    full_message = f"{prefix} {message} {suffix}".strip()
    if extra:
        full_message += f"\n\n{extra}"

    return medieval_embed(description=full_message, color_name=color)

# ---------- BATTLE SYSTEM ----------
class BattleAction(Enum):
    THRUST = "thrust"      # High damage, low accuracy
    SLASH = "slash"        # Medium damage, medium accuracy
    BLOCK = "block"        # Defense boost, counter chance
    DODGE = "dodge"        # Avoid next attack
    HEAL = "heal"          # Restore health (requires potion)
    FLEE = "flee"          # Attempt to escape

class BattleStatus:
    def __init__(self, challenger, opponent):
        self.challenger = challenger
        self.opponent = opponent
        self.challenger_hp = 100
        self.opponent_hp = 100
        self.challenger_defense = 0
        self.opponent_defense = 0
        self.challenger_dodge = False
        self.opponent_dodge = False
        self.turn = 0  # 0 = challenger, 1 = opponent
        self.challenger_used_items = []
        self.opponent_used_items = []
        self.battle_log = []

    def add_log(self, message):
        self.battle_log.append(message)

    def get_status(self):
        return (f"**{self.challenger.display_name}**: ❤️ {self.challenger_hp}/100 | 🛡️ {self.challenger_defense}\n"
                f"**{self.opponent.display_name}**: ❤️ {self.opponent_hp}/100 | 🛡️ {self.opponent_defense}")

# ---------- BOT ----------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None, case_insensitive=True)

# ---------- ECONOMY DB ----------
def init_db():
    with sqlite3.connect(DB_NAME) as db:
        # Create tables if they don't exist
        db.execute("""
        CREATE TABLE IF NOT EXISTS economy (
            user_id INTEGER PRIMARY KEY,
            gold INTEGER DEFAULT 0,
            silver INTEGER DEFAULT 0,
            copper INTEGER DEFAULT 0,
            debt INTEGER DEFAULT 0,
            debt_since TEXT
        )""")
        db.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            item TEXT,
            qty INTEGER,
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
            battle_roles TEXT
        )""")
        db.execute("""
        CREATE TABLE IF NOT EXISTS battle_stats (
            user_id INTEGER PRIMARY KEY,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_damage INTEGER DEFAULT 0,
            duels_fought INTEGER DEFAULT 0
        )""")

        # Check if battle_roles column exists, if not add it
        cursor = db.execute("PRAGMA table_info(guild_config)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'battle_roles' not in columns:
            print("⚠️  Adding 'battle_roles' column to guild_config table...")
            db.execute("ALTER TABLE guild_config ADD COLUMN battle_roles TEXT")

        db.commit()

# ---------- ECONOMY SYSTEM ----------
CAP_GOLD = 999
CAP_SILVER = 999
CAP_COPPER = 999

def get_pouch(user_id, ctx=None):
    """Get user's coin pouch with admin check"""
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT gold, silver, copper, debt, debt_since FROM economy WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            # New users start with 10 silver and 500 copper
            db.execute("INSERT INTO economy (user_id, silver, copper) VALUES (?,?,?)", (user_id, 10, 500))
            db.commit()
            return 0, 10, 500, 0, None

        # Check if user is admin and give 50% wallet boost if they are
        if ctx:
            member = ctx.guild.get_member(user_id)
            if member and member.guild_permissions.administrator:
                g, s, c, d, ds = row
                # Calculate 50% of max
                target_gold = CAP_GOLD // 2
                target_silver = CAP_SILVER // 2
                target_copper = CAP_COPPER // 2

                # Only boost if below 50%
                if g < target_gold or s < target_silver or c < target_copper:
                    new_gold = max(g, target_gold)
                    new_silver = max(s, target_silver)
                    new_copper = max(c, target_copper)

                    db.execute("""
                        UPDATE economy SET gold=?, silver=?, copper=? WHERE user_id=?
                    """, (new_gold, new_silver, new_copper, user_id))
                    db.commit()
                    return new_gold, new_silver, new_copper, d, ds

        return row

def add_coin(user_id, gold=0, silver=0, copper=0, ctx=None):
    """Add coin to user's pouch with admin check"""
    # First check current balance with admin boost
    g, s, c, d, ds = get_pouch(user_id, ctx)

    # Convert everything to copper for debt repayment
    total_copper_added = gold * 10000 + silver * 100 + copper

    if total_copper_added > 0 and d > 0:
        # Pay debt first
        pay_amount = min(d, total_copper_added)
        d -= pay_amount
        total_copper_added -= pay_amount

        # Convert remaining back to gold/silver/copper
        remaining = total_copper_added
        gold = remaining // 10000
        remaining %= 10000
        silver = remaining // 100
        copper = remaining % 100

        if d == 0:
            ds = None

    # Apply caps
    g = min(CAP_GOLD, max(0, g + gold))
    s = min(CAP_SILVER, max(0, s + silver))
    c = min(CAP_COPPER, max(0, c + copper))

    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
            INSERT OR REPLACE INTO economy (user_id, gold, silver, copper, debt, debt_since)
            VALUES (?,?,?,?,?,?)
        """, (user_id, g, s, c, d, ds))
        db.commit()

def set_debt(user_id, amount):
    """Set user's debt amount"""
    _, _, _, _, ds = get_pouch(user_id)
    if amount > 0 and ds is None:
        ds = utcnow().isoformat()
    elif amount <= 0:
        ds = None
    with sqlite3.connect(DB_NAME) as db:
        db.execute("UPDATE economy SET debt=?, debt_since=? WHERE user_id=?", (amount, ds, user_id))
        db.commit()

# ---------- SEPARATE COOLDOWNS ----------
def get_cooldown(user_id, action_type):
    """Get user's cooldown for a specific action"""
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute(f"SELECT last_{action_type} FROM cooldowns WHERE user_id=?", (user_id,)).fetchone()
        if not row or not row[0]:
            return None
        return dt.fromisoformat(row[0]).replace(tzinfo=timezone.utc)

def set_cooldown(user_id, action_type):
    """Set user's cooldown for a specific action"""
    with sqlite3.connect(DB_NAME) as db:
        db.execute(f"INSERT OR REPLACE INTO cooldowns (user_id, last_{action_type}) VALUES (?,?)",
                   (user_id, utcnow().isoformat()))
        db.commit()

# ---------- INVENTORY ----------
def add_item(user_id, item, qty=1):
    """Add item to user's inventory"""
    with sqlite3.connect(DB_NAME) as db:
        old = db.execute("SELECT qty FROM inventory WHERE user_id=? AND item=?", (user_id, item)).fetchone()
        old_qty = old[0] if old else 0
        db.execute("INSERT OR REPLACE INTO inventory (user_id, item, qty) VALUES (?,?,?)",
                   (user_id, item, old_qty + qty))
        db.commit()

def remove_item(user_id, item, qty=1):
    """Remove item from user's inventory"""
    with sqlite3.connect(DB_NAME) as db:
        old = db.execute("SELECT qty FROM inventory WHERE user_id=? AND item=?", (user_id, item)).fetchone()
        if not old:
            return False
        old_qty = old[0]
        if old_qty < qty:
            return False
        new_qty = old_qty - qty
        if new_qty <= 0:
            db.execute("DELETE FROM inventory WHERE user_id=? AND item=?", (user_id, item))
        else:
            db.execute("UPDATE inventory SET qty=? WHERE user_id=? AND item=?", (new_qty, user_id, item))
        db.commit()
        return True

def get_inventory(user_id):
    """Get user's entire inventory"""
    with sqlite3.connect(DB_NAME) as db:
        rows = db.execute("SELECT item, qty FROM inventory WHERE user_id=?", (user_id,)).fetchall()
        return {r[0]: r[1] for r in rows} if rows else {}

def has_item(user_id, item, qty=1):
    """Check if user has item(s)"""
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT qty FROM inventory WHERE user_id=? AND item=?", (user_id, item)).fetchone()
        return row is not None and row[0] >= qty

# ---------- BATTLE SYSTEM FUNCTIONS ----------
def set_battle_roles(guild_id, role_ids):
    """Set the battle roles for a guild"""
    role_str = ",".join(str(rid) for rid in role_ids)
    with sqlite3.connect(DB_NAME) as db:
        db.execute("INSERT OR REPLACE INTO guild_config (guild_id, market_channel, battle_roles) VALUES (?,?,?)",
                   (guild_id, None, role_str))
        db.commit()

def get_battle_roles(guild_id):
    """Get the battle roles for a guild"""
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT battle_roles FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
        if row and row[0]:
            return [int(rid) for rid in row[0].split(",") if rid]
        return []

def can_battle(user, guild):
    """Check if user can battle based on roles"""
    battle_roles = get_battle_roles(guild.id)
    if not battle_roles:
        return False

    user_role_ids = [role.id for role in user.roles]
    return any(role_id in user_role_ids for role_id in battle_roles)

def get_battle_hierarchy(guild):
    """Get battle roles in hierarchy order"""
    battle_roles = get_battle_roles(guild.id)
    if not battle_roles:
        return []

    # Get role objects and sort by position (highest first)
    roles = [guild.get_role(rid) for rid in battle_roles if guild.get_role(rid)]
    roles.sort(key=lambda r: r.position, reverse=True)
    return roles

def update_battle_stats(user_id, won=False, damage=0):
    """Update user's battle statistics"""
    with sqlite3.connect(DB_NAME) as db:
        # Get current stats
        row = db.execute("SELECT wins, losses, total_damage, duels_fought FROM battle_stats WHERE user_id=?", (user_id,)).fetchone()

        if not row:
            wins = 1 if won else 0
            losses = 0 if won else 1
            db.execute("INSERT INTO battle_stats (user_id, wins, losses, total_damage, duels_fought) VALUES (?,?,?,?,?)",
                      (user_id, wins, losses, damage, 1))
        else:
            wins, losses, total_damage, duels_fought = row
            wins = wins + 1 if won else wins
            losses = losses + 1 if not won else losses
            total_damage += damage
            duels_fought += 1

            db.execute("""
                UPDATE battle_stats SET wins=?, losses=?, total_damage=?, duels_fought=?
                WHERE user_id=?
            """, (wins, losses, total_damage, duels_fought, user_id))
        db.commit()

def get_battle_stats(user_id):
    """Get user's battle statistics"""
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT wins, losses, total_damage, duels_fought FROM battle_stats WHERE user_id=?", (user_id,)).fetchone()
        if row:
            return {
                "wins": row[0],
                "losses": row[1],
                "total_damage": row[2],
                "duels_fought": row[3],
                "win_rate": round((row[0] / row[3] * 100) if row[3] > 0 else 0, 1),
                "avg_damage": round(row[2] / row[3] if row[3] > 0 else 0, 1)
            }
        return {
            "wins": 0,
            "losses": 0,
            "total_damage": 0,
            "duels_fought": 0,
            "win_rate": 0.0,
            "avg_damage": 0.0
        }

def apply_item_effects(challenger, opponent, battle):
    """Apply item effects to battle"""
    challenger_items = get_inventory(challenger.id)
    opponent_items = get_inventory(opponent.id)

    # Apply defense boosts from armor
    for item, qty in challenger_items.items():
        if qty > 0 and item in ROYAL_MARKET:
            item_data = ROYAL_MARKET[item]
            if item_data.get("type") == "armor":
                if item == "leather_armor":
                    battle.challenger_defense += 3
                elif item == "chainmail":
                    battle.challenger_defense += 6
                elif item == "plate_armor":
                    battle.challenger_defense += 8

    for item, qty in opponent_items.items():
        if qty > 0 and item in ROYAL_MARKET:
            item_data = ROYAL_MARKET[item]
            if item_data.get("type") == "armor":
                if item == "leather_armor":
                    battle.opponent_defense += 3
                elif item == "chainmail":
                    battle.opponent_defense += 6
                elif item == "plate_armor":
                    battle.opponent_defense += 8

# ---------- BATTLE VIEW ----------
class BattleButton(discord.ui.Button):
    def __init__(self, action, battle_status, ctx):
        self.action = action
        self.battle = battle_status
        self.ctx = ctx

        # Set button properties based on action
        emojis = {
            BattleAction.THRUST: "⚔️",
            BattleAction.SLASH: "🗡️",
            BattleAction.BLOCK: "🛡️",
            BattleAction.DODGE: "🌀",
            BattleAction.HEAL: "❤️",
            BattleAction.FLEE: "🏃"
        }

        labels = {
            BattleAction.THRUST: "Thrust",
            BattleAction.SLASH: "Slash",
            BattleAction.BLOCK: "Block",
            BattleAction.DODGE: "Dodge",
            BattleAction.HEAL: "Heal",
            BattleAction.FLEE: "Flee"
        }

        super().__init__(
            style=discord.ButtonStyle.primary,
            label=labels[action],
            emoji=emojis[action],
            custom_id=action.value
        )

    async def callback(self, interaction: discord.Interaction):
        # Check if it's the user's turn
        current_player = self.battle.challenger if self.battle.turn == 0 else self.battle.opponent
        if interaction.user.id != current_player.id:
            await interaction.response.send_message(
                "⏳ It is not thy turn to act!",
                ephemeral=True
            )
            return

        # Process action
        if self.action == BattleAction.HEAL:
            # Check if user has healing potion
            user_id = current_player.id
            if not remove_item(user_id, "healing_potion", 1):
                await interaction.response.send_message(
                    "❌ Thou hast no healing potion!",
                    ephemeral=True
                )
                return
            # Use healing potion
            if self.battle.turn == 0:
                heal_amount = random.randint(20, 40)
                self.battle.challenger_hp = min(100, self.battle.challenger_hp + heal_amount)
                self.battle.add_log(f"**{current_player.display_name}** used a healing potion! +{heal_amount} HP")
                self.battle.challenger_used_items.append("healing_potion")
            else:
                heal_amount = random.randint(20, 40)
                self.battle.opponent_hp = min(100, self.battle.opponent_hp + heal_amount)
                self.battle.add_log(f"**{current_player.display_name}** used a healing potion! +{heal_amount} HP")
                self.battle.opponent_used_items.append("healing_potion")
        elif self.action == BattleAction.FLEE:
            # Attempt to flee
            flee_chance = random.random()
            if flee_chance > 0.5:  # 50% chance to flee
                if self.battle.turn == 0:
                    loser = self.battle.challenger
                    winner = self.battle.opponent
                else:
                    loser = self.battle.opponent
                    winner = self.battle.challenger

                # Calculate winnings (10% of loser's copper)
                g, s, c, _, _ = get_pouch(loser.id, self.ctx)
                winnings = int(c * 0.1)
                if winnings > 0:
                    add_coin(loser.id, 0, 0, -winnings, self.ctx)
                    add_coin(winner.id, 0, 0, winnings, self.ctx)

                self.battle.add_log(f"**{loser.display_name}** fled in cowardice!")
                self.battle.add_log(f"**{winner.display_name}** claims {winnings} copper as spoils!")

                # Send final battle result
                embed = medieval_embed(
                    title="⚔️  Battle Concluded! 🏃",
                    description=f"**{loser.display_name}** hath fled the battlefield!\n\n" +
                               "**Battle Log:**\n" + "\n".join(self.battle.battle_log[-5:]),
                    color_name="battle"
                )
                embed.add_field(name="🏆 Victor", value=winner.display_name, inline=True)
                embed.add_field(name="💰 Spoils", value=f"{winnings} copper", inline=True)
                embed.set_footer(text=f"{winner.display_name} claims victory by default!")

                await interaction.response.edit_message(embed=embed, view=None)
                return
            else:
                self.battle.add_log(f"**{current_player.display_name}** failed to flee!")
        else:
            # Process combat action
            await self.process_combat_action(current_player)

        # Check if battle is over
        if self.battle.challenger_hp <= 0 or self.battle.opponent_hp <= 0:
            await self.end_battle(interaction)
            return

        # Switch turns
        self.battle.turn = 1 - self.battle.turn

        # Update view for next player
        view = BattleView(self.battle, self.ctx)
        embed = self.get_battle_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def process_combat_action(self, current_player):
        is_challenger = (self.battle.turn == 0)
        target = self.battle.opponent if is_challenger else self.battle.challenger
        target_name = target.display_name

        # Check if target is dodging
        if (is_challenger and self.battle.opponent_dodge) or (not is_challenger and self.battle.challenger_dodge):
            self.battle.add_log(f"**{target_name}** dodged the attack!")
            if is_challenger:
                self.battle.opponent_dodge = False
            else:
                self.battle.challenger_dodge = False
            return

        # Calculate damage
        if self.action == BattleAction.THRUST:
            hit_chance = random.random()
            if hit_chance > 0.3:  # 70% accuracy
                damage = random.randint(15, 25)
                defense = self.battle.opponent_defense if is_challenger else self.battle.challenger_defense
                actual_damage = max(1, damage - defense)

                if is_challenger:
                    self.battle.opponent_hp -= actual_damage
                else:
                    self.battle.challenger_hp -= actual_damage

                self.battle.add_log(f"**{current_player.display_name}** thrust for {actual_damage} damage!")
            else:
                self.battle.add_log(f"**{current_player.display_name}** missed with a thrust!")

        elif self.action == BattleAction.SLASH:
            hit_chance = random.random()
            if hit_chance > 0.2:  # 80% accuracy
                damage = random.randint(10, 20)
                defense = self.battle.opponent_defense if is_challenger else self.battle.challenger_defense
                actual_damage = max(1, damage - defense)

                if is_challenger:
                    self.battle.opponent_hp -= actual_damage
                else:
                    self.battle.challenger_hp -= actual_damage

                self.battle.add_log(f"**{current_player.display_name}** slashed for {actual_damage} damage!")
            else:
                self.battle.add_log(f"**{current_player.display_name}** missed with a slash!")

        elif self.action == BattleAction.BLOCK:
            defense_boost = random.randint(3, 7)
            if is_challenger:
                self.battle.challenger_defense += defense_boost
                self.battle.add_log(f"**{current_player.display_name}** blocked! +{defense_boost} defense")
            else:
                self.battle.opponent_defense += defense_boost
                self.battle.add_log(f"**{current_player.display_name}** blocked! +{defense_boost} defense")

        elif self.action == BattleAction.DODGE:
            if is_challenger:
                self.battle.challenger_dodge = True
            else:
                self.battle.opponent_dodge = True
            self.battle.add_log(f"**{current_player.display_name}** prepared to dodge!")

    def get_battle_embed(self):
        current_player = self.battle.challenger if self.battle.turn == 0 else self.battle.opponent
        embed = medieval_embed(
            title="⚔️  Royal Duel ⚔️",
            description=f"**{current_player.display_name}**'s turn to act!\n\n" +
                       self.battle.get_status() + "\n\n" +
                       "**Recent Actions:**\n" + "\n".join(self.battle.battle_log[-3:]),
            color_name="battle"
        )
        embed.set_footer(text=f"Use an action below! • Turn will expire in 60 seconds")
        return embed

    async def end_battle(self, interaction):
        # Determine winner and loser
        if self.battle.challenger_hp <= 0:
            winner = self.battle.opponent
            loser = self.battle.challenger
        else:
            winner = self.battle.challenger
            loser = self.battle.opponent

        # Calculate winnings (20% of loser's copper)
        g, s, c, _, _ = get_pouch(loser.id, self.ctx)
        winnings = int(c * 0.2)
        if winnings > 0:
            add_coin(loser.id, 0, 0, -winnings, self.ctx)
            add_coin(winner.id, 0, 0, winnings, self.ctx)

        # Update battle statistics
        winner_damage = 100 - self.battle.opponent_hp if winner == self.battle.challenger else 100 - self.battle.challenger_hp
        loser_damage = 100 - self.battle.challenger_hp if loser == self.battle.challenger else 100 - self.battle.opponent_hp

        update_battle_stats(winner.id, won=True, damage=winner_damage)
        update_battle_stats(loser.id, won=False, damage=loser_damage)

        # Add final log
        self.battle.add_log(f"🏆 **{winner.display_name}** is victorious!")
        self.battle.add_log(f"💰 **{winner.display_name}** claims {winnings} copper as spoils!")

        # Create final embed
        embed = medieval_embed(
            title="⚔️  Battle Concluded! 🏆",
            description=f"**{winner.display_name}** hath triumphed over **{loser.display_name}**!\n\n" +
                       "**Battle Log:**\n" + "\n".join(self.battle.battle_log[-5:]),
            color_name="battle"
        )
        embed.add_field(name="🏆 Victor", value=winner.display_name, inline=True)
        embed.add_field(name="🏳️ Defeated", value=loser.display_name, inline=True)
        embed.add_field(name="💰 Spoils", value=f"{winnings} copper", inline=True)

        # Check for item bonuses
        winner_inv = get_inventory(winner.id)
        if "enchanted_ring" in winner_inv:
            embed.add_field(name="🔮 Enchanted Ring", value="Magical aura aided thy victory!", inline=False)
        if "warhammer" in winner_inv:
            embed.add_field(name="⚒️ Warhammer", value="Armor-shattering blow proved decisive!", inline=False)

        embed.set_footer(text=f"{winner.display_name} may challenge another noble in 1 hour")

        await interaction.response.edit_message(embed=embed, view=None)


class BattleView(discord.ui.View):
    def __init__(self, battle_status, ctx):
        super().__init__(timeout=60)
        self.battle = battle_status
        self.ctx = ctx
        self.update_buttons()

    def update_buttons(self):
        # Clear existing buttons
        self.clear_items()

        # Add action buttons based on turn
        if (self.battle.turn == 0 and self.battle.challenger.id == self.ctx.author.id) or \
           (self.battle.turn == 1 and self.battle.opponent.id == self.ctx.author.id):

            # Get user's inventory for item checks
            user_id = self.battle.challenger.id if self.battle.turn == 0 else self.battle.opponent.id
            inventory = get_inventory(user_id)

            # Basic actions
            self.add_item(BattleButton(BattleAction.THRUST, self.battle, self.ctx))
            self.add_item(BattleButton(BattleAction.SLASH, self.battle, self.ctx))
            self.add_item(BattleButton(BattleAction.BLOCK, self.battle, self.ctx))
            self.add_item(BattleButton(BattleAction.DODGE, self.battle, self.ctx))

            # Heal button (only if has healing potion)
            if "healing_potion" in inventory and inventory["healing_potion"] > 0:
                self.add_item(BattleButton(BattleAction.HEAL, self.battle, self.ctx))

            # Flee button
            self.add_item(BattleButton(BattleAction.FLEE, self.battle, self.ctx))

    def get_battle_embed(self):
        current_player = self.battle.challenger if self.battle.turn == 0 else self.battle.opponent
        embed = medieval_embed(
            title="⚔️  Royal Duel ⚔️",
            description=f"**{current_player.display_name}**'s turn to act!\n\n" +
                       self.battle.get_status() + "\n\n" +
                       "**Recent Actions:**\n" + "\n".join(self.battle.battle_log[-3:]),
            color_name="battle"
        )
        embed.set_footer(text=f"Use an action below! • Turn will expire in 60 seconds")
        return embed

# ---------- ROYAL MARKETPLACE ----------
ROYAL_MARKET = {
    # Food & Drink
    "bread": {"price": (0, 0, 5), "desc": "A hearty loaf to fill a peasant's belly", "type": "food", "use": "Restores vigor"},
    "ale": {"price": (0, 0, 12), "desc": "Foaming tankard of barley brew", "type": "drink", "use": "Cheers the spirit"},
    "cheese": {"price": (0, 0, 8), "desc": "Wheel of aged goat cheese", "type": "food", "use": "Sustains on long journeys"},
    "roast_chicken": {"price": (0, 2, 0), "desc": "Whole roasted fowl with herbs", "type": "food", "use": "Feasts the hungry"},
    "mead": {"price": (0, 1, 0), "desc": "Honey wine of the northlands", "type": "drink", "use": "Warms the bones"},

    # Weapons (Battle Effects)
    "dagger": {"price": (0, 25, 0), "desc": "Small blade for close encounters", "type": "weapon",
               "use": "+10% dodge chance in battle", "battle_effect": "dodge_boost"},
    "shortsword": {"price": (0, 50, 0), "desc": "Reliable blade for any fighter", "type": "weapon",
                   "use": "+15% accuracy with slash attacks", "battle_effect": "accuracy_boost"},
    "longbow": {"price": (0, 40, 0), "desc": "Yew bow with quiver of arrows", "type": "weapon",
                "use": "Can attack from distance first", "battle_effect": "first_strike"},
    "battleaxe": {"price": (0, 75, 0), "desc": "Heavy axe for strong warriors", "type": "weapon",
                  "use": "+5 damage to all attacks", "battle_effect": "damage_boost"},
    "warhammer": {"price": (0, 65, 0), "desc": "Crushing weapon of knights", "type": "weapon",
                  "use": "Ignores 50% of enemy defense", "battle_effect": "armor_pierce"},

    # Armor (Battle Effects)
    "leather_armor": {"price": (0, 45, 0), "desc": "Light protection for travelers", "type": "armor",
                      "use": "+3 base defense in battle", "battle_effect": "defense_boost"},
    "chainmail": {"price": (0, 90, 0), "desc": "Interlocking metal rings", "type": "armor",
                  "use": "+6 base defense in battle", "battle_effect": "defense_boost"},
    "plate_armor": {"price": (2, 0, 0), "desc": "Full steel plate of knights", "type": "armor",
                    "use": "+8 base defense in battle", "battle_effect": "defense_boost"},
    "shield": {"price": (0, 30, 0), "desc": "Wooden shield with iron boss", "type": "armor",
               "use": "Block action is 50% more effective", "battle_effect": "block_boost"},
    "helmet": {"price": (0, 25, 0), "desc": "Steel helmet with nasal guard", "type": "armor",
               "use": "Reduces critical hit chance against you", "battle_effect": "crit_reduction"},

    # Magic Items (Battle Effects)
    "healing_potion": {"price": (0, 15, 0), "desc": "Restores vitality in dire times", "type": "potion",
                       "use": "Heals 20-40 HP in battle", "battle_effect": "healing"},
    "mana_potion": {"price": (0, 20, 0), "desc": "Restores magical energy", "type": "potion",
                    "use": "Allows extra action in battle", "battle_effect": "extra_action"},
    "enchanted_ring": {"price": (5, 0, 0), "desc": "Magical ring with unknown powers", "type": "magic",
                       "use": "+10% chance to land critical hits", "battle_effect": "crit_boost"},
    "crystal_ball": {"price": (3, 0, 0), "desc": "For fortune telling and scrying", "type": "magic",
                     "use": "Reveals enemy's next move", "battle_effect": "predict"},
    "phoenix_feather": {"price": (10, 0, 0), "desc": "Legendary feather with magic", "type": "magic",
                        "use": "Once per battle, survive fatal blow with 1 HP", "battle_effect": "revive"},

    # Tools
    "lantern": {"price": (0, 8, 0), "desc": "Light for dark dungeons", "type": "tool", "use": "Illuminates darkness"},
    "rope": {"price": (0, 2, 0), "desc": "Strong hemp rope, 50 feet", "type": "tool", "use": "Climbing aid"},
    "lockpicks": {"price": (0, 20, 0), "desc": "Tools for discreet entry", "type": "tool", "use": "Opens locks"},
    "spyglass": {"price": (0, 35, 0), "desc": "See distant lands and foes", "type": "tool", "use": "Long vision"},
    "map": {"price": (0, 5, 0), "desc": "Chart of surrounding lands", "type": "tool", "use": "Navigation aid"},

    # Luxuries
    "golden_goblet": {"price": (5, 0, 0), "desc": "Gilded cup for showing riches", "type": "luxury", "use": "Impression +5"},
    "silver_locket": {"price": (0, 30, 0), "desc": "Ornate locket with compartment", "type": "luxury", "use": "Stores secrets"},
    "royal_seal": {"price": (10, 0, 0), "desc": "Official seal of kingdom", "type": "luxury", "use": "Authority symbol"},
    "chess_set": {"price": (0, 15, 0), "desc": "Royal game of strategy", "type": "luxury", "use": "Intelligence +3"},
    "silver_flute": {"price": (0, 25, 0), "desc": "Musical instrument for bards", "type": "luxury", "use": "Charisma +4"},

    # Companions & Mounts (Battle Effects)
    "hunting_hound": {"price": (0, 50, 0), "desc": "Loyal beast for the trail", "type": "companion",
                      "use": "Chance to attack alongside you", "battle_effect": "companion_attack"},
    "falcon": {"price": (0, 60, 0), "desc": "Noble bird for hunting", "type": "companion",
               "use": "Reveals enemy inventory", "battle_effect": "scout"},
    "warhorse": {"price": (1, 0, 0), "desc": "Sturdy steed for battle", "type": "mount",
                 "use": "+20% flee success chance", "battle_effect": "flee_boost"},
    "pack_mule": {"price": (0, 40, 0), "desc": "Beast of burden for goods", "type": "mount", "use": "Carry capacity +50"},

    # Resources
    "iron_ore": {"price": (0, 0, 20), "desc": "Unrefined iron from mines", "type": "resource", "use": "Crafting material"},
    "herbs": {"price": (0, 5, 0), "desc": "Medicinal herbs for healing", "type": "resource", "use": "Potion ingredient"},
    "furs": {"price": (0, 8, 0), "desc": "Warm pelts from forest", "type": "resource", "use": "Clothing material"},
    "gemstones": {"price": (0, 50, 0), "desc": "Precious stones for trade", "type": "resource", "use": "High value trade"},
}

ITEMS_PER_PAGE = 8

# ---------- DEBT & PRISON ----------
@tasks.loop(hours=24)
async def levy_debt_interest():
    """Apply daily interest to debts"""
    with sqlite3.connect(DB_NAME) as db:
        rows = db.execute("SELECT user_id, debt FROM economy WHERE debt > 0").fetchall()
        for uid, debt in rows:
            new_debt = int(debt * (1 + DEBT_INTEREST_RATE))
            db.execute("UPDATE economy SET debt=? WHERE user_id=?", (new_debt, uid))
        db.commit()

    # Check for prison sentences
    await check_prison_sentences()

async def check_prison_sentences():
    """Check for debtors who should be imprisoned"""
    now = utcnow()
    with sqlite3.connect(DB_NAME) as db:
        rows = db.execute("SELECT user_id, debt_since FROM economy WHERE debt > 0").fetchall()
        for uid, since_str in rows:
            if not since_str:
                continue
            since = dt.fromisoformat(since_str).replace(tzinfo=timezone.utc)
            if (now - since).days >= DAYS_BEFORE_PRISON:
                for guild in bot.guilds:
                    member = guild.get_member(uid)
                    if not member:
                        continue
                    role = discord.utils.get(guild.roles, name=PRISON_ROLE_NAME)
                    if role and role not in member.roles:
                        try:
                            await member.add_roles(role)
                            # Announce in market channel if set
                            market_chan_id = get_market_channel(guild.id)
                            if market_chan_id:
                                chan = guild.get_channel(market_chan_id)
                                if chan:
                                    await chan.send(
                                        f"⚖️  **Hear ye!** {member.display_name} hath been cast into debtor's prison "
                                        f"for failing to settle debts to the Crown!"
                                    )
                        except discord.Forbidden:
                            pass

@levy_debt_interest.before_loop
async def before_interest():
    await bot.wait_until_ready()

# ---------- MARKET CHANNEL ----------
def set_market_channel(guild_id, channel_id):
    """Set the market announcement channel"""
    with sqlite3.connect(DB_NAME) as db:
        db.execute("INSERT OR REPLACE INTO guild_config (guild_id, market_channel, battle_roles) VALUES (?,?,?)",
                   (guild_id, channel_id, None))
        db.commit()

def get_market_channel(guild_id):
    """Get the market announcement channel"""
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("SELECT market_channel FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
        return row[0] if row else None

# ---------- SHOP VIEW ----------
class MarketView(discord.ui.View):
    def __init__(self, ctx, current_page=0):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.current_page = current_page
        self.total_pages = (len(ROYAL_MARKET) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    def get_page_embed(self):
        items = list(ROYAL_MARKET.items())
        start_idx = self.current_page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = items[start_idx:end_idx]

        embed = medieval_embed(
            title=f"🏪  Royal Marketplace - Page {self.current_page + 1} of {self.total_pages}",
            color_name="gold"
        )

        for item_key, data in page_items:
            g, s, c = data["price"]

            # Format price
            price_parts = []
            if g > 0:
                price_parts.append(f"**{g}** gold")
            if s > 0:
                price_parts.append(f"**{s}** silver")
            if c > 0:
                price_parts.append(f"**{c}** copper")
            price_str = ", ".join(price_parts)

            # Item type icon
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
                "resource": "⛏️"
            }

            icon = type_icons.get(data["type"], "📦")
            item_name = item_key.replace('_', ' ').title()

            embed.add_field(
                name=f"{icon} {item_name} - {price_str}",
                value=f"{data['desc']}\n*Use: {data['use']}*",
                inline=False
            )

        embed.set_footer(text=f"Use {PREFIX}buy <item_name> to purchase • {len(ROYAL_MARKET)} total wares")
        embed.description = "**Fine wares from across the realm!**"

        return embed

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.gray, custom_id="prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "🚫  This market stall is not meant for thee, good sir!",
                ephemeral=True
            )
            return

        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_page_embed(), view=self)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.gray, custom_id="next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "🚫  This market stall is not meant for thee, fair maiden!",
                ephemeral=True
            )
            return

        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_page_embed(), view=self)

# ---------- ECONOMY COMMANDS ----------
@bot.command(name="help")
@commands.guild_only()
async def _help(ctx):
    """Display marketplace commands"""
    cmds = {
        "labour": "Toil for coin at the royal works (1 hour cooldown)",
        "daily": "Claim thy daily royal stipend (24 hour cooldown)",
        "market": "Browse the royal marketplace wares",
        "buy": "Purchase an item from the market",
        "pouch": "Count the coin in thy purse",
        "sack": "Check thy possessions and inventory",
        "use": "Use an item from thy inventory",
        "pay": "Send coin to another soul",
        "gamble": "Wager coin at the dice game (no cooldown)",
        "slots": "Try thy luck at the royal slots (no cooldown)",
        "coinflip": "Heads or tails bet with fortune (no cooldown)",
        "paydebt": "Repay debt to the Crown",
        "setmarket": "Set the market announcement hall (Admin)",
        "battlehelp": "Learn about the royal duel system",
        "challenge": "Challenge a noble to combat",
        "battlestats": "Check battle statistics",
        "battlehierarchy": "View noble ranks",
        "setbroles": "Set which roles can battle (Admin)"
    }

    embed = medieval_embed(
        title="💰  Royal Marketplace Charter",
        description="**Hark!** Here be the commands for the royal economy and duels:\n",
        color_name="gold"
    )

    for name, desc in cmds.items():
        embed.add_field(name=f"**{PREFIX}{name}**", value=f"*{desc}*", inline=False)

    embed.add_field(
        name="⚖️  Remember, good folk:",
        value="• Labour: 1 hour cooldown\n• Daily: 24 hour cooldown\n• Battle: 1 hour cooldown\n• Gambling: No cooldown\n• Debt: 2% daily interest, 3 days unpaid = prison",
        inline=False
    )

    embed.set_footer(text=f"Royal Marketplace & Battle Arena of {ctx.guild.name}")

    await ctx.send(embed=embed)

@bot.command(aliases=['work', 'toil'])
@commands.guild_only()
async def labour(ctx):
    """Toil for coin at the royal works (1 hour cooldown)"""
    cd = get_cooldown(ctx.author.id, "labour")
    if cd and utcnow() - cd < timedelta(hours=1):
        remain = timedelta(hours=1) - (utcnow() - cd)
        m = remain.seconds // 60
        s = remain.seconds % 60
        return await ctx.send(embed=medieval_response(
            f"Thou must rest thy weary bones! Return in **{m}** minutes and **{s}** seconds.",
            success=False
        ))

    # Medieval job types with descriptions
    jobs = {
        "mining": {
            "copper": (20, 70), "silver": (0, 5), "gold": (0, 1),
            "desc": "⛏️  Mining ore in the deep mines",
            "flair": ["The earth yielded its treasures!", "A rich vein was struck!", "The pickaxe rang true in the depths!"]
        },
        "farming": {
            "copper": (15, 50), "silver": (0, 3), "gold": (0, 0),
            "desc": "🌾  Tilling the royal fields",
            "flair": ["The harvest was bountiful!", "The soil yielded good crop!", "The fields were fertile this day!"]
        },
        "blacksmith": {
            "copper": (25, 65), "silver": (0, 6), "gold": (0, 1),
            "desc": "🔥  Forging at the royal smithy",
            "flair": ["The anvil sang with each strike!", "Steel was tempered to perfection!", "The forge burned bright and hot!"]
        },
        "carpentry": {
            "copper": (18, 55), "silver": (0, 4), "gold": (0, 0),
            "desc": "🪵  Crafting in the royal workshop",
            "flair": ["Wood was shaped with master skill!", "Joints were fitted without flaw!", "The saw made sweet music!"]
        },
        "merchant": {
            "copper": (30, 85), "silver": (0, 8), "gold": (0, 2),
            "desc": "💰  Trading in the market square",
            "flair": ["A shrewd bargain was struck!", "Goods changed hands profitably!", "The market favored thy trade!"]
        },
        "guard": {
            "copper": (22, 60), "silver": (0, 5), "gold": (0, 1),
            "desc": "🛡️  Standing watch on castle walls",
            "flair": ["The watch was uneventful but paid!", "No invaders this shift!", "The walls were well defended!"]
        }
    }

    job_name, job_data = random.choice(list(jobs.items()))
    copper = random.randint(job_data["copper"][0], job_data["copper"][1])
    silver = random.randint(job_data["silver"][0], job_data["silver"][1])
    gold = random.randint(job_data["gold"][0], job_data["gold"][1])

    add_coin(ctx.author.id, gold, silver, copper, ctx)
    set_cooldown(ctx.author.id, "labour")

    # Create response with medieval flair
    coin_desc = []
    if gold > 0:
        coin_desc.append(f"**{gold}** gold piece{'s' if gold > 1 else ''}")
    if silver > 0:
        coin_desc.append(f"**{silver}** silver coin{'s' if silver > 1 else ''}")
    if copper > 0:
        coin_desc.append(f"**{copper}** copper penny{'pence' if copper > 1 else ''}")

    coin_str = ", ".join(coin_desc)
    flair = random.choice(job_data["flair"])

    embed = medieval_embed(
        title="🔨  Honest Labour",
        description=f"**{job_data['desc']}**\n\n{flair}\n\nThou hast earned: {coin_str}.",
        color_name="green"
    )

    # Check if user is admin and show wallet status
    if ctx.author.guild_permissions.administrator:
        g, s, c, _, _ = get_pouch(ctx.author.id, ctx)
        admin_status = f"👑 **Royal Administrator:** {g}/{CAP_GOLD} gold, {s}/{CAP_SILVER} silver, {c}/{CAP_COPPER} copper"
        embed.set_footer(text=admin_status)
    else:
        embed.set_footer(text="Return in one hour for more work at the royal works")

    await ctx.send(embed=embed)

@bot.command(aliases=['stipend', 'allowance'])
@commands.guild_only()
async def daily(ctx):
    """Claim thy daily royal stipend (24 hour cooldown)"""
    cd = get_cooldown(ctx.author.id, "daily")
    if cd and utcnow() - cd < timedelta(days=1):
        remain = timedelta(days=1) - (utcnow() - cd)
        h = remain.seconds // 3600
        m = (remain.seconds % 3600) // 60
        return await ctx.send(embed=medieval_response(
            f"Thou hast already claimed today's stipend! Return in **{h}** hours and **{m}** minutes.",
            success=False
        ))

    # Daily reward
    base_copper = 150  # Increased from 100
    bonus = random.randint(0, 75)  # Random bonus
    total_copper = base_copper + bonus

    add_coin(ctx.author.id, 0, 0, total_copper, ctx)
    set_cooldown(ctx.author.id, "daily")

    daily_messages = [
        f"The Crown grants thee thy daily stipend!",
        f"Thy loyalty is rewarded with coin!",
        f"The royal treasury provides for its subjects!",
        f"A day's allowance for a loyal subject!",
    ]

    embed = medieval_embed(
        title="🏦  Daily Royal Stipend",
        description=f"{random.choice(daily_messages)}\n\nThou receivest: **{total_copper}** copper pence.\n\n*Bonus: +{bonus} copper*",
        color_name="green"
    )

    # Check admin status
    if ctx.author.guild_permissions.administrator:
        g, s, c, _, _ = get_pouch(ctx.author.id, ctx)
        admin_note = f"👑 **Royal Purse:** {g}/{CAP_GOLD} gold, {s}/{CAP_SILVER} silver"
        embed.set_footer(text=admin_note)
    else:
        next_daily = utcnow() + timedelta(days=1)
        embed.set_footer(text=f"Next stipend: <t:{int(next_daily.timestamp())}:R>")

    await ctx.send(embed=embed)

@bot.command(aliases=['shop', 'wares'])
@commands.guild_only()
async def market(ctx):
    """Browse the royal marketplace wares"""
    view = MarketView(ctx)
    embed = view.get_page_embed()

    message = await ctx.send(embed=embed, view=view)
    view.message = message

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
    g_price, s_price, c_price = item_data["price"]

    g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
    total_copper = g * 10000 + s * 100 + c
    price_copper = g_price * 10000 + s_price * 100 + c_price

    if total_copper < price_copper:
        shortfall = price_copper - total_copper
        embed = medieval_response(
            "Thy purse is too light for this purchase!",
            success=False,
            extra=f"Thou needest **{shortfall}** more copper. Labour or claim daily stipend to earn more!"
        )
        return await ctx.send(embed=embed)

    # Make purchase
    add_coin(ctx.author.id, -g_price, -s_price, -c_price, ctx)
    add_item(ctx.author.id, item_key)

    # Success message
    item_display = item_key.replace('_', ' ').title()

    price_parts = []
    if g_price > 0:
        price_parts.append(f"**{g_price}** gold")
    if s_price > 0:
        price_parts.append(f"**{s_price}** silver")
    if c_price > 0:
        price_parts.append(f"**{c_price}** copper")
    price_str = ", ".join(price_parts)

    purchase_flairs = [
        f"A fine choice! The {item_display} is now thine!",
        f"Excellent purchase! The {item_display} shall serve thee well!",
        f"Thou hast acquired the {item_display}! May it bring thee fortune!",
        f"The {item_display} is wrapped and ready! A wise investment!",
        f"The merchant smiles! The {item_display} is thine for {price_str}!",
    ]

    embed = medieval_embed(
        title="🏪  Purchase Complete!",
        description=f"{random.choice(purchase_flairs)}\n\n**Item:** {item_display}\n**Cost:** {price_str}\n**Use:** {item_data['use']}",
        color_name="green"
    )

    # Show remaining balance
    g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
    balance_desc = []
    if g > 0:
        balance_desc.append(f"**{g}** gold")
    if s > 0:
        balance_desc.append(f"**{s}** silver")
    if c > 0:
        balance_desc.append(f"**{c}** copper")

    if balance_desc:
        embed.add_field(name="Remaining Purse", value=", ".join(balance_desc), inline=False)

    embed.set_footer(text=f"Use {PREFIX}use {item_display.lower()} to employ thy new ware")

    await ctx.send(embed=embed)

@bot.command(aliases=['purse', 'coins', 'wealth'])
@commands.guild_only()
async def pouch(ctx, member: discord.Member = None):
    """Count the coin in thy purse"""
    member = member or ctx.author
    g, s, c, debt, debt_since = get_pouch(member.id, ctx)

    # Coin descriptions
    coin_desc = []
    if g > 0:
        coin_desc.append(f"**{g}** gold piece{'s' if g > 1 else ''}")
    if s > 0:
        coin_desc.append(f"**{s}** silver coin{'s' if s > 1 else ''}")
    if c > 0:
        coin_desc.append(f"**{c}** copper penny{'pence' if c > 1 else ''}")

    if not coin_desc:
        coin_desc = ["**naught but dust and dreams**"]

    total_value = g * 10000 + s * 100 + c

    embed = medieval_embed(
        title=f"💰  Purse of {member.display_name}",
        description=f"**Contents:** {', '.join(coin_desc)}\n\n**Total Value:** **{total_value:,}** copper pence",
        color_name="gold"
    )

    # Add debt information if applicable
    if debt > 0:
        embed.add_field(
            name="⚖️  Debt to the Crown",
            value=f"**{debt:,}** copper\n*Interest: {DEBT_INTEREST_RATE*100}% daily*\n*Prison in: {DAYS_BEFORE_PRISON} days unpaid*",
            inline=False
        )

        if debt_since:
            since = dt.fromisoformat(debt_since).replace(tzinfo=timezone.utc)
            days_in_debt = (utcnow() - since).days
            embed.add_field(
                name="📅  Days in Debt",
                value=f"**{days_in_debt}** day{'s' if days_in_debt != 1 else ''}",
                inline=True
            )

    # Add wallet capacity
    capacity = f"**{g}/{CAP_GOLD}** gold • **{s}/{CAP_SILVER}** silver • **{c}/{CAP_COPPER}** copper"
    embed.add_field(name="📊  Purse Capacity", value=capacity, inline=False)

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
        "⚔️  Weapons": {k:v for k,v in inventory.items() if ROYAL_MARKET.get(k, {}).get("type") == "weapon"},
        "🛡️  Armor": {k:v for k,v in inventory.items() if ROYAL_MARKET.get(k, {}).get("type") == "armor"},
        "🔮  Magic": {k:v for k,v in inventory.items() if ROYAL_MARKET.get(k, {}).get("type") == "magic"},
        "🧪  Potions": {k:v for k,v in inventory.items() if ROYAL_MARKET.get(k, {}).get("type") == "potion"},
        "🍞  Provisions": {k:v for k,v in inventory.items() if ROYAL_MARKET.get(k, {}).get("type") in ["food", "drink"]},
        "🛠️  Tools": {k:v for k,v in inventory.items() if ROYAL_MARKET.get(k, {}).get("type") == "tool"},
        "💎  Luxuries": {k:v for k,v in inventory.items() if ROYAL_MARKET.get(k, {}).get("type") == "luxury"},
        "🐕  Companions": {k:v for k,v in inventory.items() if ROYAL_MARKET.get(k, {}).get("type") in ["companion", "mount"]},
        "⛏️  Resources": {k:v for k,v in inventory.items() if ROYAL_MARKET.get(k, {}).get("type") == "resource"},
        "📦  Miscellaneous": {k:v for k,v in inventory.items() if k not in [item for cat in categories.values() for item in cat]}
    }

    total_items = sum(inventory.values())

    embed = medieval_embed(
        title=f"🎒  Sack of {member.display_name}",
        description=f"**Total Items:** {total_items}\n**Unique Wares:** {len(inventory)}",
        color_name="blue"
    )

    for category_name, items in categories.items():
        if items:
            items_list = "\n".join([f"• {k.replace('_', ' ').title()}: **{v}**" for k, v in items.items()])
            embed.add_field(name=category_name, value=items_list, inline=False)

    if member.guild_permissions.administrator:
        embed.set_footer(text="👑 Royal Administrator's Possessions")
    elif total_items > 20:
        embed.set_footer(text="A well-stocked adventurer indeed!")
    elif total_items > 10:
        embed.set_footer(text="Thy sack grows heavy with wares!")
    else:
        embed.set_footer(text="More room for treasures and trinkets!")

    await ctx.send(embed=embed)

@bot.command(aliases=['employ', 'consume', 'drink', 'eat', 'equip'])
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
            f"Thou equippest the {item_display}. {effect}!",
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
        title=f"✨  Using {item_display}",
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
            g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
            pay_amount = c  # Can only pay copper directly
            amount_desc = "all thy copper"
        else:
            # Try to parse as number first
            try:
                pay_amount = int(amount)
                amount_desc = f"**{pay_amount}** copper"
            except ValueError:
                # Try to parse as gold/silver/copper string
                parts = amount.lower().split()
                pay_amount = 0
                amount_desc_parts = []

                for i in range(0, len(parts), 2):
                    if i + 1 >= len(parts):
                        break

                    try:
                        num = int(parts[i])
                        unit = parts[i + 1]

                        if unit.startswith('g'):
                            pay_amount += num * 10000
                            amount_desc_parts.append(f"**{num}** gold")
                        elif unit.startswith('s'):
                            pay_amount += num * 100
                            amount_desc_parts.append(f"**{num}** silver")
                        elif unit.startswith('c'):
                            pay_amount += num
                            amount_desc_parts.append(f"**{num}** copper")
                    except (ValueError, IndexError):
                        pass

                if not amount_desc_parts:
                    raise ValueError("Invalid amount format")

                amount_desc = ", ".join(amount_desc_parts)

        if pay_amount <= 0:
            return await ctx.send(embed=medieval_response(
                "Thou must send a positive amount of coin!",
                success=False
            ))

        # Check if sender has enough
        g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
        if pay_amount > c:
            return await ctx.send(embed=medieval_response(
                f"Thou hast only **{c}** copper, but wishest to send **{pay_amount}**!",
                success=False
            ))

        # Make the payment
        add_coin(ctx.author.id, 0, 0, -pay_amount, ctx)  # Remove from sender
        add_coin(member.id, 0, 0, pay_amount, ctx)  # Add to receiver

        # Create response
        payment_messages = [
            f"Thou hast paid {amount_desc} to {member.display_name}!",
            f"{amount_desc} changes hands from thee to {member.display_name}!",
            f"Thou transferrest {amount_desc} to {member.display_name}'s purse!",
            f"The coin hath been sent! {amount_desc} to {member.display_name}!",
        ]

        embed = medieval_embed(
            title="💰  Royal Payment",
            description=f"{random.choice(payment_messages)}",
            color_name="green"
        )

        if note:
            embed.add_field(name="📝  Note", value=note, inline=False)

        # Show sender's remaining balance
        g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
        remaining_desc = []
        if g > 0:
            remaining_desc.append(f"**{g}** gold")
        if s > 0:
            remaining_desc.append(f"**{s}** silver")
        if c > 0:
            remaining_desc.append(f"**{c}** copper")

        if remaining_desc:
            embed.add_field(name="Thy Remaining Purse", value=", ".join(remaining_desc), inline=False)

        # Check if receiver is admin
        if member.guild_permissions.administrator:
            embed.set_footer(text=f"👑 Paid to Royal Administrator • {member.display_name}")
        else:
            embed.set_footer(text=f"Payment recorded in royal ledgers")

        await ctx.send(embed=embed)

        # Send DM to receiver if possible
        try:
            dm_embed = medieval_embed(
                title="💰  Coin Received!",
                description=f"**{ctx.author.display_name}** hath paid thee {amount_desc} in **{ctx.guild.name}**!",
                color_name="green"
            )

            if note:
                dm_embed.add_field(name="📝  Note", value=note, inline=False)

            await member.send(embed=dm_embed)
        except:
            pass  # Cannot send DM, but that's okay

    except ValueError as e:
        if "Invalid amount format" in str(e):
            embed = medieval_embed(
                title="💰  Payment Format",
                description=f"**Usage:** `{PREFIX}pay @user <amount> [note]`\n\n**Examples:**\n`{PREFIX}pay @friend 100` - Pay 100 copper\n`{PREFIX}pay @merchant all` - Pay all thy copper\n`{PREFIX}pay @knight 2g 5s 10c For thy service`\n`{PREFIX}pay @smith 1g For the sword`",
                color_name="orange"
            )
            embed.set_footer(text="Use 'g' for gold, 's' for silver, 'c' for copper, or just a number for copper")
        else:
            embed = medieval_response(
                "Prithee, enter a valid amount or 'all' for thy payment.",
                success=False
            )
        await ctx.send(embed=embed)

@bot.command(aliases=['dice', 'wager'])
@commands.guild_only()
async def gamble(ctx, wager: str = "10"):
    """Wager coin at the dice game (no cooldown)"""
    try:
        # Parse wager
        if wager.lower() in ["all", "max"]:
            g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
            wager_amount = c
            wager_desc = "all thy copper"
        else:
            wager_amount = int(wager)
            wager_desc = f"**{wager_amount}** copper"

        if wager_amount <= 0:
            return await ctx.send(embed=medieval_response(
                "Thou must wager a positive amount of coin, good sir!",
                success=False
            ))

        g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
        if wager_amount > c + debt:
            return await ctx.send(embed=medieval_response(
                "Thy purse is too light for such a wager!",
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
            add_coin(ctx.author.id, 0, 0, wager_amount, ctx)
            color = "green"
            win_lose = f"Thou gainest **{wager_amount}** copper!"
            flair = random.choice([
                "The dice favor the bold!",
                "Fortune smiles upon thee!",
                "A most excellent roll!",
                "Thy luck holds strong!",
            ])
        elif player_roll < house_roll:
            outcome = "DEFEAT! 💀"
            result_desc = f"The house's **{house_name}** bested thy **{player_name}**!"
            add_coin(ctx.author.id, 0, 0, -wager_amount, ctx)
            color = "red"
            win_lose = f"Thou losest **{wager_amount}** copper."
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

        # Check for debt
        g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
        if c < 0:
            set_debt(ctx.author.id, -c)
            add_coin(ctx.author.id, 0, 0, c, ctx)
            win_lose += f"\n\n⚠️  Thou art now **{debt}** copper in debt to the Crown!"

        embed = medieval_embed(
            title=f"🎲  {outcome}",
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
    cost = 5
    g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
    if c < cost:
        return await ctx.send(embed=medieval_response(
            f"Thou needest {cost} copper pennies to play the royal slots!",
            success=False
        ))

    add_coin(ctx.author.id, 0, 0, -cost, ctx)

    symbols = ["🍒", "⭐", "🔔", "👑", "💎", "⚔️", "🛡️", "🐉", "⚜️", "🏰"]
    slot1 = random.choice(symbols)
    slot2 = random.choice(symbols)
    slot3 = random.choice(symbols)

    result = f"**[ {slot1} | {slot2} | {slot3} ]**"

    # Medieval slot outcomes
    if slot1 == slot2 == slot3:
        if slot1 == "💎":
            win = 200
            msg = "**JACKPOT! DIAMONDS OF LEGEND!** 💎"
            flavor = "The gods of fortune shower thee with riches!"
        elif slot1 == "👑":
            win = 100
            msg = "**ROYAL FLUSH!** 👑"
            flavor = "A king's ransom is thine!"
        elif slot1 == "🐉":
            win = 150
            msg = "**DRAGON'S HOARD!** 🐉"
            flavor = "Thou hast found a dragon's treasure trove!"
        elif slot1 == "🏰":
            win = 80
            msg = "**CASTLE FORTUNE!** 🏰"
            flavor = "The castle treasury opens for thee!"
        else:
            win = 40
            msg = "**THREE OF A KIND!**"
            flavor = "A most fortunate alignment of symbols!"
    elif slot1 == slot2 or slot2 == slot3 or slot1 == slot3:
        win = 10
        msg = "**PAIR WIN!**"
        flavor = "Not the grand prize, but coin nonetheless!"
    else:
        win = 0
        msg = "**NO WIN**"
        flavor = "Fortune favors not the bold this day..."

    if win > 0:
        add_coin(ctx.author.id, 0, 0, win, ctx)
        color = "green"
        result_msg = f"**{msg}**\n{flavor}\n\nThou hast won **{win}** copper!"
    else:
        color = "red"
        result_msg = f"**{msg}**\n{flavor}\n\nThou hast lost **{cost}** copper."

    embed = medieval_embed(
        title="🎰  Royal Slot Machine",
        description=f"**{result}**\n\n{result_msg}",
        color_name=color
    )

    if win >= 100:
        embed.set_footer(text="🎉  A truly legendary win!")
    elif win > 0:
        embed.set_footer(text="🎊  Fortune smiles upon thee!")

    await ctx.send(embed=embed)

@bot.command(aliases=['headsails', 'bet'])
@commands.guild_only()
async def coinflip(ctx, choice: str = "", wager: str = "10"):
    """Heads or tails bet with fortune (no cooldown)"""
    if choice.lower() not in ["heads", "tails", "h", "t"]:
        embed = medieval_embed(
            title="🪙  Royal Coin Flip",
            description=f"**Usage:** `{PREFIX}coinflip <heads/tails> [wager]`\n\n**Examples:**\n`{PREFIX}coinflip heads 50`\n`{PREFIX}coinflip tails max`\n`{PREFIX}coinflip h all`",
            color_name="orange"
        )
        embed.set_footer(text="Heads bears the King's likeness, tails the Royal Crest")
        return await ctx.send(embed=embed)

    try:
        if wager.lower() in ["all", "max"]:
            g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
            wager_amount = c
            wager_desc = "all thy copper"
        else:
            wager_amount = int(wager)
            wager_desc = f"**{wager_amount}** copper"

        if wager_amount <= 0:
            return await ctx.send(embed=medieval_response(
                "A wager must be positive coin, good sirrah!",
                success=False
            ))

        g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)
        if wager_amount > c + debt:
            return await ctx.send(embed=medieval_response(
                "Thy purse jingles not with enough coin for this wager!",
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
            add_coin(ctx.author.id, 0, 0, wager_amount, ctx)
            color = "green"
            win_lose = f"Thou gainest **{wager_amount}** copper!"
            flair = random.choice([
                "The King smiles upon thee!",
                "Fortune favors the bold!",
                "A most excellent guess!",
                "Thy wisdom in gambling shows!",
            ])
        else:
            outcome = "DEFEAT! 💀"
            result_text = f"Alas, thy guess was wrong!"
            add_coin(ctx.author.id, 0, 0, -wager_amount, ctx)
            color = "red"
            win_lose = f"Thou losest **{wager_amount}** copper."
            flair = random.choice([
                "The fickle finger of fate points elsewhere!",
                "Better luck next time, good sir!",
                "The coin hath betrayed thee!",
                "Fortune is a cruel mistress this day!",
            ])

        embed = medieval_embed(
            title=f"🪙  {outcome}",
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
    g, s, c, debt, _ = get_pouch(ctx.author.id, ctx)

    if debt <= 0:
        return await ctx.send(embed=medieval_response(
            "Thou hast no debt to the Crown! Thy ledger is clean.",
            success=True
        ))

    try:
        if amount.lower() in ["all", "max"]:
            pay_amount = min(debt, c)
        else:
            pay_amount = int(amount)

        if pay_amount <= 0:
            return await ctx.send(embed=medieval_response(
                "Thou must pay a positive amount to settle thy debt!",
                success=False
            ))

        if pay_amount > c:
            return await ctx.send(embed=medieval_response(
                f"Thou hast only **{c}** copper, but wishest to pay **{pay_amount}**!",
                success=False
            ))

        if pay_amount > debt:
            pay_amount = debt

        # Pay the debt
        add_coin(ctx.author.id, 0, 0, -pay_amount, ctx)
        new_debt = debt - pay_amount

        if new_debt <= 0:
            set_debt(ctx.author.id, 0)
            message = f"Thy debt to the Crown is fully settled! Thou art free of obligation!"
            extra = "The royal scribe stamps thy ledger CLEAR."
        else:
            set_debt(ctx.author.id, new_debt)
            message = f"Thou hast paid **{pay_amount}** copper toward thy debt!"
            extra = f"Remaining debt: **{new_debt}** copper"

        embed = medieval_response(message, success=True, extra=extra)

        # Check if user was in prison and should be released
        if new_debt <= 0:
            for guild in bot.guilds:
                member = guild.get_member(ctx.author.id)
                if member:
                    role = discord.utils.get(guild.roles, name=PRISON_ROLE_NAME)
                    if role and role in member.roles:
                        try:
                            await member.remove_roles(role)
                            market_chan_id = get_market_channel(guild.id)
                            if market_chan_id:
                                chan = guild.get_channel(market_chan_id)
                                if chan:
                                    await chan.send(
                                        f"🏰  **Hear ye!** {member.display_name} hath settled all debts "
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

# ---------- BATTLE COMMANDS ----------
@bot.command(name="setbroles")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def set_battle_roles_cmd(ctx, *roles: discord.Role):
    """Set which roles can participate in battles"""
    if not roles:
        embed = medieval_response(
            "Prithee, specify the noble roles that may duel!",
            success=False,
            extra=f"Usage: `{PREFIX}setbroles @King @Queen @Duke @Marquise @Count @Viscount @Baron`"
        )
        return await ctx.send(embed=embed)

    role_ids = [role.id for role in roles]
    set_battle_roles(ctx.guild.id, role_ids)

    # Sort roles by hierarchy for display
    sorted_roles = sorted(roles, key=lambda r: r.position, reverse=True)
    role_list = "\n".join([f"• **{role.name}**" for role in sorted_roles])

    embed = medieval_embed(
        title="⚔️  Battle Roles Set",
        description=f"The following noble ranks may now engage in royal duels:\n\n{role_list}",
        color_name="battle"
    )
    embed.set_footer(text=f"Hierarchy: {sorted_roles[0].name} (highest) to {sorted_roles[-1].name} (lowest)")

    await ctx.send(embed=embed)

@bot.command(name="challenge", aliases=['duel', 'fight'])
@commands.guild_only()
async def challenge(ctx, opponent: discord.Member):
    """Challenge another noble to a duel"""
    # Check if challenger can battle
    if not can_battle(ctx.author, ctx.guild):
        embed = medieval_response(
            "Thou art not of noble rank to issue challenges!",
            success=False,
            extra=f"Only those with battle roles may duel. Ask an administrator to use `{PREFIX}setbroles`"
        )
        return await ctx.send(embed=embed)

    # Check if opponent can battle
    if not can_battle(opponent, ctx.guild):
        embed = medieval_response(
            f"{opponent.display_name} is not of noble rank to accept challenges!",
            success=False
        )
        return await ctx.send(embed=embed)

    # Check cooldown
    cd = get_cooldown(ctx.author.id, "battle")
    if cd and utcnow() - cd < timedelta(hours=1):
        remain = timedelta(hours=1) - (utcnow() - cd)
        m = remain.seconds // 60
        s = remain.seconds % 60
        return await ctx.send(embed=medieval_response(
            f"Thou must rest from thy last duel! Return in **{m}** minutes and **{s}** seconds.",
            success=False
        ))

    # Cannot challenge self
    if opponent.id == ctx.author.id:
        return await ctx.send(embed=medieval_response(
            "Thou cannot challenge thyself! That would be madness!",
            success=False
        ))

    # Cannot challenge bots
    if opponent.bot:
        return await ctx.send(embed=medieval_response(
            "Thou cannot challenge automatons or spirits!",
            success=False
        ))

    # Create challenge embed
    hierarchy = get_battle_hierarchy(ctx.guild)
    challenger_rank = next((role for role in ctx.author.roles if role.id in get_battle_roles(ctx.guild.id)), None)
    opponent_rank = next((role for role in opponent.roles if role.id in get_battle_roles(ctx.guild.id)), None)

    embed = medieval_embed(
        title="⚔️  Royal Challenge Issued! ⚔️",
        description=f"**{ctx.author.display_name}** ({challenger_rank.name if challenger_rank else 'Unknown'}) challenges **{opponent.display_name}** ({opponent_rank.name if opponent_rank else 'Unknown'}) to a duel!\n\n" +
                   "The challenged must accept within 60 seconds to proceed.",
        color_name="battle"
    )

    if hierarchy:
        embed.add_field(
            name="🏰  Battle Hierarchy",
            value="\n".join([f"• {role.name}" for role in hierarchy]),
            inline=False
        )

    # Show item advantages
    challenger_items = get_inventory(ctx.author.id)
    opponent_items = get_inventory(opponent.id)

    if challenger_items:
        weapon_count = sum(1 for item in challenger_items if ROYAL_MARKET.get(item, {}).get("type") in ["weapon", "armor", "magic"])
        embed.add_field(name="🗡️  Challenger's Arsenal", value=f"{weapon_count} battle items", inline=True)

    if opponent_items:
        weapon_count = sum(1 for item in opponent_items if ROYAL_MARKET.get(item, {}).get("type") in ["weapon", "armor", "magic"])
        embed.add_field(name="🛡️  Opponent's Arsenal", value=f"{weapon_count} battle items", inline=True)

    embed.set_footer(text=f"{opponent.display_name}, react with ✅ to accept or ❌ to decline")

    # Send challenge and wait for response
    challenge_msg = await ctx.send(embed=embed)
    await challenge_msg.add_reaction("✅")
    await challenge_msg.add_reaction("❌")

    def check(reaction, user):
        return user == opponent and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == challenge_msg.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)

        if str(reaction.emoji) == "❌":
            embed = medieval_embed(
                title="⚔️  Challenge Declined",
                description=f"**{opponent.display_name}** hath declined the duel!\n\n" +
                           f"**{ctx.author.display_name}** must wait for another challenger.",
                color_name="red"
            )
            await challenge_msg.edit(embed=embed)
            await challenge_msg.clear_reactions()
            return

        # Challenge accepted - start battle
        await challenge_msg.clear_reactions()

        # Create battle status
        battle = BattleStatus(ctx.author, opponent)

        # Apply item effects
        apply_item_effects(ctx.author, opponent, battle)

        # Randomly decide who goes first (50/50 chance)
        battle.turn = random.randint(0, 1)

        # Create battle view
        view = BattleView(battle, ctx)
        embed = view.get_battle_embed()

        battle_msg = await ctx.send(embed=embed, view=view)
        view.message = battle_msg

        # Set cooldown for challenger
        set_cooldown(ctx.author.id, "battle")

    except asyncio.TimeoutError:
        embed = medieval_embed(
            title="⚔️  Challenge Expired",
            description=f"**{opponent.display_name}** did not respond in time.\n\n" +
                       f"The challenge from **{ctx.author.display_name}** hath expired.",
            color_name="orange"
        )
        await challenge_msg.edit(embed=embed)
        await challenge_msg.clear_reactions()

@bot.command(name="battlestats", aliases=['bstats', 'duelstats'])
@commands.guild_only()
async def battle_stats(ctx, member: discord.Member = None):
    """Check battle statistics"""
    member = member or ctx.author

    # Check if member can battle
    if not can_battle(member, ctx.guild):
        embed = medieval_response(
            f"{member.display_name} is not of noble rank to participate in battles!",
            success=False
        )
        return await ctx.send(embed=embed)

    stats = get_battle_stats(member.id)

    # Get battle role
    battle_role = next((role for role in member.roles if role.id in get_battle_roles(ctx.guild.id)), None)
    rank_name = battle_role.name if battle_role else "Unknown"

    embed = medieval_embed(
        title=f"⚔️  Battle Record of {member.display_name}",
        description=f"**Rank:** {rank_name}\n**Status:** {'🏆 Victorious' if stats['wins'] > stats['losses'] else '⚔️ Seasoned' if stats['duels_fought'] > 0 else '🛡️ Untested'}",
        color_name="battle"
    )

    embed.add_field(name="🏆 Victories", value=f"**{stats['wins']}**", inline=True)
    embed.add_field(name="🏳️ Defeats", value=f"**{stats['losses']}**", inline=True)
    embed.add_field(name="📊 Win Rate", value=f"**{stats['win_rate']}%**", inline=True)

    embed.add_field(name="⚔️ Duels Fought", value=f"**{stats['duels_fought']}**", inline=True)
    embed.add_field(name="💥 Total Damage", value=f"**{stats['total_damage']}**", inline=True)
    embed.add_field(name="⚡ Avg Damage", value=f"**{stats['avg_damage']}**", inline=True)

    # Calculate rankings
    if stats['duels_fought'] > 0:
        if stats['win_rate'] >= 80:
            rating = "🌟 Legendary Warrior"
        elif stats['win_rate'] >= 60:
            rating = "⚔️ Master Duelist"
        elif stats['win_rate'] >= 40:
            rating = "🛡️ Skilled Fighter"
        elif stats['win_rate'] >= 20:
            rating = "🎯 Novice Combatant"
        else:
            rating = "🛠️ Training Needed"

        embed.add_field(name="🏅 Skill Rating", value=rating, inline=False)

    # Show equipped battle items
    inventory = get_inventory(member.id)
    battle_items = {k:v for k,v in inventory.items()
                   if k in ROYAL_MARKET and ROYAL_MARKET[k].get("type") in ["weapon", "armor", "magic", "potion"]}

    if battle_items:
        item_list = "\n".join([f"• {k.replace('_', ' ').title()} (x{v})" for k,v in battle_items.items()])
        embed.add_field(name="🗡️  Battle Arsenal", value=item_list[:500] + ("..." if len(item_list) > 500 else ""), inline=False)

    embed.set_footer(text=f"Use {PREFIX}challenge @noble to issue a duel")

    await ctx.send(embed=embed)

@bot.command(name="battlehierarchy", aliases=['bhierarchy', 'ranks'])
@commands.guild_only()
async def battle_hierarchy(ctx):
    """Show the battle hierarchy"""
    hierarchy = get_battle_hierarchy(ctx.guild)

    if not hierarchy:
        embed = medieval_response(
            "No battle roles have been set!",
            success=False,
            extra=f"An administrator must use `{PREFIX}setbroles` to establish the noble ranks."
        )
        return await ctx.send(embed=embed)

    embed = medieval_embed(
        title="🏰  Royal Battle Hierarchy",
        description="The noble ranks from highest to lowest authority:\n",
        color_name="battle"
    )

    for i, role in enumerate(hierarchy, 1):
        # Count members with this role who can battle
        members_with_role = [m for m in ctx.guild.members if role in m.roles and can_battle(m, ctx.guild)]

        # Get top duelist in this rank
        top_duelist = None
        top_wins = 0
        for member in members_with_role:
            stats = get_battle_stats(member.id)
            if stats['wins'] > top_wins:
                top_wins = stats['wins']
                top_duelist = member

        rank_info = f"**{i}. {role.name}**\n"
        rank_info += f"Members: {len(members_with_role)}\n"
        if top_duelist and top_wins > 0:
            rank_info += f"Champion: {top_duelist.display_name} ({top_wins} wins)\n"

        embed.add_field(name=f"🎖️  {role.name}", value=rank_info, inline=False)

    embed.set_footer(text=f"Only these noble ranks may issue and accept challenges")

    await ctx.send(embed=embed)

@bot.command(name="battlehelp", aliases=['duelhelp'])
@commands.guild_only()
async def battle_help(ctx):
    """Display battle system commands"""
    cmds = {
        "setbroles": "Set which noble roles can battle (Admin only)",
        "challenge": "Challenge another noble to a duel",
        "battlestats": "Check thine or another's battle statistics",
        "battlehierarchy": "View the noble battle hierarchy",
        "market": "Browse wares that can aid thee in battle",
        "buy": "Purchase weapons, armor, and potions for battle"
    }

    embed = medieval_embed(
        title="⚔️  Royal Battle System",
        description="**Hark!** Here be the commands for honorable duels:\n",
        color_name="battle"
    )

    for name, desc in cmds.items():
        embed.add_field(name=f"**{PREFIX}{name}**", value=f"*{desc}*", inline=False)

    embed.add_field(
        name="🗡️  Battle Actions:",
        value="• **Thrust**: High damage (70% hit)\n• **Slash**: Medium damage (80% hit)\n• **Block**: Boost defense\n• **Dodge**: Avoid next attack\n• **Heal**: Use potion (requires item)\n• **Flee**: Attempt escape (50% chance)",
        inline=False
    )

    embed.add_field(
        name="🏆  Battle Rules:",
        value="• Only nobles with battle roles may duel\n• 1 hour cooldown between challenges\n• Winner claims 20% of loser's copper\n• Items from market affect battle\n• Hierarchy determines social standing",
        inline=False
    )

    embed.set_footer(text=f"Prove thy worth in honorable combat!")

    await ctx.send(embed=embed)

# ---------- ON READY ----------
@bot.event
async def on_ready():
    print(f'🏪  Royal Market Bot hath awakened as {bot.user} (ID: {bot.user.id})')
    print('💰  Ready to manage the kingdom\'s economy!')
    print('⚔️  Battle system initialized for noble duels!')
    print('🏰  Market stalls stocked and ready for trade!')
    print('⚖️  Debt collectors armed with quills!')
    print('👑  Royal administrators receive 50% purse fortification!')
    print('⏰  Separate cooldowns: Labour (1h), Daily (24h), Battle (1h), Gambling (none)')
    print('🎖️  Battle hierarchy system ready for noble challenges!')
    print('------')
    # Start the background task after bot is ready
    if not levy_debt_interest.is_running():
        levy_debt_interest.start()

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
            "default": "Thy argument is flawed, good sir. Check thy command usage."
        },
        commands.MissingPermissions: "🚫  Thou lacketh the merchant's seal for this command!",
        commands.NoPrivateMessage: "⚠️  Market commands may not be used in private chambers!",
        commands.MissingRequiredArgument: {
            "member": "Thou must name a soul to pay!",
            "amount": "Thou must specify an amount!",
            "item_name": "Thou must name an item!",
            "choice": "Thou must choose heads or tails!",
            "channel": "Thou must name a market hall!",
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
        print("🏪  Unhandled error:", type(error).__name__, error)

# ---------- RUN ----------
if __name__ == "__main__":
    init_db()
    print("🏪  Initializing Royal Market Economy Bot with Battle System...")
    print("💰  Loading coin purses and ledgers...")
    print("⚔️  Initializing noble duel system...")
    print("🎖️  Setting up battle hierarchy...")
    print("🏰  Stocking the marketplace with 40 fine wares...")
    print("⚖️  Preparing debt collection systems...")
    print("🎰  Setting up games of chance...")
    print(f"👑  Administrators will receive {CAP_GOLD//2}/{CAP_GOLD} gold, {CAP_SILVER//2}/{CAP_SILVER} silver, {CAP_COPPER//2}/{CAP_COPPER} copper")
    print("⏰  Cooldown system: Labour (1h), Daily (24h), Battle (1h), Gambling (none)")
    print("⚔️  Battle actions: Thrust, Slash, Block, Dodge, Heal, Flee")
    bot.run(TOKEN)
