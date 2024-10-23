import discord
from discord import Intents
from discord.ext import commands, tasks
import aiosqlite
import asyncio
from datetime import datetime, timedelta
import random

intents = Intents.default()
intents.messages = True  # Enable message intents
intents.reactions = True  # Enable reaction intents
intents.presences = True  # For presence updates
intents.guilds = True  # For guild-related events
intents.members = True  # For member-related events
intents.message_content = True  # Enable message content intents

async def setup_database():
    async with aiosqlite.connect(DATABASE) as db:
        # Create the pets table if it doesn't exist, and ensure all necessary columns are included
        await db.execute('''
            CREATE TABLE IF NOT EXISTS pets (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                hunger INTEGER DEFAULT 100,
                happiness INTEGER DEFAULT 100,
                energy INTEGER DEFAULT 100,
                coins INTEGER DEFAULT 0,
                freeze_end DATETIME,
                owner_id TEXT,
                birth_time DATETIME  -- Make sure this line is included
            )
        ''')
        await db.commit()


# Define weather conditions and their effects
WEATHER_CONDITIONS = {
    'Sunny': {'happiness': 5, 'energy': 10, 'hunger': 0},
    'Rainy': {'happiness': -5, 'energy': -5, 'hunger': 0},
    'Windy': {'happiness': 0, 'energy': 5, 'hunger': -5},
    'Snowy': {'happiness': -10, 'energy': -5, 'hunger': 0},
}

DEGRADATION_RANGE = {
    'hunger': (2, 5),       # Valid range: (min_increase, max_increase)
    'energy': (1, 3),       # Valid range: (min_decrease, max_decrease)
    'happiness': (1, 4)     # Valid range: (min_decrease, max_decrease)
}

# Variable to store current weather
current_weather = None
weather_update_time = None
DAILY_COIN_REWARD = 100
FREEZE_COST = 50  # Cost in coins to freeze stats for a day
FREEZE_DURATION = timedelta(days=1)  # Duration for the freeze

# Define the bot and its command prefix
bot = commands.Bot(command_prefix='~', help_command=None, intents=intents)

# Database setup
DATABASE = 'pets.db'

# Pet class to define pet attributes
class VirtualPet:
    def __init__(self, owner_id, name):
        self.owner_id = owner_id
        self.name = name
        self.hunger = # When updating stats
        self.happiness = 100
        self.energy = 100
        self.coins = 0
        self.birth_time = discord.utils.utcnow()
        self.last_claimed = None

# Function to feed the pet
async def feed_pet(pet_id):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('UPDATE pets SET hunger = hunger + 10, happiness = happiness + 5 WHERE id = ?', (pet_id,))
        await db.commit()

# Function to play with the pet
async def play_with_pet(pet_id):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('UPDATE pets SET happiness = happiness + 10, energy = energy - 5 WHERE id = ?', (pet_id,))
        await db.commit()

# Function to let the pet rest
async def rest_pet(pet_id):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('UPDATE pets SET energy = energy + 10 WHERE id = ?', (pet_id,))
        await db.commit()


