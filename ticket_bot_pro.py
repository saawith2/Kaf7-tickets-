import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv
import logging
import asyncio

# تحميل متغيرات البيئة
load_dotenv()

# إعدادات التسجيل الاحترافية
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('🎫 TicketBot Pro')

# إعدادات البوت
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=os.getenv('PREFIX', '!'), intents=intents)

# ملفات البيانات
DB_FILE = os.getenv('DB_PATH', 'tickets_config.json')
LOGS_FILE = 'tickets_logs.json'
STATS_FILE = 'tickets_stats.json'

def load_data(file_name):
    """تحميل البيانات من ملف JSON"""
    try:
        if os.path.exists(file_name):
            with open(file_name, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"خطأ في تحميل {file_name}: {e}")
    
    if file_name == DB_FILE:
        return {
            "tickets": {},
            "guild_configs": {},
            "closed_tickets": [],
            "blocked_users": []
        }
    elif file_name == LOGS_FILE:
        return {"logs": []}
    elif file_name == STATS_FILE:
        return {"total_opened": 0, "total_closed": 0, "average_response_time": 0}
    
    return {}

def save_data(file_name, data):
    """حفظ البيانات في ملف JSON"""
    try:
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ {file_name}: {e}")
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

def update_stats(action: str):
    """تحديث الإحصائيات"""
    stats = load_data(STATS_FILE)
    if action == "opened":
        stats["total_opened"] += 1
    elif action == "closed":
        stats["total_closed"] += 1
    save_data(STATS_FILE, stats)

# ==================== MODALS ====================

