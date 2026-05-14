import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv
from collections import defaultdict
import asyncio

# تحميل متغيرات البيئة
load_dotenv()

# إعدادات البوت الأساسية - بدون مشاكل logging
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=os.getenv('PREFIX', '!'), intents=intents)

# ملفات البيانات
DB_FILE = 'tickets_config.json'
LOGS_FILE = 'tickets_logs.json'
STATS_FILE = 'tickets_stats.json'

# متغيرات عامة
spam_tracker = defaultdict(list)
ticket_creation_times = {}

# ==================== FUNCTIONS ====================

def load_data(file_name):
    """تحميل البيانات من ملف JSON"""
    try:
        if os.path.exists(file_name):
            with open(file_name, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"❌ خطأ في تحميل {file_name}: {e}")
    
    if file_name == DB_FILE:
        return {
            "tickets": {},
            "guild_configs": {},
            "closed_tickets": [],
            "blocked_users": [],
            "feedbacks": []
        }
    elif file_name == LOGS_FILE:
        return {"logs": []}
    elif file_name == STATS_FILE:
        return {"total_opened": 0, "total_closed": 0, "response_times": []}
    
    return {}

def save_data(file_name, data):
    """حفظ البيانات في ملف JSON"""
    try:
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"❌ خطأ في حفظ {file_name}: {e}")
        return False

async def check_spam(user_id: int, max_per_minute: int = 3) -> bool:
    """فحص إذا كان المستخدم يسبب spam"""
    now = datetime.now()
    
    # احذف الطلبات القديمة
    spam_tracker[user_id] = [
        t for t in spam_tracker[user_id] 
        if (now - t).seconds < 60
    ]
    
    if len(spam_tracker[user_id]) >= max_per_minute:
        return True
    
    spam_tracker[user_id].append(now)
    return False

def log_ticket_action(ticket_id: str, action: str, user: str, details: str = ""):
    """تسجيل جميع إجراءات التذاكر"""
    logs = load_data(LOGS_FILE)
    logs["logs"].append({
        "timestamp": datetime.now().isoformat(),
        "ticket_id": ticket_id,
        "action": action,
        "user": user,
        "details": details
    })
    save_data(LOGS_FILE, logs)

def update_stats(action: str, response_time: int = 0):
    """تحديث الإحصائيات"""
    stats = load_data(STATS_FILE)
    if action == "opened":
        stats["total_opened"] += 1
    elif action == "closed":
        stats["total_closed"] += 1
        if response_time > 0:
            stats.setdefault("response_times", []).append(response_time)
    save_data(STATS_FILE, stats)

# ==================== MODALS ====================

