import discord
from discord.ext import commands
from googletrans import Translator, LANGUAGES
import os
import sqlite3
from dotenv import load_dotenv
import requests

load_dotenv()

# Initialize the bot
bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

# Initialize the translator
translator = Translator()

# Connect to SQLite database
conn = sqlite3.connect('languages.db')
cursor = conn.cursor()

# Ensure the table exists
cursor.execute('''CREATE TABLE IF NOT EXISTS language_preferences (
                    server_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    first_language TEXT NOT NULL,
                    second_language TEXT NOT NULL,
                    webhook_url TEXT NOT NULL,
                    PRIMARY KEY (server_id, channel_id)
                )''')
conn.commit()

# Function to detect language
def detect_language(text):
    try:
        detected_lang = translator.detect(text).lang
        return detected_lang
    except Exception as e:
        print(f"Failed to detect language: {str(e)}")
        return None

@bot.event
async def on_ready():
    tree = await bot.tree.sync()
    print(f"Logged in as {bot.user}\nServing {len(bot.guilds)} server(s)\nSynced {len(tree)} slash command(s)")
    activity_name = f"{len(bot.guilds)} Server" if len(bot.guilds) < 2 else f"{len(bot.guilds)} Servers"
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=activity_name))

@bot.tree.command(description="Check the current latency of the bot.")
async def ping(interaction: discord.Interaction):
    embed = discord.Embed(color=discord.Color.light_embed())
    embed.description = f"Pong! {round(bot.latency * 1000, 2)} ms"
    await interaction.response.send_message(embed=embed)

@bot.tree.command(description="Set The Language Preference For A Channel.")
async def set_languages(interaction: discord.Interaction, first_lang: str, second_lang: str):
    embed = discord.Embed(color=discord.Color.light_embed())
    embed.description = "Setting The Language Preferences..."
    await interaction.response.send_message(embed=embed)

    try:
        if not interaction.user.guild_permissions.manage_channels:
            embed.description = "You do not have the permission to use that command."
            await interaction.edit_original_response(embed=embed)
            return
    except:
        embed.description = "You do not have the permission to use that command."
        await interaction.edit_original_response(embed=embed)
        return

    server_id = interaction.guild.id
    channel_id = interaction.channel.id

    first_lang_code = None
    second_lang_code = None
    for code, name in LANGUAGES.items():
        if name.lower() == first_lang.lower():
            first_lang_code = code
        if name.lower() == second_lang.lower():
            second_lang_code = code

    if not first_lang_code or not second_lang_code:
        embed.description = "One or both of the language names provided are invalid."
        await interaction.edit_original_response(embed=embed)
        return

    cursor.execute('SELECT * FROM language_preferences WHERE server_id=? AND channel_id=?', (server_id, channel_id))
    existing_entry = cursor.fetchone()

    if existing_entry:
        webhook_url = existing_entry[4]  # Use the existing webhook URL
        cursor.execute('UPDATE language_preferences SET first_language=?, second_language=? WHERE server_id=? AND channel_id=?',
                       (first_lang_code, second_lang_code, server_id, channel_id))
    else:
        webhook = await interaction.channel.create_webhook(name="Translation Webhook")
        webhook_url = webhook.url
        cursor.execute('INSERT INTO language_preferences VALUES (?, ?, ?, ?, ?)', (server_id, channel_id, first_lang_code, second_lang_code, webhook_url))

    conn.commit()
    
    embed.description = f"Language preferences set for this channel: First Language - ``{LANGUAGES.get(first_lang_code)}``, Second Language - ``{LANGUAGES.get(second_lang_code)}``"
    await interaction.edit_original_response(embed=embed)

@bot.tree.command(description="Remove Language Preferences For A Channel.")
async def remove_languages(interaction: discord.Interaction):
    embed = discord.Embed(color=discord.Color.light_embed())
    embed.description = "Removing Language Preferences..."
    await interaction.response.send_message(embed=embed)

    try:
        if not interaction.user.guild_permissions.manage_channels:
            embed.description = "You do not have the permission to use that command."
            await interaction.edit_original_response(embed=embed)
            return
    except:
        embed.description = "You do not have the permission to use that command."
        await interaction.edit_original_response(embed=embed)
        return

    server_id = interaction.guild.id
    channel_id = interaction.channel.id

    cursor.execute('SELECT * FROM language_preferences WHERE server_id=? AND channel_id=?', (server_id, channel_id))
    existing_entry = cursor.fetchone()

    if existing_entry:
        cursor.execute('DELETE FROM language_preferences WHERE server_id=? AND channel_id=?', (server_id, channel_id))
        conn.commit()
        embed.description = "Language preferences removed for this channel."
    else:
        embed.description = "No language preferences set for this channel."

    await interaction.edit_original_response(embed=embed)

