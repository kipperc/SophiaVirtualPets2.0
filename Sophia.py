import discord
import time
import json
import os
import asyncio
from discord.ext import commands
from datetime import timedelta
import random
import aiosqlite

async def get_db_connection():
    conn = await aiosqlite.connect('pets.db')
    conn.row_factory = aiosqlite.Row  # Use Row to fetch rows as dictionaries
    return conn

db = None  # Global variable to hold the database connection

class MyBot(commands.Bot):
    async def setup_hook(self):
        # Schedule background tasks during bot setup
        self.loop.create_task(update_pets_status())
        self.loop.create_task(save_pets_periodically()) 
        self.loop.create_task(grant_daily_coins())
        self.loop.create_task(update_weather_periodically())

# Initialize the database
async def initialize_database():
    async with aiosqlite.connect('pets.db') as db:
        # Create the pets table if it doesn't exist
        await db.execute(''' 
            CREATE TABLE IF NOT EXISTS pets (
                name TEXT NOT NULL,
                owner_id INTEGER PRIMARY KEY,
                hunger INTEGER NOT NULL DEFAULT 50,
                happiness INTEGER NOT NULL DEFAULT 50,
                energy INTEGER NOT NULL DEFAULT 50,
                birth_time REAL NOT NULL,
                coins INTEGER NOT NULL DEFAULT 0,
                last_claimed REAL,
                freeze_end REAL
            )
        ''')
        await db.commit()



WEATHER_TYPES = [
    {
        "type": "Sunny ☀️",
        "happiness_change": 5,
        "hunger_change": 0,
        "energy_change": -5,
        "description": "It's a bright sunny day! Pets feel happy but a bit tired."
    },
    {
        "type": "Rainy 🌧️",
        "happiness_change": -5,
        "hunger_change": 0,
        "energy_change": 5,
        "description": "It's raining outside. Pets feel gloomy but well-rested."
    },
    {
        "type": "Snowy ❄️",
        "happiness_change": -5,
        "hunger_change": 5,
        "energy_change": -5,
        "description": "It's snowing! Pets are cold and get hungrier, but it's tough on their energy."
    },
    {
        "type": "Windy 🌬️",
        "happiness_change": 0,
        "hunger_change": -5,
        "energy_change": -5,
        "description": "It's windy today. Pets feel a bit hungry and tired from the strong wind."
    },
]

RANDOM_EVENTS = [
    {
        "description": "Your pet found a hidden treasure!",
        "happiness_change": 5,
        "hunger_change": -10,
        "energy_change": 10
    },
    {
        "description": "Your pet had a bad dream.",
        "happiness_change": -10,
        "hunger_change": -5,
        "energy_change": -10
    },
    {
        "description": "Your pet made a new friend!",
        "happiness_change": 10,
        "hunger_change": -10,
        "energy_change": -5
    },
    {
        "description": "Your pet is feeling lazy today.",
        "happiness_change": -10,
        "hunger_change": -5,
        "energy_change": -10
    },
]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="~", intents=intents, help_command=None)

# Cooldown settings
REACTION_COOLDOWN = 10  # Cooldown time in seconds
cooldowns = {}

