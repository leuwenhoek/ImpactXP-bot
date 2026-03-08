import os
import discord
import re
import psycopg2
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime, time, timezone

# --- CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
RESET_PIN = os.getenv('RESET_PIN')

# CHANNEL IDS (Update these!)
MAIN_ANNOUNCEMENT_CHANNEL_ID = os.getenv('MAIN_ANNOUNCEMENT_CHANNEL_ID')
RAMPAGE_TEXT_CHANNEL_ID = os.getenv('RAMPAGE_TEXT_CHANNEL_ID')
RAMPAGE_TASK_CHANNEL_ID = os.getenv('RAMPAGE_TASK_CHANNEL_ID') 
RESULT_CHANNEL_ID = os.getenv('RESULT_CHANNEL_ID') 
WINNER_ROLE_ID = os.getenv('WINNER_ROLE_ID')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True 

class RampageBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.vc_tracking = {}  
        self.daily_xp = {}     
        self.current_thread_id = None
        self.vc_buffer = {} 
        self.announcement_done = False

    def get_db_connection(self):
        return psycopg2.connect(DATABASE_URL, sslmode='require')

    async def setup_hook(self):
        self.daily_cycle.start()
        self.rampage_start_check.start()
        await self.tree.sync()

    def format_seconds(self, seconds):
        h, m = int(seconds // 3600), int((seconds % 3600) // 60)
        return f"{h:02d}h {m:02d}m"

    # --- MARCH 10 START ANNOUNCEMENT ---
    @tasks.loop(minutes=10)
    async def rampage_start_check(self):
        target = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now >= target and not self.announcement_done:
            channel = self.get_channel(MAIN_ANNOUNCEMENT_CHANNEL_ID)
            if channel:
                embed = discord.Embed(title="🚨 THE RAMPAGE HAS BEGUN! 🦍", color=0xFF0000)
                embed.description = "@everyone **7-Day Lock-In starts NOW.** Beast mode activated! Grind Hoollow, skills, academics + fun."
                embed.add_field(name="📅 When", value="**March 10th-17th** | VC: Rampage (10+ hrs/day)", inline=False)
                embed.add_field(name="🏆 Rewards", value="• @Rampage tag\n• Elite Rampage List\n• AI-scored ImpactXP", inline=False)
                embed.add_field(name="📋 Rules", value="• Daily tasks in thread\n• Min 10hrs VC/day", inline=False)
                embed.set_footer(text="Let's DOMINATE 💥")
                await channel.send(content="@everyone", embed=embed)
                self.announcement_done = True
                self.rampage_start_check.stop()

    def add_xp(self, user_id, seconds=0, tasks_xp=0):
        uid = str(user_id)
        if uid not in self.daily_xp: 
            self.daily_xp[uid] = {"total_seconds": 0, "task_xp": 0}
        self.daily_xp[uid]["total_seconds"] += seconds
        self.daily_xp[uid]["task_xp"] += tasks_xp
        
        db_seconds_to_add = 0
        if seconds > 0:
            self.vc_buffer[uid] = self.vc_buffer.get(uid, 0) + seconds
            if self.vc_buffer[uid] >= 3600:
                hours = int(self.vc_buffer[uid] // 3600)
                db_seconds_to_add = hours * 3600
                self.vc_buffer[uid] %= 3600

        if tasks_xp > 0 or db_seconds_to_add > 0:
            try:
                conn = self.get_db_connection()
                cur = conn.cursor()
                cur.execute("""INSERT INTO rampage_stats (user_id, total_seconds, task_xp) VALUES (%s, %s, %s)
                               ON CONFLICT (user_id) DO UPDATE SET total_seconds = rampage_stats.total_seconds + EXCLUDED.total_seconds,
                               task_xp = rampage_stats.task_xp + EXCLUDED.task_xp;""", (uid, db_seconds_to_add, tasks_xp))
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"DB Error: {e}")

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=timezone.utc))
    async def daily_cycle(self):
        now = datetime.now(timezone.utc)
        res_channel = self.get_channel(RESULT_CHANNEL_ID)
        main_ann_channel = self.get_channel(MAIN_ANNOUNCEMENT_CHANNEL_ID)
        text_channel = self.get_channel(RAMPAGE_TEXT_CHANNEL_ID)
        
        # --- MARCH 18: FINALE LOGIC ---
        if now.day == 18 and now.month == 3:
            conn = self.get_db_connection(); cur = conn.cursor()
            cur.execute("SELECT * FROM rampage_stats"); rows = cur.fetchall()
            cur.close(); conn.close()
            
            if rows:
                winner_data = max(rows, key=lambda x: ((x[1]/3600)*3) + x[2])
                winner_member = main_ann_channel.guild.get_member(int(winner_data[0]))
                
                if winner_member:
                    role = main_ann_channel.guild.get_role(WINNER_ROLE_ID)
                    if role: await winner_member.add_roles(role)
                    
                    winner_hrs = int(winner_data[1] // 3600)
                    total_xp = ((winner_data[1]/3600)*3) + winner_data[2]

                    embed = discord.Embed(title="🔱 RAMPAGE CHAMPION CROWNED! 🏆", color=0xFFD700)
                    embed.description = f"{winner_member.mention} **DOMINATED** the 7-day beast mode!\n**Ultimate Rampage Champion** 🦍💥"
                    embed.add_field(name="📊 Winning Stats", value=f"• **VC Hours:** {winner_hrs}h\n• **Total Score:** {total_xp:.2f} XP", inline=False)
                    embed.set_footer(text="GG to all beasts! | Next grind soon! 🚀")
                    await main_ann_channel.send(content="@everyone", embed=embed)
            
            self.daily_cycle.stop()
            return

        # --- REGULAR DAILY CYCLE ---
        if self.current_thread_id:
            try:
                old = self.get_channel(self.current_thread_id)
                if old: await old.edit(archived=True, locked=True)
            except: pass

        if res_channel:
            # Post Daily Results
            d_embed = discord.Embed(title="🏆 Daily Results", color=0xFF4500)
            sorted_d = sorted(self.daily_xp.items(), key=lambda x: ((x[1]['total_seconds']/3600)*3)+x[1]['task_xp'], reverse=True)
            for i, (uid, data) in enumerate(sorted_d[:5], 1):
                d_embed.add_field(name=f"#{i}", value=f"<@{uid}> - XP: `{((data['total_seconds']/3600)*3)+data['task_xp']:.2f}`", inline=False)
            await res_channel.send(embed=d_embed)

            # Post All-Time Standings
            conn = self.get_db_connection(); cur = conn.cursor()
            cur.execute("SELECT * FROM rampage_stats"); rows = cur.fetchall()
            cur.close(); conn.close()
            if rows:
                a_embed = discord.Embed(title="🔱 Current All-Time Standings", color=0xFFD700)
                sorted_a = sorted(rows, key=lambda x: ((x[1]/3600)*3) + x[2], reverse=True)
                for i, row in enumerate(sorted_a[:5], 1):
                    a_embed.add_field(name=f"#{i}", value=f"<@{row[0]}>: `{((row[1]/3600)*3)+row[2]:.2f}` XP", inline=False)
                await res_channel.send(embed=a_embed)

        self.daily_xp.clear()

        # Create New Thread
        task_chan = self.get_channel(RAMPAGE_TASK_CHANNEL_ID)
        if task_chan:
            t_name = f"task list - {now.strftime('%d %b')}"
            if isinstance(task_chan, discord.ForumChannel):
                p = await task_chan.create_thread(name=t_name, content="🦍 Post work here!")
                self.current_thread_id = p.thread.id
            else:
                th = await task_chan.create_thread(name=t_name, type=discord.ChannelType.public_thread)
                self.current_thread_id = th.id

            if text_channel:
                msg = (
                    f"🔥 **Thread is OPEN now!**\n"
                    f"Share your work in this format inside <#{self.current_thread_id}>:\n"
                    "```\n1.\n2.\n3.\n4.\n```"
                )
                await text_channel.send(msg)

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel is None and after.channel is not None:
        bot.vc_tracking[member.id] = datetime.now()
    elif before.channel is not None and after.channel is None:
        join_time = bot.vc_tracking.pop(member.id, None)
        if join_time:
            bot.add_xp(member.id, seconds=(datetime.now() - join_time).total_seconds())

@bot.event
async def on_message(message):
    if message.author.bot: return
    if bot.current_thread_id and message.channel.id == bot.current_thread_id:
        nums = re.findall(r'\d+', message.content)
        if nums:
            bot.add_xp(message.author.id, tasks_xp=int(nums[-1]) * 5)
            await message.add_reaction("📈")
    await bot.process_commands(message)

@bot.command(name="lb")
async def leaderboard(ctx):
    active_display = {uid: data.copy() for uid, data in bot.daily_xp.items()}
    for uid, join_time in bot.vc_tracking.items():
        uid_s = str(uid)
        if uid_s not in active_display: active_display[uid_s] = {"total_seconds": 0, "task_xp": 0}
        active_display[uid_s]["total_seconds"] += (datetime.now() - join_time).total_seconds()
    sorted_users = sorted(active_display.items(), key=lambda x: ((x[1]['total_seconds']/3600)*3)+x[1]['task_xp'], reverse=True)
    embed = discord.Embed(title="🦍 Daily Rankings", color=0x2ecc71)
    for i, (uid, data) in enumerate(sorted_users[:10], 1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User:{uid}"
        xp = ((data['total_seconds']/3600)*3) + data['task_xp']
        embed.add_field(name=f"{i}. {name}", value=f"XP: `{xp:.2f}`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="all_time")
async def all_time(ctx):
    conn = bot.get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT * FROM rampage_stats"); rows = cur.fetchall()
    cur.close(); conn.close()
    if not rows: return await ctx.send("Empty.")
    sorted_all = sorted(rows, key=lambda x: ((x[1]/3600)*3) + x[2], reverse=True)
    embed = discord.Embed(title="🔱 Hall of Fame", color=0xffd700)
    for i, (uid, seconds, task_xp) in enumerate(sorted_all[:15], 1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User:{uid}"
        total = ((seconds/3600)*3) + task_xp
        embed.add_field(name=f"{i}. {name}", value=f"Total: `{total:.2f}` XP", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="start_day")
@commands.has_permissions(administrator=True)
async def start_day(ctx):
    await bot.daily_cycle()
    await ctx.send("✅ Cycle forced.")

@bot.command(name="reset")
@commands.has_permissions(administrator=True)
async def reset_data(ctx, pin: str):
    if pin == RESET_PIN:
        # Clear the database
        try:
            conn = bot.get_db_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM rampage_stats")
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            await ctx.send(f"DB Error: {e}")
            return
        # Clear the in-memory daily ranking
        bot.daily_xp.clear()
        await ctx.send("💥 Neon Database and daily ranking cleared.")
    else:
        await ctx.send("❌ Incorrect PIN. Reset aborted.")

if TOKEN: bot.run(TOKEN)