# Command to create a pet
@bot.command(name='adopt')
async def adopt(ctx, pet_name: str):
    initial_hunger = 50
    initial_happiness = 50
    initial_energy = 50
    initial_coins = 0
    current_time = datetime.now()  # For birth_time or other time-related fields

    async with aiosqlite.connect(DATABASE) as db:
        # Insert the new pet with initial stats into the database
        await db.execute('''
            INSERT INTO pets (name, hunger, happiness, energy, coins, birth_time, owner_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (pet_name, initial_hunger, initial_happiness, initial_energy, initial_coins, current_time, str(ctx.author.id)))

        await db.commit()

    await ctx.send(f"You have adopted a new pet named {pet_name}!")

# Command to check pet status and react to take care of the pet
@bot.command(name='status')
async def status(ctx):
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute('SELECT id, name, hunger, happiness, energy, coins, freeze_end FROM pets WHERE owner_id = ?', (ctx.author.id,)) as cursor:
            pets = await cursor.fetchall()

    if pets:
        for pet in pets:
            pet_id, name, hunger, happiness, energy, coins, freeze_end = pet
            
            # Create an embed for the pet
            embed = discord.Embed(title=f"Status of {name}", color=discord.Color.blue())
            embed.add_field(name="Hunger", value=f"{hunger}", inline=True)
            embed.add_field(name="Happiness", value=f"{happiness}", inline=True)
            embed.add_field(name="Energy", value=f"{energy}", inline=True)
            embed.add_field(name="Coins", value=f"{coins}", inline=True)
            
            # Check if the pet is frozen
            if freeze_end is not None:
                freeze_end_date = datetime.fromisoformat(freeze_end)
                if freeze_end_date > discord.utils.utcnow():
                    embed.add_field(name="Status", value=f"Frozen until {freeze_end_date.strftime('%Y-%m-%d %H:%M:%S')}", inline=False)
                else:
                    embed.add_field(name="Status", value="Not frozen", inline=False)
            else:
                embed.add_field(name="Status", value="Not frozen", inline=False)

            message = await ctx.send(embed=embed)

            # Add reactions for stat changes
            await message.add_reaction("🍔")  # Feed (increase hunger)
            await message.add_reaction("🎉")  # Play (increase happiness)
            await message.add_reaction("💤")  # Rest (increase energy)

            # Wait for a reaction from the user
            def check(reaction, user):
                return user == ctx.author and reaction.message.id == message.id and str(reaction.emoji) in ["🍔", "🎉", "💤"]

            try:
                reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)

                # Update the pet's stats based on the reaction
                async with aiosqlite.connect(DATABASE) as db:
                    if str(reaction.emoji) == "🍔":
                        # Increase hunger (decrease hunger value)
                        await db.execute('UPDATE pets SET hunger = hunger - 10 WHERE id = ?', (pet_id,))
                        await ctx.send(f'{ctx.author.mention} fed **{name}**!')

                    elif str(reaction.emoji) == "🎉":
                        # Increase happiness
                        await db.execute('UPDATE pets SET happiness = happiness + 10 WHERE id = ?', (pet_id,))
                        await ctx.send(f'{ctx.author.mention} played with **{name}**!')

                    elif str(reaction.emoji) == "💤":
                        # Increase energy
                        await db.execute('UPDATE pets SET energy = energy + 10 WHERE id = ?', (pet_id,))
                        await ctx.send(f'{ctx.author.mention} let **{name}** rest!')

                    await db.commit()

                # Remove the user's reaction after processing
                await message.remove_reaction(reaction, user)

            except asyncio.TimeoutError:
                await ctx.send(f'{ctx.author.mention}, you took too long to respond!')

    else:
        await ctx.send(f'{ctx.author.mention}, you don\'t have any pets! Use `!create_pet <name>` to create one.')


# Command to show the leaderboard of pets by age
@bot.command(name='leaderboard')
async def leaderboard(ctx):
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute('SELECT name, birth_time FROM pets WHERE owner_id = ?', (ctx.author.id,)) as cursor:
            pets = await cursor.fetchall()

    if pets:
        # Calculate age and prepare leaderboard data
        leaderboard_data = []
        for name, birth_time in pets:
            age = (discord.utils.utcnow() - datetime.fromisoformat(birth_time)).total_seconds() // (3600 * 24)  # Age in days
            leaderboard_data.append((name, age))

        # Sort pets by age (older first)
        leaderboard_data.sort(key=lambda x: x[1], reverse=True)

        # Format the leaderboard message
        leaderboard_message = '🐾 **Pet Leaderboard** 🐾\n'
        for idx, (name, age) in enumerate(leaderboard_data, start=1):
            leaderboard_message += f'{idx}. **{name}** - Age: {int(age)} days\n'

        await ctx.send(leaderboard_message)
    else:
        await ctx.send(f'{ctx.author.mention}, you don\'t have any pets! Use `!create_pet <name>` to create one.')
        
# Command to update and show the current weather
@bot.command(name='weather')
async def weather(ctx):
    global current_weather, weather_update_time

    # Check if it's a new day to update the weather
    now = discord.utils.utcnow()
    if weather_update_time is None or now.date() != weather_update_time.date():
        current_weather = random.choice(list(WEATHER_CONDITIONS.keys()))
        weather_update_time = now
        await ctx.send(f'The weather has changed to **{current_weather}**!')

        # Apply weather effects to all pets of the user
        async with aiosqlite.connect(DATABASE) as db:
            async with db.execute('SELECT id FROM pets WHERE owner_id = ?', (ctx.author.id,)) as cursor:
                pets = await cursor.fetchall()

            for pet in pets:
                pet_id = pet[0]
                effects = WEATHER_CONDITIONS[current_weather]

                # Update the pet's stats based on the weather
                await db.execute('UPDATE pets SET happiness = happiness + ?, energy = energy + ?, hunger = hunger + ? WHERE id = ?',
                                 (effects['happiness'], effects['energy'], effects['hunger'], pet_id))
            await db.commit()
    else:
        await ctx.send(f'The current weather is still **{current_weather}**.')

    # Show the current weather and its effects
    effects = WEATHER_CONDITIONS[current_weather]
    await ctx.send(f'**Weather Effects:**\nHappiness: {effects["happiness"]}, Energy: {effects["energy"]}, Hunger: {effects["hunger"]}')

# Command to check weather effects
@bot.command(name='weather_status')
async def weather_status(ctx):
    if current_weather:
        effects = WEATHER_CONDITIONS[current_weather]
        await ctx.send(f'The current weather is **{current_weather}** with the following effects:\n'
                       f'Happiness: {effects["happiness"]}, Energy: {effects["energy"]}, Hunger: {effects["hunger"]}')
    else:
        await ctx.send(f'The weather has not been set yet. Use `!weather` to check the current weather.')
        
@bot.command(name='daily')
async def daily(ctx):
    now = discord.utils.utcnow()

    async with aiosqlite.connect(DATABASE) as db:
        # Check if the user has pets
        async with db.execute('SELECT id, last_claimed FROM pets WHERE owner_id = ?', (ctx.author.id,)) as cursor:
            pets = await cursor.fetchall()

        if pets:
            for pet in pets:
                pet_id, last_claimed = pet
                
                # Check if the user has claimed coins today
                if last_claimed is None or datetime.fromisoformat(last_claimed) < now.replace(hour=0, minute=0, second=0, microsecond=0):
                    # Update the pet's coins and last claimed date
                    await db.execute('UPDATE pets SET coins = coins + ?, last_claimed = ? WHERE id = ?',
                                     (DAILY_COIN_REWARD, now.isoformat(), pet_id))
                    await db.commit()
                    await ctx.send(f'{ctx.author.mention}, you have claimed **{DAILY_COIN_REWARD} coins** for your pet!')
                else:
                    await ctx.send(f'{ctx.author.mention}, you have already claimed your coins today for **{pet[0]}**!')
        else:
            await ctx.send(f'{ctx.author.mention}, you don\'t have any pets! Use `!create_pet <name>` to create one.')
            
@bot.command(name='balance')
async def balance(ctx):
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute('SELECT name, coins FROM pets WHERE owner_id = ?', (ctx.author.id,)) as cursor:
            pets = await cursor.fetchall()

    if pets:
        coins_message = '\n'.join([f'**{row[0]}** - Coins: {row[1]}' for row in pets])
        await ctx.send(f'{ctx.author.mention}, here are your pets\' coins:\n{coins_message}')
    else:
        await ctx.send(f'{ctx.author.mention}, you don\'t have any pets! Use `!create_pet <name>` to create one.')

@bot.command(name='freeze')
async def freeze(ctx):
    async with aiosqlite.connect(DATABASE) as db:
        # Check if the user has any pets
        async with db.execute('SELECT id, coins, freeze_end FROM pets WHERE owner_id = ?', (ctx.author.id,)) as cursor:
            pets = await cursor.fetchall()

        if pets:
            for pet in pets:
                pet_id, coins, freeze_end = pet

                # Check if the freeze is already active
                if freeze_end is not None and datetime.fromisoformat(freeze_end) > discord.utils.utcnow():
                    await ctx.send(f'{ctx.author.mention}, your pet **{pet_id}** is already frozen until {freeze_end}.')
                    continue

                # Check if the user has enough coins to freeze stats
                if coins >= FREEZE_COST:
                    # Deduct the cost and set the freeze end time
                    new_freeze_end = discord.utils.utcnow() + FREEZE_DURATION
                    await db.execute('UPDATE pets SET coins = coins - ?, freeze_end = ? WHERE id = ?',
                                     (FREEZE_COST, new_freeze_end.isoformat(), pet_id))
                    await db.commit()
                    await ctx.send(f'{ctx.author.mention}, you have frozen the stats of **{pet_id}** for 1 day!')
                else:
                    await ctx.send(f'{ctx.author.mention}, you do not have enough coins to freeze the stats of **{pet_id}**!')
        else:
            await ctx.send(f'{ctx.author.mention}, you don\'t have any pets! Use `!create_pet <name>` to create one.')
            
            
@bot.command(name='help')
async def help_command(ctx):
    help_embed = discord.Embed(
        title="Help Menu",
        description="Here are the commands you can use:",
        color=discord.Color.blue()
    )

    # Add commands to the embed
    help_embed.add_field(name="`~adopt <pet_name>`", value="Adopt a new pet with the given name.", inline=False)
    help_embed.add_field(name="`~status`", value="View the status of your pet.", inline=False)
    help_embed.add_field(name="`~leaderboard`", value="View the leaderboard of pets ranked by age.", inline=False)
    help_embed.add_field(name="`~weather`", value="Check the current weather affecting your pet's stats.", inline=False)
    help_embed.add_field(name="`~freeze`", value="Freeze stat degradation for a specified time by spending coins.", inline=False)
    help_embed.add_field(name="`~daily`", value="Claim your daily coins.", inline=False)
    help_embed.add_field(name="`~balance`", value="Check your coin balance.", inline=False)
    
    # Send the help embed
    await ctx.send(embed=help_embed)

  
@tasks.loop(hours=4)
async def degrade_pet_stats():
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute('SELECT id, hunger, energy, happiness FROM pets') as cursor:
            async for row in cursor:
                pet_id, hunger, energy, happiness = row

                # Randomly degrade hunger, energy, and happiness
                hunger_increase = random.randint(*DEGRADATION_RANGE['hunger'])  # Ensure this range is valid
                energy_decrease = random.randint(*DEGRADATION_RANGE['energy'])  # Ensure this range is valid
                happiness_decrease = random.randint(*DEGRADATION_RANGE['happiness'])  # Ensure this range is valid

                # Update hunger, energy, and happiness values
                new_hunger = min(hunger + hunger_increase, 100)  # Cap the max hunger
                new_energy = max(energy - energy_decrease, 0)  # Ensure energy doesn't go below 0
                new_happiness = max(happiness - happiness_decrease, 0)  # Ensure happiness doesn't go below 0

                await db.execute(
                    'UPDATE pets SET hunger = ?, energy = ?, happiness = ? WHERE id = ?',
                    (new_hunger, new_energy, new_happiness, pet_id)
                )
                await db.commit()

@tasks.loop(hours=4)  # Adjust the frequency as needed
async def check_for_dead_pets():
    async with aiosqlite.connect(DATABASE) as db:
        # Fetch all pets from the database
        async with db.execute('SELECT name, hunger, energy, owner_id FROM pets') as cursor:
            async for row in cursor:
                pet_name, hunger, energy, owner_id = row
                
                # Check if the pet is dead
                if hunger <= 0 or energy <= 0:
                    # Delete the pet from the database
                    await db.execute('DELETE FROM pets WHERE name = ? AND owner_id = ?', (pet_name, owner_id))
                    await db.commit()
                    # Optional: Notify the owner about the death
                    user = await bot.fetch_user(owner_id)
                    await user.send(f"Your pet '{pet_name}' has died due to starvation or exhaustion.")
                    

# Run the bot
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await setup_database()  # Call the correctly named function
    degrade_pet_stats.start()  # Start the background task
    check_for_dead_pets.start()  # Start the background task




# Replace 'YOUR_TOKEN_HERE' with your bot's token
bot.run('BOT TOKEN')