class VirtualPet:
    def __init__(self, name, owner_id, hunger=50, happiness=50, energy=50, birth_time=None, coins=0, last_claimed=None, freeze_end=None):
        self.name = name
        self.owner_id = owner_id
        self.hunger = hunger
        self.happiness = happiness
        self.energy = energy
        self.birth_time = birth_time or time.time()
        self.coins = coins
        self.last_claimed = last_claimed
        self.freeze_end = freeze_end

    @classmethod
    def from_db_row(cls, row):
        if len(row) != 9:  # Ensure the row has the expected number of columns
            raise ValueError(f"Row does not have the expected number of columns: {len(row)}")
    
        return cls(
            owner_id=int(row[1]),  # Correctly access owner_id at index 1
            name=row[0],            # Name is at index 0
            hunger=row[2],          # Hunger is at index 2
            happiness=row[3],       # Happiness is at index 3
            energy=row[4],          # Energy is at index 4
            birth_time=row[5],      # Birth time is at index 5
            coins=row[6],           # Coins are at index 6
            last_claimed=row[7],    # Last claimed is at index 7
            freeze_end=row[8]       # Freeze end is at index 8
        )
    
    def status(self):
        return f"Hunger: {self.hunger}/100, Happiness: {self.happiness}/100, Energy: {self.energy}/100"
    
    def is_alive(self):
        if self.hunger >= 100:
            return False, f"Oh no! {self.name} has starved... 💀"
        if self.happiness <= 0:
            return False, f"{self.name} is too sad and has run away... 😢"
        return True, None
    def feed(self, amount):
        self.hunger = max(0, self.hunger - amount)
    
    def play(self, amount):
        self.energy = max(0, self.energy - amount)
        self.happiness = min(100, self.happiness + 10)  # Example increase

    def sleep(self, amount):
        self.energy = min(100, self.energy + amount)

    def update_hunger(self):
        # Example: Increase hunger over time
        self.hunger = min(100, self.hunger + 5)  # Increment hunger

    def update_energy(self):
        # Example: Decrease energy over time
        self.energy = max(0, self.energy - 5)  # Decrement energy
        
    def get_mood(self):
        if self.happiness > 80 and self.energy > 60:
            return "Happy 😊"
        elif self.hunger > 80:
            return "Hungry 🍗"
        elif self.energy < 20:
            return "Tired 😴"
        elif self.happiness < 30:
            return "Sad 😢"
        else:
            return "Neutral 😐"
        
    def get_age(self):
        return time.time() - self.birth_time  # Returns age in seconds
    
    def feed(self):
        if self.freeze_end and time.time() < self.freeze_end:
            return f"{self.name}'s stats are frozen!"
        
        self.hunger = max(0, self.hunger - 20)
        self.happiness = min(100, self.happiness + 5)
        return f"{self.name} is happily munching on food! 🍗 Hunger: {self.hunger}, Happiness: {self.happiness}"
    
    def play(self):
        if self.freeze_end and time.time() < self.freeze_end:
            return f"{self.name}'s stats are frozen!"
            
        self.happiness = min(100, self.happiness + 20)
        self.energy = max(0, self.energy - 10)
        self.hunger = min(100, self.hunger + 10)
        return f"{self.name} is having fun playing! 🎾 Happiness: {self.happiness}, Energy: {self.energy}, Hunger: {self.hunger}"
    
    def sleep(self):
        if self.freeze_end and time.time() < self.freeze_end:
            return f"{self.name}'s stats are frozen!"
            
        self.energy = min(100, self.energy + 30)
        self.hunger = min(100, self.hunger + 20)
        return f"{self.name} is peacefully sleeping! 💤 Energy: {self.energy}, Hunger: {self.hunger}"
    

    def update_status(self):
        if self.freeze_end and time.time() < self.freeze_end:
            return
    
        # Regular updates to hunger, happiness, and energy
        self.hunger = min(100, self.hunger + random.randint(1, 3))
        self.happiness = max(0, self.happiness - random.randint(1, 3))
        self.energy = max(0, self.energy - random.randint(1, 3))
    
        # Trigger a random event with a 20% chance
        if random.random() < 0.2:  
            event = random.choice(RANDOM_EVENTS)
            self.happiness = max(0, min(100, self.happiness + event["happiness_change"]))
            self.hunger = max(0, min(100, self.hunger + event["hunger_change"]))
            self.energy = max(0, min(100, self.energy + event["energy_change"]))
    


    def generate_embed(self):
        embed = discord.Embed(title=self.name, color=0x00ff00)
        embed.add_field(name="Hunger", value=f"{self.hunger}/100", inline=True)
        embed.add_field(name="Happiness", value=f"{self.happiness}/100", inline=True)
        embed.add_field(name="Energy", value=f"{self.energy}/100", inline=True)
        embed.add_field(name="Coins", value=self.coins, inline=True)
        embed.add_field(name="Mood", value=self.get_mood(), inline=True)
        age_days = int(self.get_age() // (24 * 3600))
        embed.add_field(name="Age", value=f"{age_days} days", inline=True)
        return embed
    
    async def save(self):
        async with aiosqlite.connect("pets.db") as db:
            await db.execute('''
                INSERT OR REPLACE INTO pets 
                (owner_id, name, hunger, happiness, energy, birth_time, coins, last_claimed, freeze_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (self.owner_id, self.name, self.hunger, self.happiness, self.energy, 
                  self.birth_time, self.coins, self.last_claimed, self.freeze_end))
            await db.commit()

    
    @staticmethod
    async def load(owner_id):
        async with aiosqlite.connect("pets.db") as db:
            async with db.execute('SELECT * FROM pets WHERE owner_id = ?', (owner_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return VirtualPet.from_db_row(row)
                return None
    
    @staticmethod
    async def load_all():
        pets = []
        async with aiosqlite.connect("pets.db") as db:
            async with db.execute('SELECT * FROM pets') as cursor:
                async for row in cursor:
                    pets.append(VirtualPet.from_db_row(row))
        return pets
    
    @staticmethod
    async def delete(owner_id):
        async with aiosqlite.connect("pets.db") as db:
            await db.execute('DELETE FROM pets WHERE owner_id = ?', (owner_id,))
            await db.commit()
            


async def get_pet_data_from_database(owner_id):
    async with aiosqlite.connect('pets.db') as db:
        async with db.execute(""" 
            SELECT name, owner_id, hunger, happiness, energy, birth_time, coins, last_claimed, freeze_end 
            FROM pets 
            WHERE owner_id = ? 
        """, (owner_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'name': row[0],                             # Name as TEXT
                    'owner_id': int(row[1]),                   # Ensure owner_id is an integer
                    'hunger': int(row[2]),                     # Ensure hunger is an integer
                    'happiness': int(row[3]),                  # Ensure happiness is an integer
                    'energy': int(row[4]),                     # Ensure energy is an integer
                    'birth_time': float(row[5]),               # Ensure birth_time is a float (if using timestamps)
                    'coins': int(row[6]),                      # Ensure coins is an integer
                    'last_claimed': float(row[7]) if row[7] is not None else None,  # Cast to float, or None
                    'freeze_end': float(row[8]) if row[8] is not None else None   # Cast to float, or None
                }
            return None

# Enabling row_factory to return dictionary-like objects
async def fetch_pet_data(user_id):
    async with aiosqlite.connect('pets.db') as db:
        db.row_factory = aiosqlite.Row  # This makes rows accessible by column name
        async with db.execute("SELECT * FROM pets WHERE owner_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
    return row
            
async def fetch_pet_from_db(owner_id):
    async with aiosqlite.connect('pets.db') as db:
        async with db.execute("SELECT * FROM pets WHERE owner_id = ?", (owner_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return VirtualPet.from_db_row(row)  # Ensure this matches the new row structure
            return None


def format_time(seconds):
    return str(timedelta(seconds=seconds)).split('.')[0]


async def update_pets_status():
    while True:
        await asyncio.sleep(3600)  # Update every hour
        pets = await VirtualPet.load_all()
        for pet in pets:
            pet.update_status()
            alive = pet.is_alive()
            if not alive:
                await VirtualPet.delete(pet.owner_id)
                continue
            await pet.save()

async def save_pets_periodically():
    while True:
        await asyncio.sleep(86400)  # Save every 24 hours
        pets = await VirtualPet.load_all()
        for pet in pets:
            await pet.save()
    
async def grant_daily_coins():
    while True:
        await asyncio.sleep(86400)  # Wait for 24 hours
        pets = await VirtualPet.load_all()
        for pet in pets:
            pet.coins += 10
            await pet.save()
    
current_weather = None
last_weather_change_time = time.time()

def change_weather():
    global current_weather
    current_weather = random.choice(WEATHER_TYPES)
    return current_weather
    
def apply_weather_effects(pet):
    if not current_weather:
        return "The weather is stable today."
        
    if pet.freeze_end and time.time() < pet.freeze_end:
        return f"{pet.name}'s stats are frozen. Weather has no effect."
        
    pet.happiness = max(0, min(100, pet.happiness + current_weather["happiness_change"]))
    pet.hunger = max(0, min(100, pet.hunger + current_weather["hunger_change"]))
    pet.energy = max(0, min(100, pet.energy + current_weather["energy_change"]))
    return current_weather["description"]

async def update_weather_periodically():
    while True:
        await asyncio.sleep(86400)  # Change weather every 24 hours
        change_weather()
        
async def delete_message_after_delay(message, delay=10):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except discord.errors.NotFound:
        pass

async def save_pet_to_db(pet):
    async with aiosqlite.connect('pets.db') as db:
        await db.execute('''
            INSERT OR REPLACE INTO pets 
            (owner_id, name, hunger, happiness, energy, birth_time, coins, last_claimed, freeze_end)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            pet.owner_id,
            pet.name,
            pet.hunger,
            pet.happiness,
            pet.energy,
            pet.birth_time,
            pet.coins,
            pet.last_claimed,
            pet.freeze_end
        ))
        await db.commit()
        
