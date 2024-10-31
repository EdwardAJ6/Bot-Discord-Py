queues = {}
voice_clients = {}
loop_flags = {}
loop_song = {}
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

COMMAND_PREFIX = ">"  # Puedes cambiar el prefijo si lo deseas
load_dotenv()

# Configuración de intents
intents = discord.Intents.default()
intents.message_content = True
bot_discord = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Credenciales de Spotify desde variables de entorno
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
    raise ValueError("Las variables de entorno SPOTIPY_CLIENT_ID y SPOTIPY_CLIENT_SECRET deben estar configuradas.")
client_spotipy = spotipy.Spotify(
    auth_manager=SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
)
