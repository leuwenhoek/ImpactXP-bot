import os
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime, time, timezone

load_dotenv()
TOKEN = os.getenv('TOKEN')

# 1. SETUP INTENTS CORRECTLY
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True # This tracks VC joins/leaves

class RampageBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.vc_tracking = {}  
        self.daily_xp = {}     

    async def setup_hook(self):
        await self.tree.sync()
        self.midnight_report.start()

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=timezone.utc))
    async def midnight_report(self):
        self.daily_xp.clear() 
        print("Stats reset for the new day.")

bot = RampageBot()

def format_seconds(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}h {minutes:02d}m {secs:02d}s"

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    # SAFETY CHECK:
    if not intents.voice_states:
        print("WARNING: Voice State Intent is NOT enabled in code.")
    else:
        print("SUCCESS: Voice State Intent is enabled. Ready to track VC.")
    print("------")

@bot.event
async def on_voice_state_update(member, before, after):
    # LOG EVERY MOVEMENT TO TERMINAL FOR TESTING
    if before.channel is None and after.channel is not None:
        bot.vc_tracking[member.id] = datetime.now()
        print(f"DEBUG >>> {member.name} joined {after.channel.name}. Timer started.")
    
    elif before.channel is not None and after.channel is None:
        join_time = bot.vc_tracking.pop(member.id, None)
        if join_time:
            duration = (datetime.now() - join_time).total_seconds()
            if member.id not in bot.daily_xp:
                bot.daily_xp[member.id] = {"total_seconds": 0, "task_xp": 0}
            bot.daily_xp[member.id]["total_seconds"] += duration
            print(f"DEBUG <<< {member.name} left. Added {duration:.2f} seconds.")

@bot.command(name="lb")
async def leaderboard(ctx):
    active_display = {uid: data.copy() for uid, data in bot.daily_xp.items()}
    
    # Add LIVE sessions
    now = datetime.now()
    for uid, join_time in bot.vc_tracking.items():
        if uid not in active_display:
            active_display[uid] = {"total_seconds": 0, "task_xp": 0}
        active_display[uid]["total_seconds"] += (now - join_time).total_seconds()

    if not active_display:
        return await ctx.send("No stats yet! Join a VC to start the Rampage! 🦍")

    # Sort: (Seconds / 3600) * 3 XP per hour
    sorted_users = sorted(
        active_display.items(), 
        key=lambda x: ((x[1]['total_seconds'] / 3600) * 3) + x[1]['task_xp'], 
        reverse=True
    )

    embed = discord.Embed(title="🦍 Rampage Live Standings", color=0x5865F2)
    for i, (user_id, data) in enumerate(sorted_users, 1):
        member = ctx.guild.get_member(user_id)
        name = member.display_name if member else f"User:{user_id}"
        
        vc_xp = (data['total_seconds'] / 3600) * 3
        time_str = format_seconds(data['total_seconds'])
        status = "🟢 ACTIVE" if user_id in bot.vc_tracking else "🔴 AWAY"
        
        embed.add_field(
            name=f"{i}. {name} ({status})",
            value=f"**ImpactXP:** `{vc_xp:.2f}`\n**Time:** `{time_str}`",
            inline=False
        )
    await ctx.send(embed=embed)

if TOKEN:
    bot.run(TOKEN)