async def delete_pet_from_db(owner_id):
    # Connect to the SQLite database asynchronously
    async with aiosqlite.connect('pets.db') as db:
        # SQL query to delete the pet record for the given owner_id
        query = "DELETE FROM pets WHERE owner_id = ?"
        
        # Execute the deletion query with the provided owner_id
        await db.execute(query, (owner_id,))
        
        # Commit the changes to the database
        await db.commit()
    
async def update_pet_in_db(pet):
    async with aiosqlite.connect('pets.db') as db:
        await db.execute("""
            UPDATE pets
            SET name = ?, hunger = ?, happiness = ?, energy = ?, birth_time = ?, coins = ?, last_claimed = ?, freeze_end = ?
            WHERE owner_id = ?
        """, (
            pet.name,                           # Access pet's name attribute
            int(pet.hunger),                   # Ensure hunger is an integer
            int(pet.happiness),                # Ensure happiness is an integer
            int(pet.energy),                   # Ensure energy is an integer
            float(pet.birth_time),             # Ensure birth_time is a float
            int(pet.coins),                    # Ensure coins is an integer
            float(pet.last_claimed) if pet.last_claimed is not None else None,  # Ensure last_claimed is a float or None
            float(pet.freeze_end) if pet.freeze_end is not None else None,      # Ensure freeze_end is a float or None
            int(pet.owner_id)                  # Ensure owner_id is an integer
        ))
        await db.commit()
    