class TicketFeedbackModal(discord.ui.Modal, title="تقييم الخدمة"):
    """نموذج التقييم بعد إغلاق التذكرة"""
    
    rating = discord.ui.TextInput(
        label="التقييم (1-5)",
        placeholder="أدخل رقم من 1 إلى 5",
        min_length=1,
        max_length=1
    )
    
    feedback = discord.ui.TextInput(
        label="ملاحظاتك (اختياري)",
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
            logger.info(f"⭐ تقييم جديد: {rating}/5 من {interaction.user}")
            
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
                    description=ticket_info.get('description', 'لا يوجد وصف')[:100]
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
                logger.info(f"✅ فئة جديدة: {category_name}")
            
            ticket_number = len([c for c in category.channels]) + 1
            channel_name = f"{ticket_info['emoji']}-{interaction.user.name[:12]}-{ticket_number}".lower()[:32]
            
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                topic=f"User:{interaction.user.id} | Ticket:{ticket_id} | Time:{datetime.now().isoformat()}"
            )
            
            await channel.set_permissions(
                interaction.user,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True
            )
            await channel.set_permissions(guild.default_role, view_channel=False)
            
            # رسالة ترحيب مفصلة
            embed = discord.Embed(
                title=f"{ticket_info['emoji']} تذكرة {ticket_info['name']}",
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
            embed.add_field(
                name="ℹ️ ملاحظة",
                value="سيتم الرد على تذكرتك قريباً. يرجى الانتظار.",
                inline=False
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.set_footer(text="استخدم الأزرار أدناه للتحكم")
            
            await channel.send(embed=embed, view=TicketActionView(guild.id, channel.id))
            
            # تسجيل الإجراء
            log_ticket_action(ticket_id, "opened", str(interaction.user), channel.name)
            update_stats("opened")
            
            await interaction.followup.send(
                f"✅ تم فتح التذكرة!\n{channel.mention}",
                ephemeral=True
            )
            
            logger.info(f"✅ تذكرة جديدة: {channel_name} من {interaction.user}")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ ليس لدي أذونات كافية!", ephemeral=True)
        except Exception as e:
            logger.error(f"خطأ: {e}")
            await interaction.followup.send(f"❌ خطأ: {str(e)}", ephemeral=True)

class TicketButtonView(discord.ui.View):
    def __init__(self, tickets: dict, guild_id: int):
        super().__init__(persistent=False)
        self.tickets_data = tickets
        self.guild_id = guild_id
        
        for i, (ticket_id, ticket_info) in enumerate(list(tickets.items())[:5]):
            button = discord.ui.Button(
                label=ticket_info['name'][:80],
                emoji=ticket_info['emoji'],
                style=discord.ButtonStyle.primary,
                custom_id=f"ticket_{ticket_id}"
            )
            button.callback = self.button_callback(ticket_id, guild_id)
            self.add_item(button)
    
    def button_callback(self, ticket_id: str, guild_id: int):
        async def callback(interaction: discord.Interaction):
            config = load_data(DB_FILE)
            
            if interaction.user.id in config.get("blocked_users", []):
                await interaction.response.send_message("❌ أنت محظور!", ephemeral=True)
                return
            
            guild = bot.get_guild(guild_id)
            open_tickets = [c for c in guild.channels if isinstance(c, discord.TextChannel) 
                           and c.topic and str(interaction.user.id) in c.topic]
            
            if len(open_tickets) >= 3:
                await interaction.response.send_message(
                    "⚠️ لديك 3 تذاكر مفتوحة!",
                    ephemeral=True
                )
                return
            
            ticket_info = config['tickets'].get(ticket_id)
            if not ticket_info:
                await interaction.response.send_message("❌ غير موجود", ephemeral=True)
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
                
                ticket_number = len([c for c in category.channels]) + 1
                channel_name = f"{ticket_info['emoji']}-{interaction.user.name[:12]}-{ticket_number}".lower()[:32]
                
                channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    topic=f"User:{interaction.user.id} | Ticket:{ticket_id} | Time:{datetime.now().isoformat()}"
                )
                
                await channel.set_permissions(interaction.user, view_channel=True, send_messages=True)
                await channel.set_permissions(guild.default_role, view_channel=False)
                
                embed = discord.Embed(
                    title=f"{ticket_info['emoji']} {ticket_info['name']}",
                    description=ticket_info.get('welcome_message', 'أهلا!'),
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                
                await channel.send(embed=embed, view=TicketActionView(guild.id, channel.id))
                
                log_ticket_action(ticket_id, "opened", str(interaction.user), channel.name)
                update_stats("opened")
                
                await interaction.followup.send(f"✅ تم! {channel.mention}", ephemeral=True)
                
            except Exception as e:
                logger.error(f"خطأ: {e}")
                await interaction.followup.send(f"❌ خطأ: {e}", ephemeral=True)
        
        return callback

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
        
        # حفظ معلومات التذكرة المغلقة
        closed_info = {
            "channel_name": channel.name,
            "closed_by": str(interaction.user),
            "closed_at": datetime.now().isoformat(),
            "duration": "معلومة",
            "message_count": len(await channel.history(limit=None).flatten() if hasattr(channel.history(limit=None), 'flatten') else [])
        }
        
        if "closed_tickets" not in config:
            config["closed_tickets"] = []
        config["closed_tickets"].append(closed_info)
        
        save_data(DB_FILE, config)
        
        # طلب التقييم
        embed = discord.Embed(
            title="📋 هل تريد تقييم الخدمة؟",
            description="ساعدنا على التحسن بتقييمك!",
            color=discord.Color.gold()
        )
        
        await interaction.response.send_modal(TicketFeedbackModal())
        
        log_ticket_action(channel.name, "closed", str(interaction.user))
        update_stats("closed")
        
        await asyncio.sleep(2)
        await channel.delete(reason=f"أغلقت من {interaction.user}")
        logger.info(f"🔒 تم إغلاق: {channel.name}")
    
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
            log_ticket_action(channel.name, "reopened", str(interaction.user))

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
    ticket_name="اسم التذكرة (مثال: تقرير مشكلة)",
    emoji="إيموجي (مثال: 🐛)",
    ticket_id="معرف فريد (مثال: bug)",
    description="وصف التذكرة (اختياري)",
    welcome_message="رسالة الترحيب (اختياري)"
)
@app_commands.checks.has_permissions(administrator=True)
async def add_ticket(
    interaction: discord.Interaction,
    ticket_name: str,
    emoji: str,
    ticket_id: str,
    description: Optional[str] = None,
    welcome_message: Optional[str] = None
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
        embed = discord.Embed(
            title="⚠️ وصلت للحد الأقصى",
            description="الحد الأقصى 100 تذكرة!",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    config['tickets'][ticket_id] = {
        'name': ticket_name,
        'emoji': emoji,
        'description': description or 'لا يوجد وصف',
        'welcome_message': welcome_message or 'شكراً لتواصلك معنا!',
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
    if description:
        embed.add_field(name="الوصف", value=description, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    logger.info(f"✅ تذكرة جديدة: {ticket_name}")

@bot.tree.command(name="list_tickets", description="📋 عرض جميع التذاكر")
async def list_tickets(interaction: discord.Interaction):
    config = load_data(DB_FILE)
    
    if not config['tickets']:
        embed = discord.Embed(
            title="❌ لا توجد تذاكر",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📋 قائمة التذاكر",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    for i, (tid, tinfo) in enumerate(config['tickets'].items(), 1):
        value = f"**المعرف:** `{tid}`\n**الوصف:** {tinfo.get('description', 'N/A')}"
        embed.add_field(
            name=f"{i}. {tinfo['emoji']} {tinfo['name']}",
            value=value,
            inline=False
        )
    
    embed.set_footer(text=f"المجموع: {len(config['tickets'])} / 100")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="delete_ticket", description="🗑️ حذف تذكرة")
@app_commands.describe(ticket_id="معرف التذكرة")
@app_commands.checks.has_permissions(administrator=True)
async def delete_ticket(interaction: discord.Interaction, ticket_id: str):
    config = load_data(DB_FILE)
    
    if ticket_id not in config['tickets']:
        await interaction.response.send_message("❌ غير موجودة!", ephemeral=True)
        return
    
    ticket = config['tickets'].pop(ticket_id)
    save_data(DB_FILE, config)
    
    embed = discord.Embed(
        title="✅ تم الحذف",
        description=f"{ticket['emoji']} {ticket['name']}",
        color=discord.Color.green()
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    logger.info(f"🗑️ حذفت: {ticket['name']}")

@bot.tree.command(name="ticket_panel", description="🎫 عرض لوحة التذاكر")
@app_commands.describe(panel_type="dropdown أو buttons")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_panel(interaction: discord.Interaction, panel_type: str = "dropdown"):
    config = load_data(DB_FILE)
    
    if not config['tickets']:
        await interaction.response.send_message("❌ لا توجد تذاكر!", ephemeral=True)
        return
    
    ptype = panel_type.lower().strip()
    
    if ptype == "dropdown":
        embed = discord.Embed(
            title="🎫 لوحة التذاكر",
            description="اختر التذكرة من القائمة 👇",
            color=discord.Color.blue()
        )
        view = discord.ui.View()
        view.add_item(TicketSelect(config['tickets'], interaction.guild_id))
        await interaction.response.send_message(embed=embed, view=view)
        
    elif ptype == "buttons":
        embed = discord.Embed(
            title="🎫 لوحة التذاكر",
            description="اختر التذكرة 👇",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(
            embed=embed,
            view=TicketButtonView(config['tickets'], interaction.guild_id)
        )
    else:
        await interaction.response.send_message("❌ استخدم: dropdown أو buttons", ephemeral=True)

@bot.tree.command(name="edit_ticket", description="✏️ تعديل تذكرة")
@app_commands.describe(
    ticket_id="المعرف",
    new_name="الاسم الجديد",
    new_emoji="الإيموجي الجديد",
    new_description="الوصف الجديد"
)
@app_commands.checks.has_permissions(administrator=True)
async def edit_ticket(
    interaction: discord.Interaction,
    ticket_id: str,
    new_name: Optional[str] = None,
    new_emoji: Optional[str] = None,
    new_description: Optional[str] = None
):
    config = load_data(DB_FILE)
    
    if ticket_id not in config['tickets']:
        await interaction.response.send_message("❌ غير موجودة!", ephemeral=True)
        return
    
    if new_name:
        config['tickets'][ticket_id]['name'] = new_name
    if new_emoji:
        config['tickets'][ticket_id]['emoji'] = new_emoji
    if new_description:
        config['tickets'][ticket_id]['description'] = new_description
    
    save_data(DB_FILE, config)
    
    ticket = config['tickets'][ticket_id]
    embed = discord.Embed(
        title="✅ تم التعديل",
        description=f"{ticket['emoji']} {ticket['name']}",
        color=discord.Color.green()
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ticket_stats", description="📊 إحصائيات التذاكر")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_stats(interaction: discord.Interaction):
    stats = load_data(STATS_FILE)
    config = load_data(DB_FILE)
    
    total_closed = len(config.get('closed_tickets', []))
    closed_rate = (total_closed / stats['total_opened'] * 100) if stats['total_opened'] > 0 else 0
    
    embed = discord.Embed(
        title="📊 إحصائيات التذاكر",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    
    embed.add_field(name="📂 التذاكر المفتوحة", value=str(stats['total_opened']), inline=True)
    embed.add_field(name="✅ المغلقة", value=str(total_closed), inline=True)
    embed.add_field(name="📈 نسبة الإغلاق", value=f"{closed_rate:.1f}%", inline=True)
    embed.add_field(name="📋 عدد أنواع التذاكر", value=str(len(config['tickets'])), inline=True)
    
    if config.get('feedbacks'):
        ratings = [f['rating'] for f in config['feedbacks']]
        avg_rating = sum(ratings) / len(ratings)
        embed.add_field(name="⭐ متوسط التقييم", value=f"{avg_rating:.1f}/5", inline=True)
    
    embed.set_footer(text="آخر تحديث")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="block_user", description="🚫 حظر مستخدم من التذاكر")
@app_commands.describe(user="المستخدم")
@app_commands.checks.has_permissions(administrator=True)
async def block_user(interaction: discord.Interaction, user: discord.User):
    config = load_data(DB_FILE)
    
    if "blocked_users" not in config:
        config["blocked_users"] = []
    
    if user.id not in config["blocked_users"]:
        config["blocked_users"].append(user.id)
        save_data(DB_FILE, config)
        
        embed = discord.Embed(
            title="🚫 تم الحظر",
            description=f"{user.mention} محظور من فتح تذاكر",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ المستخدم محظور بالفعل!", ephemeral=True)

@bot.tree.command(name="unblock_user", description="✅ إلغاء حظر مستخدم")
@app_commands.describe(user="المستخدم")
@app_commands.checks.has_permissions(administrator=True)
async def unblock_user(interaction: discord.Interaction, user: discord.User):
    config = load_data(DB_FILE)
    
    if user.id in config.get("blocked_users", []):
        config["blocked_users"].remove(user.id)
        save_data(DB_FILE, config)
        
        embed = discord.Embed(
            title="✅ تم إلغاء الحظر",
            description=f"{user.mention} أصبح بإمكانه فتح تذاكر",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ لم يكن محظوراً!", ephemeral=True)

@bot.tree.command(name="ticket_logs", description="📝 عرض سجل التذاكر")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_logs(interaction: discord.Interaction, limit: Optional[int] = 10):
    logs = load_data(LOGS_FILE)
    
    if not logs.get('logs'):
        await interaction.response.send_message("❌ لا توجد سجلات!", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📝 سجل التذاكر",
        color=discord.Color.blue()
    )
    
    recent_logs = logs['logs'][-limit:]
    
    for log in reversed(recent_logs):
        timestamp = datetime.fromisoformat(log['timestamp']).strftime('%H:%M - %d/%m')
        value = f"**الإجراء:** {log['action']}\n**المستخدم:** {log['user']}\n**الوقت:** {timestamp}"
        embed.add_field(
            name=f"🎫 {log['ticket_id']}",
            value=value,
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_ready():
    logger.info("╔════════════════════════════════════════════════╗")
    logger.info("║                                                ║")
    logger.info(f"║   ✅ البوت الخنفشاري جاهز للعمل! 🚀            ║")
    logger.info(f"║   👤 البوت: {bot.user}           ║")
    logger.info(f"║   📊 السيرفرات: {len(bot.guilds)}                          ║")
    logger.info("║                                                ║")
    logger.info("╚════════════════════════════════════════════════╝")
    
    try:
        synced = await bot.tree.sync()
        logger.info(f"✅ تم مزامنة {len(synced)} أوامر 🎯")
    except Exception as e:
        logger.error(f"❌ خطأ في المزامنة: {e}")

# تشغيل البوت
TOKEN = os.getenv('TOKEN')

if not TOKEN:
    logger.error("❌ لم يتم العثور على TOKEN!")
    exit(1)

try:
    bot.run(TOKEN)
except KeyboardInterrupt:
    logger.info("❌ تم إيقاف البوت")
except Exception as e:
    logger.error(f"❌ خطأ: {e}")
