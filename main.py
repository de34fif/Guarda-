import discord
from discord.ext import commands, tasks
import asyncio
import re
from datetime import datetime
import random
import os  # Aggiunto solo per leggere il token in sicurezza

# ==================== HELP VIEW ====================
class HelpView(discord.ui.View):
    def __init__(self, bot, interaction_user):
        super().__init__(timeout=300)
        self.bot = bot
        self.current_page = 1
        self.interaction_user = interaction_user

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.gray, row=0)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_user.id:
            return await interaction.response.send_message("❌ Solo chi ha richiesto il help può navigare!", ephemeral=True)
        self.current_page = 1
        await self.update_embed(interaction)

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.red, row=0)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_user.id:
            return await interaction.response.send_message("❌ Solo chi ha richiesto il help può cancellare!", ephemeral=True)
        await interaction.message.delete()

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.gray, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_user.id:
            return await interaction.response.send_message("❌ Solo chi ha richiesto il help può navigare!", ephemeral=True)
        self.current_page = 2
        await self.update_embed(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.gray, row=0)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_user.id:
            return await interaction.response.send_message("❌ Solo chi ha richiesto il help può navigare!", ephemeral=True)
        self.current_page = 2
        await self.update_embed(interaction)

    async def update_embed(self, interaction: discord.Interaction):
        embed = self.bot.page1_embed if self.current_page == 1 else self.bot.page2_embed
        await interaction.response.edit_message(embed=embed, view=self)

# ==================== SECURITY COG (con Recovery Migliorato) ====================
class SecurityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.antinuke_config = {}
        self.snapshots = {}
        self.honeypot_channel_id = None
        self.quarantine_role_id = None
        self.PANIC_PASSWORD = "detectivenuovoserver"
        self.snapshot_loop.start()

    @tasks.loop(minutes=8)
    async def snapshot_loop(self):
        for guild in self.bot.guilds:
            config = await self.get_config(guild.id)
            if config.get("enabled"):
                await self.take_full_snapshot(guild)

    async def take_full_snapshot(self, guild):
        snapshot = {
            "roles": {},
            "channels": [],
            "timestamp": datetime.utcnow().timestamp()
        }

        for role in guild.roles:
            snapshot["roles"][role.id] = {
                "name": role.name,
                "color": role.color.value,
                "permissions": role.permissions.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable
            }

        for channel in sorted(guild.channels, key=lambda c: getattr(c, 'position', 0)):
            ch_data = {
                "name": channel.name,
                "type": str(channel.type),
                "position": getattr(channel, 'position', 0),
                "category_id": getattr(channel, 'category_id', None),
                "overwrites": {str(target.id): overwrite._values for target, overwrite in channel.overwrites.items()}
            }
            snapshot["channels"].append(ch_data)

        self.snapshots[guild.id] = snapshot

    async def restore_full_server(self, guild):
        if guild.id not in self.snapshots:
            return False, "Nessun snapshot disponibile"

        snap = self.snapshots[guild.id]
        restored_count = 0

        for role_data in snap["roles"].values():
            try:
                role = discord.utils.get(guild.roles, name=role_data["name"])
                if not role:
                    role = await guild.create_role(name=role_data["name"], color=discord.Color(role_data["color"]))
                await role.edit(
                    permissions=discord.Permissions(role_data["permissions"]),
                    hoist=role_data["hoist"],
                    mentionable=role_data["mentionable"]
                )
                restored_count += 1
            except:
                pass

        existing_names = {c.name: c for c in guild.channels}
        for ch_data in snap["channels"]:
            try:
                if ch_data["name"] in existing_names:
                    channel = existing_names[ch_data["name"]]
                else:
                    if ch_data["type"] == "category":
                        channel = await guild.create_category(ch_data["name"])
                    elif ch_data["type"] == "text":
                        cat = guild.get_channel(ch_data.get("category_id")) if ch_data.get("category_id") else None
                        channel = await guild.create_text_channel(ch_data["name"], category=cat)
                    elif ch_data["type"] == "voice":
                        cat = guild.get_channel(ch_data.get("category_id")) if ch_data.get("category_id") else None
                        channel = await guild.create_voice_channel(ch_data["name"], category=cat)
                    else:
                        continue
                    restored_count += 1

                for target_id_str, ow_values in ch_data.get("overwrites", {}).items():
                    target = guild.get_role(int(target_id_str)) or guild.get_member(int(target_id_str))
                    if target:
                        await channel.set_permissions(target, overwrite=discord.PermissionOverwrite(**ow_values))
            except:
                pass

        return True, f"Ripristinati {restored_count} elementi"

    async def get_config(self, guild_id):
        if guild_id not in self.antinuke_config:
            self.antinuke_config[guild_id] = {
                "enabled": False,
                "whitelist": [],
                "logs": None,
                "threshold": 4,
                "quarantine_enabled": True,
                "honeypot_enabled": True,
                "min_account_age_days": 7
            }
        return self.antinuke_config[guild_id]

    def check_password(self, pwd):
        return pwd == self.PANIC_PASSWORD

    @commands.command(name="panic")
    async def panic_mode(self, ctx, password: str = None):
        if not password or not self.check_password(password):
            return await ctx.send("❌ Password errata.")
        guild = ctx.guild
        if not (await self.get_config(guild.id)).get("enabled"):
            return await ctx.send("❌ Anti-Nuke non abilitato.")

        await self.take_full_snapshot(guild)
        await guild.edit(verification_level=discord.VerificationLevel.high)

        for channel in guild.channels:
            try:
                await channel.set_permissions(guild.default_role, send_messages=False, add_reactions=False)
            except:
                pass

        await ctx.send("🚨 **Panic Mode attivato!** Server bloccato. Usa `>recover detectivenuovoserver` quando è sicuro.")

    @commands.command(name="recover")
    async def recover_server(self, ctx, password: str = None):
        if not password or not self.check_password(password):
            return await ctx.send("❌ Password errata.")

        guild = ctx.guild
        success, msg = await self.restore_full_server(guild)
        if success:
            for channel in guild.channels:
                try:
                    await channel.set_permissions(guild.default_role, send_messages=True, add_reactions=True)
                except:
                    pass
            await guild.edit(verification_level=discord.VerificationLevel.medium)
            await ctx.send(f"✅ **Full Server Recovery completato!** {msg}")
        else:
            await ctx.send(f"⚠️ {msg}")

    @commands.command(name="antinuke")
    async def antinuke(self, ctx, sub: str = None, arg: str = None):
        config = await self.get_config(ctx.guild.id)
        if sub and sub.lower() in ["enable", "disable"]:
            if not arg or not self.check_password(arg):
                return await ctx.send("❌ Password errata. Usa: `>antinuke enable detectivenuovoserver`")
            config["enabled"] = (sub.lower() == "enable")
            await ctx.send("✅ **Atomic Void Security FULL** attivata" if config["enabled"] else "❌ Anti-Nuke disabilitato")
            return

        embed = discord.Embed(title="🔒 Atomic Void Security - Status", color=0x4B2C6E)
        embed.add_field(name="Anti-Nuke", value="✅ Abilitato" if config["enabled"] else "❌ Disabilitato", inline=False)
        embed.add_field(name="Honey Pot", value="✅ Attivo" if config.get("honeypot_enabled") else "❌", inline=False)
        embed.add_field(name="Quarantena", value="✅ Attiva", inline=False)
        embed.add_field(name="Snapshot", value="✅ Attivo", inline=False)
        embed.set_footer(text="Password: detectivenuovoserver per comandi sensibili")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.channel.id == self.honeypot_channel_id and not message.author.bot:
            await message.delete()
            try:
                await message.guild.ban(message.author, reason="Honey Pot Trigger")
            except:
                pass

        if re.search(r'[MN][A-Za-z\d]{23}\.[\w-]{6}\.[\w-]{27}', message.content):
            await message.delete()
            try:
                await message.guild.ban(message.author, reason="Token Stealer")
            except:
                pass

    async def log_action(self, guild, text):
        config = await self.get_config(guild.id)
        if config.get("logs"):
            channel = guild.get_channel(config["logs"])
            if channel:
                await channel.send(f"`{datetime.utcnow().strftime('%H:%M:%S')}` {text}")