async def fetch_all_pets_from_db():
    # Connect to the SQLite database asynchronously
    async with aiosqlite.connect('pets.db') as db:
        # SQL query to fetch all pets from the database
        query = "SELECT owner_id, name, hunger, happiness, energy, birth_time, coins, last_claimed, freeze_end FROM pets"
        
        # Execute the query and fetch all records
        async with db.execute(query) as cursor:
            rows = await cursor.fetchall()  # Fetch all rows asynchronously
            
            # Convert rows into a list of pet dictionaries or objects
            pets = []
            for row in rows:
                pet_data = {
                    'owner_id': row[0],
                    'name': row[1],
                    'hunger': row[2],
                    'happiness': row[3],
                    'energy': row[4],
                    'birth_time': row[5],
                    'coins': row[6],
                    'last_claimed': row[7],
                    'freeze_end': row[8]
                }
                pets.append(pet_data)
            
            return pets
    
async def update_freeze_timer_in_db(owner_id, freeze_end):
    async with aiosqlite.connect('pets.db') as db:
        await db.execute("UPDATE pets SET freeze_end = ? WHERE owner_id = ?", (freeze_end, owner_id))
        await db.commit()
    
async def is_admin(ctx):
    return ctx.author.guild_permissions.administrator


def generate_embed(pet):
    embed = discord.Embed(title=f"{pet.name}'s Status", color=discord.Color.blue())
    
    # Adding pet's attributes to the embed
    embed.add_field(name="Hunger", value=f"{pet.hunger}/100", inline=True)
    embed.add_field(name="Happiness", value=f"{pet.happiness}/100", inline=True)
    embed.add_field(name="Energy", value=f"{pet.energy}/100", inline=True)
    embed.add_field(name="Coins", value=pet.coins, inline=True)

    # Convert the pet's birth time from epoch to a human-readable format
    birth_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(pet.birth_time))
    embed.add_field(name="Born on", value=birth_date, inline=True)

    return embed

@bot.event
async def on_ready():
    # Initialize the database when the bot starts
    await initialize_database()
    print(f'Bot is ready! Logged in as {bot.user.name}')
    # Start background tasks
    bot.loop.create_task(update_pets_status())
    bot.loop.create_task(save_pets_periodically())
    bot.loop.create_task(grant_daily_coins())
    bot.loop.create_task(update_weather_periodically())
@bot.event
async def on_disconnect():
    await db.close()  # Close the connection when the bot disconnects
    
@bot.command()
async def adopt(ctx, *, name: str = None):
    if name is None:
        await ctx.send("Please provide a name for your pet! Usage: `~adopt [pet_name]`.")
        return
    # Check if the user already has a pet
    pet = await fetch_pet_from_db(ctx.author.id)
    
    if pet:
        await ctx.send(f"You already have a pet named {pet.name}!")
    else:
        # Create a new pet and save it to the database
        new_pet = VirtualPet(name, ctx.author.id)
        await save_pet_to_db(new_pet)
        await ctx.send(f"{name} has been adopted! Take good care of it.")
        # Send an embed with the pet's status
        embed = new_pet.generate_embed()
        message = await ctx.send(embed=embed)
        # Add reactions for interaction
        await message.add_reaction("🍗")  # Feed
        await message.add_reaction("🎾")  # Play
        await message.add_reaction("💤")  # Sleep
    