@bot.tree.command(description="Show Current Language Preferences For A Channel.")
async def current_languages(interaction: discord.Interaction):
    embed = discord.Embed(color=discord.Color.light_embed())
    embed.description = "Fetching Current Language Preferences..."
    await interaction.response.send_message(embed=embed)

    server_id = interaction.guild.id
    channel_id = interaction.channel.id

    cursor.execute('SELECT * FROM language_preferences WHERE server_id=? AND channel_id=?', (server_id, channel_id))
    preferences = cursor.fetchone()

    if preferences:
        first_language_code = preferences[2]
        second_language_code = preferences[3]
        first_language_name = LANGUAGES.get(first_language_code)
        second_language_name = LANGUAGES.get(second_language_code)
        embed.description = f"Current language preferences for this channel: First Language - ``{first_language_name}`` Second Language - ``{second_language_name}``"
    else:
        embed.description = "No language preferences set for this channel."

    await interaction.edit_original_response(embed=embed)
    
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.content:
        return

    channel_id = message.channel.id

    cursor.execute('SELECT * FROM language_preferences WHERE server_id=? AND channel_id=?', (message.guild.id, channel_id))
    preferences = cursor.fetchone()

    if not preferences:
        return

    first_language = preferences[2]
    second_language = preferences[3]
    webhook_url = preferences[4]

    detected_lang = detect_language(message.content)

    if not detected_lang:
        print("Failed to detect language, skipping message.")
        return

    if detected_lang == first_language:
        destination_lang = second_language
    elif detected_lang == second_language:
        destination_lang = first_language
    else:
        return

    try:
        # Check if the webhook URL is valid
        response = requests.get(webhook_url)
        
        if response.status_code == 404:  # Webhook is invalid
            print("Webhook is invalid or deleted. Creating a new webhook.")
            # Create a new webhook
            webhook = await message.channel.create_webhook(name="Translation Webhook")
            webhook_url = webhook.url
            
            # Update the database with the new webhook URL
            cursor.execute('UPDATE language_preferences SET webhook_url=? WHERE server_id=? AND channel_id=?', (webhook_url, message.guild.id, channel_id))
            conn.commit()
        elif response.status_code != 200:
            print(f"Failed to validate webhook URL, status code: {response.status_code}")
            return

        # Proceed with translation
        translated = translator.translate(message.content, dest=destination_lang)
        webhook_data = {
            'username': message.author.display_name,
            'avatar_url': str(message.author.avatar.url),
            'content': f"{translated.text} ``({message.content})``"
        }
        
        await message.delete()
        requests.post(webhook_url, json=webhook_data)
    
    except Exception as e:
        print(f"Failed to process message: {str(e)}")

@bot.tree.command(description="The help command which lists out all the basic information and commands for using the bot")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(color=discord.Color.light_embed())
    embed.title = "Help"
    embed.add_field(name="LINKS AND URLS", value="[Youtube Tutorial]()\n[Official Discord Server](https://discord.gg/4uFYtfpnfP)\n[googletrans Library Documentation](https://pypi.org/project/googletrans/)\n[Discord.py Documentation](https://discordpy.readthedocs.io/en/stable/)")
    embed.add_field(name="HELP COMMANDS", value="**/help**\nShows the list of all commands with useful links and urls.\n**/ping**\nShows the current latency of the bot in ms.\n**set_languages**\nSet the languages to translate between in a channel.\n**/remove_languages**\nRemove the languages preferences from a channel, disabling the translating feature.\n**/current_languages**\nShows what the current language preferences are for a channel.", inline=False)
    embed.set_footer(text="Still need help? Join our official Discord server at https://discord.gg/4uFYtfpnfP")
    await interaction.response.send_message(embed=embed)

# Run the bot
try:
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))
except Exception as e:
    print(f"An error occurred while starting the bot: {e}")