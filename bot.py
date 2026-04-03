# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
from discord import app_commands
import psutil
import os
import docker
import time
import io
from collections import deque
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

docker_client = None

def get_docker_client():
    global docker_client
    try:
        if docker_client is None:
            docker_client = docker.from_env()
        docker_client.ping()
    except Exception:
        try:
            docker_client = docker.from_env()
        except Exception as e:
            raise RuntimeError(f"Nu ma pot conecta la Docker: {e}")
    return docker_client

TARGET_CONTAINERS = [
    "jellyfin",
    "immich_server",
    "immich_machine_learning",
    "immich_redis",
    "immich_postgres",
    "website",
    "uptime-kuma",
    "cloudflared",
    "odv-share",
    "alltalk",
    "pihole",
    "homepage",
    "speedtest-tracker",
    "dockge",
    "diun"
]

container_states = {}

ram_history = deque(maxlen=60)

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"synced {len(synced)} command(s)")
    except Exception as e:
        print(f"error syncing commands: {e}")

    monitor_containers.start()
    record_ram.start()

    print(f'Logged in as {bot.user}')

@tasks.loop(minutes=120)
async def monitor_containers():
    channel_id = os.getenv('CHANNEL_ID')
    if not channel_id:
        return

    channel = bot.get_channel(int(channel_id))
    if not channel:
        return

    try:
        client = get_docker_client()
        for name in TARGET_CONTAINERS:
            try:
                container = client.containers.get(name)
                current_status = container.status

                if name in container_states:
                    if container_states[name] == 'running' and current_status != 'running':
                        await channel.send(f"containerul `{name}` s-a oprit! (status: `{current_status}`)")
                    elif container_states[name] != 'running' and current_status == 'running':
                        await channel.send(f"containerul `{name}` a revenit online!")

                container_states[name] = current_status
            except docker.errors.NotFound:
                if name in container_states:
                    await channel.send(f"containerul `{name}` nu mai exista!")
                    del container_states[name]
    except Exception as e:
        print(f"eroare monitorizare: {e}")

@tasks.loop(minutes=5)
async def record_ram():
    mem = psutil.virtual_memory()
    ram_history.append(mem.percent)

@bot.tree.command(name="ping", description="verifica latenta botului")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"pong! latenta: **{latency_ms}ms**")