@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    # Check if the user is within the cooldown period
    current_time = time.time()
    user_cooldown = cooldowns.get(user.id, 0)
    if current_time - user_cooldown < REACTION_COOLDOWN:
        # Remove the user's reaction even if they're on cooldown
        await reaction.remove(user)
        return
    # Update the cooldown time for the user
    cooldowns[user.id] = current_time
    # Load the user's pet from the database
    pet = await fetch_pet_from_db(user.id)
    if not pet:
        await reaction.message.channel.send(f"{user.mention}, you don't have a pet yet! Use `~adopt [pet_name]` to adopt one.")
        return
    # Check if the pet is alive
    old_mood = pet.get_mood()  # Get the old mood before the action
    alive, message = pet.is_alive()
    if not alive:
        await reaction.message.channel.send(message)
        # Delete the pet from the database since it's dead
        await delete_pet_from_db(user.id)
        return
    # Handle the reaction-based interaction
    if reaction.emoji == "🍗":  # Feed
        result = pet.feed()
    elif reaction.emoji == "🎾":  # Play
        result = pet.play()
    elif reaction.emoji == "💤":  # Sleep
        result = pet.sleep()
    else:
        return  # If the reaction is not valid, do nothing
    # If the mood has changed, notify the user
    new_mood = pet.get_mood()
    if new_mood != old_mood:
        await reaction.message.channel.send(f"{user.mention}, your pet's mood changed to {new_mood}!")
    # Send the result message (e.g., "Your pet is full now!")
    response_message = await reaction.message.channel.send(result)
    # Update the pet's status in the database
    await update_pet_in_db(pet)
    # Update the embed with the new status
    embed = pet.generate_embed()
    await reaction.message.edit(embed=embed)
    # Remove the user's reaction to prevent duplicate actions
    await reaction.remove(user)
    # Clean up the response message after a delay (optional)
    await delete_message_after_delay(response_message)

@bot.command()
async def status(ctx):
    user_id = ctx.author.id

    # Fetch the pet from the database based on the user ID
    async with aiosqlite.connect('pets.db') as db:
        async with db.execute("SELECT name, owner_id, hunger, happiness, energy, birth_time, coins, last_claimed, freeze_end FROM pets WHERE owner_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

            if row is None:
                await ctx.send("You don't have a pet yet! Use `~adopt [pet_name]` to adopt one.")
                return

            # Create a VirtualPet object from the database row using indices
            try:
                pet = VirtualPet.from_db_row(row)
            except IndexError as e:
                print(f"Error creating pet from row: {e}")  # Log error if it occurs
                await ctx.send("There was an error processing your pet data.")
                return

    # Check if the pet is alive
    alive, message = pet.is_alive()

    if not alive:
        await ctx.send(message)

        # Optionally delete the pet from the database if it's no longer alive
        async with aiosqlite.connect('pets.db') as db:
            await db.execute("DELETE FROM pets WHERE owner_id = ?", (user_id,))
            await db.commit()

        return

    # Generate the embed for the pet's status
    embed = generate_embed(pet)
    message = await ctx.send(embed=embed)

    # Add reactions for interaction
    await message.add_reaction("🍗")  # Feed
    await message.add_reaction("🎾")  # Play
    await message.add_reaction("💤")  # Sleep

@bot.command()
async def help(ctx):
    help_message = (
        "Here are the available commands:\n"
        "`~adopt [pet_name]` - Adopt a new pet with the given name.\n"
        "`~status` - Check your pet's status (hunger, happiness, energy).\n"
        "`~leaderboard` - View the leaderboard of pets sorted by age.\n"
        "`~freeze [coin_amount]` - Spend coins to freeze pet stats for vacations.\n"
        "`~rename [new_name]` - Rename pet.\n"
        "`~gift @user [coin_amount]` - Gift coins to another player.\n"
        "`~weather` - Get a weather update.\n"
        "`~adventure` - Take your pet out on an adventure.\n"
        "`~babysit [user]` - Babysit your friend's pet.\n"
        "`~feedfriend [user]` - Feed your friend's pet.\n"
        "`~steal [user]` - Attempt to steal coins from another player.\n"
        "Hidden commands! Find these to unlock hidden commands.\n"
        "Reactions: You can interact with your pet by reacting to the status message with:\n"
        "🍗 - Feed your pet\n"
        "🎾 - Play with your pet\n"
        "💤 - Let your pet sleep\n"
    )
    await ctx.send(help_message)

@bot.command()
async def leaderboard(ctx):
    """Display the leaderboard of the longest-lived pets."""
    leaderboard_data = []

    try:
        async with aiosqlite.connect('pets.db') as db:
            async with db.execute("SELECT name, owner_id, birth_time FROM pets") as cursor:
                rows = await cursor.fetchall()  # Fetch all rows

                for row in rows:
                    pet_name = row[0]
                    owner_id = row[1]
                    age_in_seconds = time.time() - row[2]  # Assuming birth_time is in seconds
                    age_in_days = age_in_seconds // (24 * 3600)  # Convert seconds to days
                    leaderboard_data.append((pet_name, owner_id, age_in_days))

                # Sort the leaderboard by age in descending order
                leaderboard_data.sort(key=lambda x: x[2], reverse=True)  # Sort by age_in_days

                # Create an embed for the leaderboard
                embed = discord.Embed(title="Pet Leaderboard", color=discord.Color.gold())

                # Add each pet to the embed
                for name, owner, age in leaderboard_data:
                    owner_user = await bot.fetch_user(owner)  # Fetch user from ID
                    embed.add_field(name=name, value=f"{owner_user.name}: {age} days", inline=False)

                await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"An error occurred while fetching the leaderboard: {e}")

