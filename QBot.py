import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os

TOKEN = os.getenv("TOKEN")

CONFIG_FILE = "config.json"
QUEUE_FILE = "queue.json"

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

created_rooms = set()

# =========================
# CONFIG
# =========================

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_config(guild_id):
    return load_config().get(str(guild_id), None)

def update_config(guild_id, key, value):
    data = load_config()
    gid = str(guild_id)

    if gid not in data:
        data[gid] = {}

    data[gid][key] = value
    save_config(data)

# =========================
# QUEUE (PER GUILD)
# =========================

def load_queue():
    if not os.path.exists(QUEUE_FILE):
        return {}
    with open(QUEUE_FILE, "r") as f:
        return json.load(f)

def save_queue(data):
    with open(QUEUE_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_queue(guild_id):
    return load_queue().get(str(guild_id), [])

def set_queue(guild_id, queue):
    data = load_queue()
    data[str(guild_id)] = queue
    save_queue(data)

# =========================
# EMBED
# =========================

def create_embed(guild_id):

    config = get_config(guild_id)
    if not config:
        return discord.Embed(description="❌ ยังไม่ได้ setup")

    queue = get_queue(guild_id)
    max_queue = config.get("max_queue", 10)

    text = f"📢 ระบบจะสร้างห้องอัตโนมัติเมื่อถึงคิว\n\n"
    text += f"จำนวนคิว: {len(queue)}/{max_queue}\n\n"

    if not queue:
        text += "ไม่มีคิว"
    else:
        for i, uid in enumerate(queue, 1):
            text += f"{i}. <@{uid}>\n"

    return discord.Embed(title="📋 ระบบคิว", description=text, color=0x00FFFF)

async def refresh_panel(guild):
    config = get_config(guild.id)
    if not config:
        return

    channel = guild.get_channel(config.get("queue_channel_id"))
    if not channel:
        return

    try:
        async for msg in channel.history(limit=10):
            if msg.author == bot.user:
                await msg.edit(embed=create_embed(guild.id))
                break
    except:
        pass

# =========================
# PANEL
# =========================

class QueuePanel(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ รับคิว", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button):

        config = get_config(interaction.guild.id)
        if not config:
            return await interaction.response.send_message("❌ ยังไม่ได้ setup", ephemeral=True)

        queue = get_queue(interaction.guild.id)
        max_queue = config.get("max_queue", 10)

        uid = str(interaction.user.id)

        if uid in queue:
            return await interaction.response.send_message("คุณอยู่ในคิวแล้ว", ephemeral=True)

        if len(queue) >= max_queue:
            return await interaction.response.send_message("❌ คิวเต็ม", ephemeral=True)

        queue.append(uid)
        set_queue(interaction.guild.id, queue)

        await interaction.message.edit(embed=create_embed(interaction.guild.id))
        await interaction.response.send_message("เข้าคิวสำเร็จ", ephemeral=True)

    @discord.ui.button(label="🚫 ยกเลิกคิว", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button):

        queue = get_queue(interaction.guild.id)
        uid = str(interaction.user.id)

        if uid in queue:
            queue.remove(uid)
            set_queue(interaction.guild.id, queue)

        await interaction.message.edit(embed=create_embed(interaction.guild.id))
        await interaction.response.send_message("ออกจากคิวแล้ว", ephemeral=True)

# =========================
# AUTO ROOM
# =========================

@tasks.loop(seconds=5)
async def queue_loop():

    for guild in bot.guilds:

        config = get_config(guild.id)
        if not config:
            continue
        if "category_id" not in config:
            continue

        queue = get_queue(guild.id)
        if not queue:
            continue

        first = int(queue[0])

        # กันสร้างซ้ำ
        if first in created_rooms:
            continue

        member = guild.get_member(first)
        if not member:
            continue

        category = guild.get_channel(config["category_id"])

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True)
        }

        # ให้ admin เห็นห้อง
        for admin_id in config.get("admin_ids", []):
            admin = guild.get_member(admin_id)
            if admin:
                overwrites[admin] = discord.PermissionOverwrite(view_channel=True)

        # ✅ สร้างห้อง
        channel = await guild.create_text_channel(
            f"queue-{member.name}",
            category=category,
            overwrites=overwrites
        )

        # ✅ ส่งข้อความแบบที่คุณต้องการ
        embed = discord.Embed(
            title="🎮 ถึงคิวแล้ว",
            description=f"{member.mention}\n\ntest ถึงคิวของคุณแล้ว",
            color=0x00ff00
        )

        await channel.send(
            content=f"{member.mention}",
            embed=embed,
            view=CloseRoom()
        )

        created_rooms.add(first)

# =========================
# CLOSE ROOM
# =========================

