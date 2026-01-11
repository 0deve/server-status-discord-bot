import discord
from discord.ext import commands
import psutil
import os
import docker
from dotenv import load_dotenv

# .env
load_dotenv()

# read msg
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# containers
TARGET_CONTAINERS = [
    "jellyfin",
    "immich_server",
    "immich_machine_learning",
    "immich_redis",
    "immich_postgres",
    "website",
    "uptime-kuma",
    "cloudflared",
    "odv-share"
]

@bot.event
async def on_ready():
    # sync commands globally (required for slash commands to appear)
    try:
        synced = await bot.tree.sync()
        print(f"synced {len(synced)} command(s)")
    except Exception as e:
        print(f"error syncing commands: {e}")

    print(f'loggin {bot.user}')

# new (test for / commands)
@bot.tree.command(name="ping", description="check connection and qualify for badge")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong")

# old (! command)
@bot.command()
async def health(ctx):
    # cpu util
    cpu = psutil.cpu_percent(interval=None)

    # ram util
    mem = psutil.virtual_memory()
    ram_used = mem.used / (1024 ** 3)  # gb
    ram_total = mem.total / (1024 ** 3)
    ram_percent = mem.percent

    # disk util
    disk = psutil.disk_usage('/')
    disk_free = disk.free / (1024 ** 3)

    # res msg
    sys_msg = (
        f"**server health report** \n"
        f"cpu: {cpu}%\n"
        f"ram: {ram_used:.1f}gb / {ram_total:.1f}gb ({ram_percent}%)\n"
        f"disk free: {disk_free:.1f}gb\n"
        f"-----------------------"
    )

    # docker status
    docker_msg = "\n**docker status** \n"

    try:
        client = docker.from_env()
        for name in TARGET_CONTAINERS:
            try:
                container = client.containers.get(name)
                status = container.status
                icon = "🟢" if status == "running" else "🔴"
                docker_msg += f"{icon} `{name}`: {status}\n"
            except docker.errors.NotFound:
                docker_msg += f"⚪ `{name}`: not found\n"
    except Exception as e:
        docker_msg += f"⚠️ eroare la conectare docker: {e}"

    await ctx.send(sys_msg + docker_msg)

bot.run(os.getenv('DISCORD_TOKEN'))