@bot.command()
async def rename(ctx, *, new_name: str):
    owner_id = ctx.author.id
    # Fetch the user's pet from the database
    pet = await fetch_pet_from_db(owner_id)
    if not pet:
        await ctx.send("You don't have a pet yet! Use `~adopt [pet_name]` to adopt one.")
        return
    old_name = pet.name
    pet.name = new_name
    await update_pet_in_db(pet)  # Save the updated pet to the database
    await ctx.send(f"Your pet's name has been changed from {old_name} to {new_name}.")

@bot.command()
async def weather(ctx):
    if current_weather:
        await ctx.send(f"The current weather is {current_weather['type']}: {current_weather['description']}")
    else:
        await ctx.send("The weather is calm today.")

@bot.command()
async def gift(ctx, member: discord.Member, amount: int):
    owner_id = ctx.author.id
    recipient_id = member.id
    # Fetch both pets from the database
    pet = await fetch_pet_from_db(owner_id)
    recipient_pet = await fetch_pet_from_db(recipient_id)
    if not pet:
        await ctx.send("You don't have a pet yet! Use `~adopt [pet_name]` to adopt one.")
        return
    if not recipient_pet:
        await ctx.send(f"{member.name} doesn't have a pet yet!")
        return
    if amount <= 0 or pet.coins < amount:
        await ctx.send(f"You don't have enough coins to gift {amount}.")
        return
    # Perform the transaction
    pet.coins -= amount
    recipient_pet.coins += amount
    # Update both pets in the database
    await update_pet_in_db(pet)
    await update_pet_in_db(recipient_pet)
    await ctx.send(f"You have gifted {amount} coins to {member.name}.")

@bot.command()
@commands.has_permissions(administrator=True)
async def force_save(ctx):
    # Fetch all pets from the database
    all_pets = await fetch_all_pets_from_db()
    # Save each pet back to the database
    for pet in all_pets:
        await update_pet_in_db(pet)
    await ctx.send("Pets have been saved successfully!")
    
@force_save.error
async def force_save_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("Sorry, I don't recognize that command. Use `~help` to see all available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Please provide all required arguments for this command.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("One of the arguments you provided is invalid. Please check and try again.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"This command is on cooldown. Please wait {error.retry_after:.2f} seconds.")
    else:
        await ctx.send("An unexpected error occurred. Please try again later.")
        print(f"Unhandled error: {error}")  # Log the error for debugging
        
@bot.command()
async def freeze(ctx, days: int):
    owner_id = ctx.author.id
    # Fetch the pet from the database
    pet = await fetch_pet_from_db(owner_id)
    if not pet:
        await ctx.send(f"{ctx.author.mention}, you don't have a pet yet! Use `~adopt [pet_name]` to adopt one.")
        return
    # Check if the user has enough coins
    if pet.coins < days:
        await ctx.send(f"{ctx.author.mention}, you don't have enough coins! You need {days} coins, but you only have {pet.coins}.")
        return
    # Deduct the coins
    pet.coins -= days
    await update_pet_in_db(pet)
    # Set the freeze duration (in seconds) and store it in the database
    freeze_end_time = time.time() + (days * 86400)  # Convert days to seconds
    await update_freeze_timer_in_db(owner_id, freeze_end_time)
    await ctx.send(f"{ctx.author.mention}, your pet's stats are frozen for {days} day(s).")
            