class CloseRoom(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 ปิดห้อง", style=discord.ButtonStyle.red)
    async def close(self, interaction: discord.Interaction, button):

        config = get_config(interaction.guild.id)

        if interaction.user.id not in config.get("admin_ids", []):
            return await interaction.response.send_message("❌ ไม่ใช่ admin", ephemeral=True)

        queue = get_queue(interaction.guild.id)

        if queue:
            queue.pop(0)
            set_queue(interaction.guild.id, queue)

        created_rooms.clear()

        await refresh_panel(interaction.guild)
        await interaction.channel.delete()

# =========================
# SETUP UI (FIXED)
# =========================

class SetupView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=60)

        self.queue_channel = None
        self.category = None

        # select queue channel
        select_queue = discord.ui.ChannelSelect(
            placeholder="เลือกห้องคิว",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )

        async def queue_callback(interaction: discord.Interaction):
            ch = select_queue.values[0]
            real = interaction.guild.get_channel(ch.id)

            self.queue_channel = real

            await interaction.response.send_message(
                f"เลือกห้องคิว: {real.mention}",
                ephemeral=True
            )

        select_queue.callback = queue_callback
        self.add_item(select_queue)

        # select category
        select_category = discord.ui.ChannelSelect(
            placeholder="เลือก Category",
            channel_types=[discord.ChannelType.category],
            min_values=1,
            max_values=1
        )

        async def category_callback(interaction: discord.Interaction):
            ch = select_category.values[0]
            real = interaction.guild.get_channel(ch.id)

            self.category = real

            await interaction.response.send_message(
                f"เลือกหมวดหมู่: {real.name}",
                ephemeral=True
            )

        select_category.callback = category_callback
        self.add_item(select_category)

    @discord.ui.button(label="✅ ยืนยัน", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button):

        if not self.queue_channel or not self.category:
            return await interaction.response.send_message("❌ เลือกให้ครบ", ephemeral=True)

        update_config(interaction.guild.id, "queue_channel_id", self.queue_channel.id)
        update_config(interaction.guild.id, "category_id", self.category.id)
        update_config(interaction.guild.id, "admin_ids", [interaction.user.id])
        update_config(interaction.guild.id, "max_queue", 10)

        embed = create_embed(interaction.guild.id)

        await self.queue_channel.send(embed=embed, view=QueuePanel())

        await interaction.response.send_message("✅ setup เสร็จ", ephemeral=True)

# =========================
# COMMANDS
# =========================

@bot.tree.command(name="setup")
async def setup(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True)

    await interaction.response.send_message(
        "ตั้งค่าระบบ",
        view=SetupView(),
        ephemeral=True
    )

@bot.tree.command(name="config")
async def config_cmd(interaction: discord.Interaction):

    config = get_config(interaction.guild.id)

    if not config:
        return await interaction.response.send_message("❌ ยังไม่ได้ setup", ephemeral=True)

    text = (
        f"Queue Channel: <#{config['queue_channel_id']}>\n"
        f"Category: <#{config['category_id']}>\n"
        f"Max Queue: {config.get('max_queue', 10)}\n"
        f"Admins: {', '.join([f'<@{i}>' for i in config.get('admin_ids', [])])}"
    )

    await interaction.response.send_message(text, ephemeral=True)

@bot.tree.command(name="done")
async def done_slash(interaction: discord.Interaction):

    config = get_config(interaction.guild.id)
    if not config:
        return

    if interaction.user.id not in config.get("admin_ids", []):
        return await interaction.response.send_message("❌ ไม่ใช่ admin", ephemeral=True)

    queue = get_queue(interaction.guild.id)

    if not queue:
        return await interaction.response.send_message("❌ ไม่มีคิว", ephemeral=True)

    finished = queue.pop(0)
    set_queue(interaction.guild.id, queue)

    created_rooms.clear()

    await interaction.response.send_message(f"✅ เสร็จสิ้นคิวของ <@{finished}>")
    await refresh_panel(interaction.guild)

@bot.tree.command(name="setmax")
async def setmax(interaction: discord.Interaction, number: int):

    config = get_config(interaction.guild.id)
    if not config:
        return

    if interaction.user.id not in config.get("admin_ids", []):
        return await interaction.response.send_message("❌ ไม่ใช่ admin", ephemeral=True)

    update_config(interaction.guild.id, "max_queue", number)

    await interaction.response.send_message(f"✅ ตั้ง max = {number}", ephemeral=True)

@bot.tree.command(name="addadmin")
async def addadmin(interaction: discord.Interaction, member: discord.Member):

    config = get_config(interaction.guild.id)
    if not config:
        return

    if interaction.user.id not in config.get("admin_ids", []):
        return await interaction.response.send_message("❌ ไม่ใช่ admin", ephemeral=True)

    admins = config.get("admin_ids", [])

    if member.id not in admins:
        admins.append(member.id)

    update_config(interaction.guild.id, "admin_ids", admins)

    await interaction.response.send_message(f"✅ เพิ่ม {member.mention}", ephemeral=True)

@bot.tree.command(name="refresh")
async def refresh_cmd(interaction: discord.Interaction):

    config = get_config(interaction.guild.id)
    if not config:
        return await interaction.response.send_message("❌ ยังไม่ได้ setup", ephemeral=True)

    await refresh_panel(interaction.guild)

    await interaction.response.send_message("✅ รีเฟรชแล้ว", ephemeral=True)

# =========================
# READY
# =========================

@bot.event
async def on_ready():
    print(f"Bot Ready : {bot.user}")

    synced = await bot.tree.sync()
    print(f"Global synced {len(synced)} commands")

    if not queue_loop.is_running():
        queue_loop.start()

bot.run(TOKEN)