class TicketFeedbackModal(discord.ui.Modal, title="تقييم الخدمة"):
    """نموذج التقييم"""
    
    rating = discord.ui.TextInput(
        label="التقييم (1-5)",
        placeholder="أدخل رقم من 1 إلى 5",
        min_length=1,
        max_length=1
    )
    
    feedback = discord.ui.TextInput(
        label="ملاحظاتك",
        placeholder="أخبرنا عن تجربتك...",
        required=False,
        style=discord.TextStyle.long,
        max_length=500
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            rating = int(self.rating.value)
            if rating < 1 or rating > 5:
                raise ValueError()
            
            config = load_data(DB_FILE)
            feedback_data = {
                "user": str(interaction.user),
                "rating": rating,
                "feedback": self.feedback.value or "لا توجد ملاحظات",
                "timestamp": datetime.now().isoformat()
            }
            
            if "feedbacks" not in config:
                config["feedbacks"] = []
            
            config["feedbacks"].append(feedback_data)
            save_data(DB_FILE, config)
            
            embed = discord.Embed(
                title="✅ شكراً لتقييمك!",
                description=f"⭐ التقييم: {rating}/5",
                color=discord.Color.gold()
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            print(f"⭐ تقييم جديد: {rating}/5 من {interaction.user}")
            
        except ValueError:
            await interaction.response.send_message(
                "❌ أدخل رقماً بين 1 و 5",
                ephemeral=True
            )

# ==================== VIEWS ====================

class TicketSelect(discord.ui.Select):
    def __init__(self, tickets: dict, guild_id: int):
        self.tickets_data = tickets
        self.guild_id = guild_id
        
        options = []
        for ticket_id, ticket_info in list(tickets.items())[:25]:
            options.append(
                discord.SelectOption(
                    label=ticket_info['name'][:100],
                    emoji=ticket_info['emoji'],
                    value=ticket_id,
                    description=ticket_info.get('description', '')[:100]
                )
            )
        
        super().__init__(
            placeholder="🎫 اختر نوع التذكرة...",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        config = load_data(DB_FILE)
        
        # التحقق من spam
        if await check_spam(interaction.user.id, max_per_minute=3):
            await interaction.response.send_message(
                "⚠️ أنت تفتح تذاكر بسرعة كبيرة! انتظر قليلاً.",
                ephemeral=True
            )
            return
        
        # التحقق من حظر المستخدم
        if interaction.user.id in config.get("blocked_users", []):
            await interaction.response.send_message(
                "❌ أنت محظور من فتح تذاكر!",
                ephemeral=True
            )
            return
        
        # التحقق من عدد التذاكر المفتوحة
        guild = bot.get_guild(self.guild_id)
        open_tickets = [c for c in guild.channels if isinstance(c, discord.TextChannel) 
                       and c.topic and str(interaction.user.id) in c.topic]
        
        if len(open_tickets) >= 3:
            await interaction.response.send_message(
                "⚠️ لديك 3 تذاكر مفتوحة بالفعل! أغلق واحدة أولاً.",
                ephemeral=True
            )
            return
        
        ticket_id = self.values[0]
        ticket_info = config['tickets'].get(ticket_id)
        
        if not ticket_info:
            await interaction.response.send_message("❌ التذكرة غير موجودة", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            category_name = f"🎫 {ticket_info['name']}"
            category = None
            
            for cat in guild.categories:
                if cat.name == category_name:
                    category = cat
                    break
            
            if not category:
                category = await guild.create_category(category_name)
                print(f"✅ فئة جديدة: {category_name}")
            
            ticket_number = len([c for c in category.channels]) + 1
            channel_name = f"{ticket_info['emoji']}-{interaction.user.name[:12]}-{ticket_number}".lower()[:32]
            
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                topic=f"User:{interaction.user.id}|Ticket:{ticket_id}|Time:{datetime.now().isoformat()}"
            )
            
            await channel.set_permissions(
                interaction.user,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True
            )
            await channel.set_permissions(guild.default_role, view_channel=False)
            
            # رسالة ترحيب
            embed = discord.Embed(
                title=f"{ticket_info['emoji']} {ticket_info['name']}",
                description=f"مرحباً {interaction.user.mention}! 👋\n\n" + 
                           ticket_info.get('welcome_message', 'شكراً لتواصلك معنا!'),
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.add_field(
                name="📋 تفاصيل التذكرة",
                value=f"**النوع:** {ticket_info['name']}\n" +
                      f"**المستخدم:** {interaction.user.mention}\n" +
                      f"**الوقت:** {datetime.now().strftime('%d/%m/%Y - %H:%M')}",
                inline=False
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.set_footer(text="استخدم الأزرار للتحكم")
            
            await channel.send(embed=embed, view=TicketActionView(guild.id, channel.id))
            
            # تسجيل الإجراء
            log_ticket_action(ticket_id, "opened", str(interaction.user), channel.name)
            update_stats("opened")
            ticket_creation_times[channel.id] = datetime.now()
            
            await interaction.followup.send(
                f"✅ تم فتح التذكرة!\n{channel.mention}",
                ephemeral=True
            )
            
            print(f"✅ تذكرة جديدة: {channel_name}")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ ليس لدي أذونات كافية!", ephemeral=True)
        except Exception as e:
            print(f"❌ خطأ: {e}")
            await interaction.followup.send(f"❌ خطأ: {str(e)}", ephemeral=True)

class TicketActionView(discord.ui.View):
    def __init__(self, guild_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.channel_id = channel_id
    
    @discord.ui.button(label="إغلاق", style=discord.ButtonStyle.red, emoji="🔒", custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = bot.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ القناة حذفت", ephemeral=True)
            return
        
        config = load_data(DB_FILE)
        
        # حساب وقت الرد
        response_time = 0
        if self.channel_id in ticket_creation_times:
            response_time = int((datetime.now() - ticket_creation_times[self.channel_id]).total_seconds() / 60)
        
        # حفظ معلومات التذكرة المغلقة
        closed_info = {
            "channel_name": channel.name,
            "closed_by": str(interaction.user),
            "closed_at": datetime.now().isoformat(),
            "response_time_minutes": response_time
        }
        
        if "closed_tickets" not in config:
            config["closed_tickets"] = []
        config["closed_tickets"].append(closed_info)
        
        save_data(DB_FILE, config)
        
        # طلب التقييم
        await interaction.response.send_modal(TicketFeedbackModal())
        
        log_ticket_action(channel.name, "closed", str(interaction.user))
        update_stats("closed", response_time)
        
        # حذف القناة
        await asyncio.sleep(2)
        await channel.delete(reason=f"أغلقت من {interaction.user}")
        print(f"🔒 تم إغلاق: {channel.name} (الوقت: {response_time} دقيقة)")
    
    @discord.ui.button(label="إعادة فتح", style=discord.ButtonStyle.green, emoji="🔓", custom_id="reopen_ticket")
    async def reopen_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = bot.get_channel(self.channel_id)
        if channel:
            await interaction.response.defer()
            await channel.set_permissions(interaction.user, send_messages=True)
            embed = discord.Embed(
                title="🔓 تم إعادة فتح التذكرة",
                color=discord.Color.green()
            )
            await channel.send(embed=embed)

    @discord.ui.button(label="حذف", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="delete_ticket")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = bot.get_channel(self.channel_id)
        if channel:
            await interaction.response.defer()
            log_ticket_action(channel.name, "deleted", str(interaction.user))
            await asyncio.sleep(1)
            await channel.delete(reason=f"حذفت من {interaction.user}")

# ==================== SLASH COMMANDS ====================

@bot.tree.command(name="add_ticket", description="🎫 إضافة تذكرة جديدة")
@app_commands.describe(
    ticket_name="اسم التذكرة",
    emoji="إيموجي",
    ticket_id="معرف فريد"
)
@app_commands.checks.has_permissions(administrator=True)
async def add_ticket(
    interaction: discord.Interaction,
    ticket_name: str,
    emoji: str,
    ticket_id: str
):
    config = load_data(DB_FILE)
    
    if ticket_id in config['tickets']:
        embed = discord.Embed(
            title="❌ معرف مكرر",
            description=f"`{ticket_id}` موجود بالفعل!",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    if len(config['tickets']) >= 100:
        await interaction.response.send_message("⚠️ وصلت للحد الأقصى!", ephemeral=True)
        return
    
    config['tickets'][ticket_id] = {
        'name': ticket_name,
        'emoji': emoji,
        'description': 'لا يوجد وصف',
        'welcome_message': 'شكراً لتواصلك معنا!',
        'created_at': datetime.now().isoformat(),
        'created_by': str(interaction.user)
    }
    
    save_data(DB_FILE, config)
    
    embed = discord.Embed(
        title="✅ تم إضافة التذكرة",
        color=discord.Color.green()
    )
    embed.add_field(name="الاسم", value=f"{emoji} {ticket_name}", inline=False)
    embed.add_field(name="المعرف", value=f"`{ticket_id}`", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    print(f"✅ تذكرة جديدة: {ticket_name}")

@bot.tree.command(name="list_tickets", description="📋 عرض جميع التذاكر")
async def list_tickets(interaction: discord.Interaction):
    config = load_data(DB_FILE)
    
    if not config['tickets']:
        await interaction.response.send_message("❌ لا توجد تذاكر!", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📋 قائمة التذاكر",
        color=discord.Color.blue()
    )
    
    for i, (tid, tinfo) in enumerate(config['tickets'].items(), 1):
        embed.add_field(
            name=f"{i}. {tinfo['emoji']} {tinfo['name']}",
            value=f"**المعرف:** `{tid}`",
            inline=False
        )
    
    embed.set_footer(text=f"المجموع: {len(config['tickets'])} / 100")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ticket_panel", description="🎫 عرض لوحة التذاكر")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_panel(interaction: discord.Interaction):
    config = load_data(DB_FILE)
    
    if not config['tickets']:
        await interaction.response.send_message("❌ لا توجد تذاكر!", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🎫 لوحة التذاكر",
        description="اختر التذكرة من القائمة 👇",
        color=discord.Color.blue()
    )
    view = discord.ui.View()
    view.add_item(TicketSelect(config['tickets'], interaction.guild_id))
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="ticket_stats", description="📊 إحصائيات التذاكر")
async def ticket_stats(interaction: discord.Interaction):
    stats = load_data(STATS_FILE)
    config = load_data(DB_FILE)
    
    total_closed = len(config.get('closed_tickets', []))
    closed_rate = (total_closed / stats['total_opened'] * 100) if stats['total_opened'] > 0 else 0
    
    embed = discord.Embed(
        title="📊 إحصائيات التذاكر",
        color=discord.Color.gold()
    )
    
    embed.add_field(name="📂 المفتوحة", value=str(stats['total_opened']), inline=True)
    embed.add_field(name="✅ المغلقة", value=str(total_closed), inline=True)
    embed.add_field(name="📈 النسبة", value=f"{closed_rate:.1f}%", inline=True)
    
    if config.get('feedbacks'):
        ratings = [f['rating'] for f in config['feedbacks']]
        avg_rating = sum(ratings) / len(ratings)
        embed.add_field(name="⭐ التقييم", value=f"{avg_rating:.1f}/5", inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==================== BOT EVENTS ====================

@bot.event
async def on_ready():
    print("╔════════════════════════════════════════╗")
    print("║  ✅ البوت جاهز للعمل! 🚀             ║")
    print(f"║  👤 البوت: {bot.user}          ║")
    print(f"║  📊 السيرفرات: {len(bot.guilds)}                   ║")
    print("╚════════════════════════════════════════╝")
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ تم مزامنة {len(synced)} أوامر")
    except Exception as e:
        print(f"❌ خطأ: {e}")

# ==================== RUN BOT ====================

TOKEN = os.getenv('TOKEN')

if not TOKEN:
    print("❌ لم يتم العثور على TOKEN في .env")
    print("أضف: TOKEN=your_token_here")
    exit(1)

try:
    print("🚀 جاري تشغيل البوت...")
    bot.run(TOKEN)
except KeyboardInterrupt:
    print("❌ تم إيقاف البوت")
except Exception as e:
    print(f"❌ خطأ: {e}")