@bot.command()
@commands.has_permissions(administrator=True)
async def delete_all_pets(ctx):
    """Force delete all pets from the database."""
    async with aiosqlite.connect('pets.db') as db:
        await db.execute("DELETE FROM pets")
        await db.commit()
    await ctx.send("All pets have been deleted from the database!")
    
@delete_all_pets.error
async def delete_all_pets_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.")
        
ADVENTURE_RESULTS = [
    "Your pet explored a mystical forest and found a shiny rock! 🌲",
    "Your pet swam across a river and chased a butterfly! 🦋",
    "Your pet got lost in a cave but found its way back. 🐾",
    "Your pet took a nap by the lake and felt refreshed! 😴"
]

@bot.command()
async def adventure(ctx):
    owner_id = ctx.author.id
    pet = await fetch_pet_from_db(owner_id)
    if not pet:
        await ctx.send("You don't have a pet yet! Use `~adopt [pet_name]` to adopt one.")
        return

    if pet.energy < 20:
        await ctx.send(f"{pet.name} is too tired to go on an adventure. 😴 Energy: {pet.energy}/100.")
        return

    result = random.choice(ADVENTURE_RESULTS)
    pet.energy -= 10  # Deduct energy for the adventure
    await update_pet_in_db(pet)
    
    await ctx.send(f"{pet.name} went on an adventure! {result} 🌟 Energy is now {pet.energy}/100.")

@bot.command()
async def feedfriend(ctx, friend: discord.Member):
    owner_id = friend.id
    pet = await fetch_pet_from_db(owner_id)

    if not pet:
        await ctx.send(f"{friend.display_name} doesn't have a pet yet!")
        return

    if pet.hunger < 20:
        await ctx.send(f"{pet.name} isn't hungry right now!")
        return

    pet.hunger = max(0, pet.hunger - 20)  # Reduce hunger, but not below 0
    await update_pet_in_db(pet)
    
    await ctx.send(f"{ctx.author.mention} fed {friend.display_name}'s pet! Hunger is now {pet.hunger}/100.")

@bot.command()
async def steal(ctx, target: discord.Member):
    owner_id = ctx.author.id
    pet = await fetch_pet_from_db(owner_id)
    target_pet = await fetch_pet_from_db(target.id)

    if not pet or not target_pet:
        await ctx.send("Both pets need to exist for the heist to happen!")
        return

    success = random.choice([True, False])
    if success:
        stolen_amount = random.randint(1, 5)
        if target_pet.coins >= stolen_amount:
            pet.coins += stolen_amount
            target_pet.coins -= stolen_amount
            await update_pet_in_db(pet)
            await update_pet_in_db(target_pet)
            await ctx.send(f"{pet.name} successfully stole {stolen_amount} coins from {target_pet.name}! 💰")
        else:
            await ctx.send(f"{target_pet.name} doesn't have enough coins to steal!")
    else:
        await ctx.send(f"{pet.name}'s attempt to steal coins from {target_pet.name} failed! 😢")
        
@bot.command()
async def babysit(ctx, friend: discord.Member):
    owner_id = friend.id
    pet = await fetch_pet_from_db(owner_id)

    if not pet:
        await ctx.send(f"{friend.display_name} doesn't have a pet yet!")
        return

    friend_message = (
        f"{friend.display_name}'s pet {pet.name} stats:\n"
        f"🌭 Hunger: {pet.hunger}/100\n"
        f"😊 Happiness: {pet.happiness}/100\n"
        f"⚡ Energy: {pet.energy}/100\n"
        f"💰 Coins: {pet.coins}"
    )
    await ctx.send(friend_message)

@bot.command()
@commands.check(is_admin)
async def give_coins(ctx, user: discord.User, amount: int):
    if amount <= 0:
        await ctx.send("Amount must be greater than zero.")
        return

    # Fetch the pet for the user (by their ID)
    pet = await fetch_pet_from_db(user.id)
    
    if not pet:
        await ctx.send(f"{user.name} does not have a pet!")
        return

    # Add the coins to the user's pet
    pet.coins += amount
    await pet.save()  # Save the updated pet back to the database

    await ctx.send(f"Gave {amount} coins to {user.name}'s pet! They now have {pet.coins} coins.")

# Handle the error if the command is used by a non-admin
@give_coins.error
async def give_coins_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("You do not have permission to use this command.")
        
# Define a shop with items that set stats to maximum or minimum values
SHOP_ITEMS = {
    "food": {"cost": 100, "effect": "max_hunger", "description": "Feed your pet to reduce hunger to 0."},
    "toy": {"cost": 100, "effect": "max_happiness", "description": "Increase your pet's happiness to 100."},
    "nap": {"cost": 100, "effect": "max_energy", "description": "Restore your pet's energy to 100."}
}