@bot.tree.command(name="health", description="arata statusul serverului, uptime, temperatura si grafic ram")
async def health(interaction: discord.Interaction):
    await interaction.response.defer()

    cpu = psutil.cpu_percent(interval=1)

    mem = psutil.virtual_memory()
    ram_used = mem.used / (1024 ** 3)
    ram_total = mem.total / (1024 ** 3)
    ram_percent = mem.percent

    disk = psutil.disk_usage('/')
    disk_used = disk.used / (1024 ** 3)
    disk_total = disk.total / (1024 ** 3)
    disk_free = disk.free / (1024 ** 3)

    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time
    uptime_days = int(uptime_seconds // (24 * 3600))
    uptime_hours = int((uptime_seconds % (24 * 3600)) // 3600)
    uptime_mins = int((uptime_seconds % 3600) // 60)

    temp_str = "n/a"
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for sensor_name, entries in temps.items():
                if entries:
                    temp_str = f"{entries[0].current:.1f}C"
                    break
    except AttributeError:
        temp_str = "n/a (OS nesuportat)"

    embed = discord.Embed(
        title="Server Health Report",
        color=0x5865F2
    )
    embed.add_field(
        name="Uptime",
        value=f"{uptime_days}z {uptime_hours}h {uptime_mins}m",
        inline=True
    )
    embed.add_field(
        name="CPU Temp",
        value=temp_str,
        inline=True
    )
    embed.add_field(
        name="CPU",
        value=f"{cpu}%",
        inline=True
    )
    embed.add_field(
        name="RAM",
        value=f"{ram_used:.1f} / {ram_total:.1f} GB ({ram_percent}%)",
        inline=True
    )
    embed.add_field(
        name="Disk",
        value=f"{disk_used:.1f} / {disk_total:.1f} GB (liber: {disk_free:.1f} GB)",
        inline=True
    )

    docker_lines = []
    try:
        client = get_docker_client()
        for name in TARGET_CONTAINERS:
            try:
                container = client.containers.get(name)
                status = container.status
                icon = "ON" if status == "running" else "OFF"
                docker_lines.append(f"{icon} `{name}`: {status}")
            except docker.errors.NotFound:
                docker_lines.append(f"`{name}`: not found")
    except Exception as e:
        docker_lines.append(f"eroare docker: {e}")

    docker_text = "\n".join(docker_lines)
    if len(docker_text) > 1024:
        docker_text = docker_text[:1021] + "..."
    embed.add_field(name="Docker Containers", value=docker_text, inline=False)

    embed.set_footer(text=f"actualizat la {time.strftime('%H:%M:%S')}")

    chart_file = None
    if len(ram_history) > 1:
        fig = None
        try:
            fig, ax = plt.subplots(figsize=(6, 3))
            x = list(range(len(ram_history)))
            y = list(ram_history)

            ax.plot(x, y, color='#5865F2', linewidth=2)
            ax.fill_between(x, y, color='#5865F2', alpha=0.3)
            ax.set_title('Utilizare RAM (%) - ultima ora', color='white', pad=10)
            ax.set_facecolor('#2B2D31')
            ax.tick_params(colors='white')
            ax.set_ylim(0, 100)
            ax.set_xlabel('minute in urma', color='#AAAAAA', fontsize=8)
            for spine in ax.spines.values():
                spine.set_color('#404040')

            fig.set_facecolor('#2B2D31')
            plt.tight_layout()

            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            chart_file = discord.File(buf, filename='ram_chart.png')
            embed.set_image(url='attachment://ram_chart.png')
        except Exception as e:
            print(f"eroare generare grafic: {e}")
        finally:
            if fig is not None:
                plt.close(fig)

    if chart_file:
        await interaction.followup.send(embed=embed, file=chart_file)
    else:
        if len(ram_history) <= 1:
            embed.set_footer(text="*(colectez date pt graficul RAM, revino in cateva minute)*")
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="logs", description="vezi ultimele loguri dintr-un container")
@app_commands.describe(
    container="alege containerul",
    nr_logs="cate linii de log vrei sa vezi (max 100)"
)
@app_commands.choices(container=[
    app_commands.Choice(name="bot-github",        value="bot-github"),
    app_commands.Choice(name="cloudflare",        value="cloudflare"),
    app_commands.Choice(name="diun",              value="diun"),
    app_commands.Choice(name="homepage",          value="homepage"),
    app_commands.Choice(name="immich",            value="immich"),
    app_commands.Choice(name="jellyfin",          value="jellyfin"),
    app_commands.Choice(name="pi-hole",           value="pi-hole"),
    app_commands.Choice(name="speedtest-tracker", value="speedtest-tracker"),
    app_commands.Choice(name="uptime-kuma",       value="uptime-kuma"),
    app_commands.Choice(name="website",           value="website"),
    app_commands.Choice(name="my-server",         value="my-server"),
])
async def logs(interaction: discord.Interaction, container: app_commands.Choice[str], nr_logs: int):
    if nr_logs < 1:
        await interaction.response.send_message("`nr_logs` trebuie sa fie cel putin 1.", ephemeral=True)
        return
    if nr_logs > 100:
        await interaction.response.send_message("`nr_logs` maxim este 100.", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        client = get_docker_client()
        try:
            cont = client.containers.get(container.value)
        except docker.errors.NotFound:
            await interaction.followup.send(f"containerul `{container.value}` nu a fost gasit.")
            return

        logs_bytes = cont.logs(tail=nr_logs)
        logs_str = logs_bytes.decode('utf-8', errors='replace')

        if not logs_str.strip():
            await interaction.followup.send(f"nu am gasit loguri recente in `{container.value}`.")
            return

        header = f"ultimele **{nr_logs}** loguri din `{container.value}`:\n"
        code_block = f"```\n{logs_str}\n```"
        msg = header + code_block

        if len(msg) > 2000:
            max_log_len = 2000 - len(header) - len("```\n...\n```")
            logs_str = logs_str[-max_log_len:]
            msg = header + f"```\n...\n{logs_str}\n```"

        await interaction.followup.send(msg)

    except RuntimeError as e:
        await interaction.followup.send(f"{e}")
    except Exception as e:
        await interaction.followup.send(f"eroare neasteptata: {e}")

TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN lipseste din .env!")

bot.run(TOKEN)