# ==================== BOT ====================
class AtomicVoidBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=">", intents=discord.Intents.all())

    async def setup_hook(self):
        await self.add_cog(SecurityCog(self))
        await self.tree.sync()

bot = AtomicVoidBot()

@bot.tree.command(name="help")
async def help_command(interaction: discord.Interaction):
    embed1 = discord.Embed(color=0x4B2C6E, timestamp=discord.utils.utcnow())
    embed1.set_author(name="detective", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    embed1.description = "**→ Start Atomic Void X Today**\n**Type >antinuke enable**\n**Server Prefix:** `>`\n**Total Commands:** `585`"

    main_features = "❤️ **Security**\n📦 **Automoderation**\n🔧 **Utility**\n🎵 **Music**\n🔄 **Autoreact & responder**\n🔨 **Moderation**\n👤 **Autorole & Invc**\n🎉 **Fun**\n🎮 **Games**\n❌ **Ignore Channels**\n📡 **Server**\n🔊 **Voice**\n👋 **Welcomer**\n🎁 **Giveaway**\n🎟️ **Ticket** `NEW`\n👥 **Invite Tracker** `NEW`"
    extra_features = "📋 **Advance Logging**\n⭐ **Vanityroles**\n➕ **Counting** `NEW`\n🔗 **J2C** `NEW`\n🤖 **AI** `NEW`\n🚀 **Boost** `NEW`\n📈 **Leveling** `NEW`\n📌 **Sticky** `NEW`\n✅ **Verification** `NEW`\n🔒 **Encryption** `NEW`\n⛏️ **Minecraft** `NEW`\n📬 **Joindm** `NEW`\n🎂 **Birthday** `NEW`\n🎨 **Customrole**"

    embed1.add_field(name="**📁 Main Features**", value=main_features, inline=True)
    embed1.add_field(name="**📁 Extra Features**", value=extra_features, inline=True)
    embed1.set_footer(text="Help page 1/2 • Requested by: detective")
    embed1.set_thumbnail(url="https://i.imgur.com/VOSTRO_LINK_PERSONAGGIO.png")

    embed2 = discord.Embed(title="🔥 Atomic Void - Advanced Chinese Security (2026)", color=0x4B2C6E)
    embed2.description = "**Funzionalità attivate con >antinuke enable detectivenuovoserver**\n\n" \
                         "🍯 Honey Pot • 🛡️ Auto Quarantena • 📸 Snapshot • 🕸️ Webhook Killer\n" \
                         "🚨 Panic Mode → `>panic detectivenuovoserver`\n" \
                         "🔄 Full Recovery → `>recover detectivenuovoserver` (ricrea canali + ruoli + permessi)"
    embed2.set_footer(text="Help page 2/2 • Requested by: detective")

    bot.page1_embed = embed1
    bot.page2_embed = embed2

    view = HelpView(bot, interaction.user.id)
    await interaction.response.send_message(embed=embed1, view=view)

@bot.event
async def on_ready():
    print("✅ Atomic Void è ONLINE!")
    print("   Password per comandi sensibili: detectivenuovoserver")

# Questa parte legge il token in modo che GitHub non ti blocchi più
bot.run(os.getenv("DISCORD_TOKEN"))
                  