@bot.command()
async def shop(ctx):
    # Display available shop items and their costs
    shop_list = "\n".join([f"{item}: {details['cost']} coins - {details['description']}"
                           for item, details in SHOP_ITEMS.items()])
    await ctx.send(f"Welcome to the shop! Here are the available items:\n\n{shop_list}")

@bot.command()
async def buy(ctx, item_name: str):
    owner_id = ctx.author.id
    pet = await fetch_pet_from_db(owner_id)
    
    if not pet:
        await ctx.send("You don't have a pet yet! Use `~adopt [pet_name]` to adopt one.")
        return

    item = SHOP_ITEMS.get(item_name.lower())

    if not item:
        await ctx.send(f"Item `{item_name}` is not available in the shop. Use `~shop` to see available items.")
        return

    if pet.coins < item["cost"]:
        await ctx.send(f"You don't have enough coins to buy `{item_name}`. You need {item['cost']} coins.")
        return

    # Deduct the cost of the item
    pet.coins -= item["cost"]

    # Apply the item's effect (setting stats to 0 for hunger, 100 for happiness and energy)
    if item["effect"] == "max_hunger":
        pet.hunger = 0  # Set hunger to its minimum value
    elif item["effect"] == "max_happiness":
        pet.happiness = 100  # Set happiness to its maximum value
    elif item["effect"] == "max_energy":
        pet.energy = 100  # Set energy to its maximum value

    await pet.save()  # Save the pet's updated stats to the database

    await ctx.send(f"You bought `{item_name}` for {item['cost']} coins! Your pet's stats have been updated.")

import random

@bot.command()
async def gamble(ctx, amount: int):
    owner_id = ctx.author.id
    pet = await fetch_pet_from_db(owner_id)
    
    if not pet:
        await ctx.send("You don't have a pet yet! Use `~adopt [pet_name]` to adopt one.")
        return

    # Check if the amount is valid
    if amount <= 0:
        await ctx.send("Please enter a valid amount to gamble.")
        return

    # Check if the user has enough coins
    if pet.coins < amount:
        await ctx.send(f"You don't have enough coins to gamble {amount}. You only have {pet.coins} coins.")
        return

    # 50% chance of winning or losing
    if random.choice([True, False]):  # 50% win, 50% lose
        pet.coins += amount  # Double the user's bet
        await ctx.send(f"Congratulations! You won {amount} coins! You now have {pet.coins} coins.")
    else:
        pet.coins -= amount  # User loses their bet
        await ctx.send(f"Oops! You lost {amount} coins. You now have {pet.coins} coins.")

    # Save the pet's updated coins
    await pet.save()

@bot.command()
async def mostcoins(ctx):
    async with aiosqlite.connect('pets.db') as db:
        async with db.execute("SELECT owner_id, name, coins FROM pets ORDER BY coins DESC") as cursor:
            rows = await cursor.fetchall()

            if not rows:
                await ctx.send("No pets found in the database.")
                return
            
            leaderboard_text = "🏆 **Coins Leaderboard** 🏆\n\n"
            for idx, (owner_id, name, coins) in enumerate(rows[:10]):  # Limit to top 10
                leaderboard_text += f"{idx + 1}. {name} (ID: {owner_id}) - {coins} coins\n"

            await ctx.send(leaderboard_text)


@bot.command()
async def balance(ctx):
    user_id = ctx.author.id

    # Fetch the pet from the database based on the user ID
    async with aiosqlite.connect('pets.db') as db:
        async with db.execute("SELECT name, coins FROM pets WHERE owner_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

            if row is None:
                await ctx.send("You don't have a pet yet! Use `~adopt [pet_name]` to adopt one.")
                return
            
            name, coins = row
            await ctx.send(f"{name} has {coins} coins.")
            
@bot.command()
async def surprise(ctx, target: discord.User):
    owner_id = target.id
    pet = await fetch_pet_from_db(owner_id)

    if not pet:
        await ctx.send(f"{target.display_name} doesn't have a pet yet!")
        return

    event = random.choice(RANDOM_EVENTS)
    pet.happiness = max(0, min(100, pet.happiness + event["happiness_change"]))
    pet.hunger = max(0, min(100, pet.hunger + event["hunger_change"]))
    pet.energy = max(0, min(100, pet.energy + event["energy_change"]))
    await pet.save()

    await ctx.send(f"Surprise for {target.display_name}'s pet: {event['description']}")


bot.run('TOKEN')
