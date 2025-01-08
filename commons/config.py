import os
from distutils.util import strtobool

import discord
import spotipy
from discord.ext import commands
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyClientCredentials

load_dotenv()


class Config(object):
    DEBUG = bool(strtobool(os.environ.get("DEBUG")))
    SPOTIPY_REDIRECT_URI_PROD = "https://5f64-191-91-57-22.ngrok-free.app/callback"  # Va cambiando
    SPOTIPY_REDIRECT_URI_DEV = "http://localhost:8002/callback"
    COMMAND_PREFIX = ">"  # Puedes cambiar el prefijo si lo deseas

    SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
    SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
    TOKEN_DISCORD = os.getenv("TOKEN_DISCORD")

    MONGODB_USER = os.getenv("MONGODB_USER")
    MONGODB_PASS = os.getenv("MONGODB_PASS")
    MONGODB_HOST = os.getenv("MONGODB_HOST")
    MONGODB_PORT = os.getenv("MONGODB_PORT")
    SPOTIPY_REDIRECT_URI = SPOTIPY_REDIRECT_URI_DEV if DEBUG else SPOTIPY_REDIRECT_URI_PROD
    FAST_API_PORT = 8002 if DEBUG else 8001
    ADMIN_ID = int(os.getenv("ADMIN_ID"))


queues = {}
voice_clients = {}
loop_flags = {}
loop_song = {}
user_tokens = {}


# Configuración de intents
intents = discord.Intents.default()
intents.message_content = True
bot_discord = commands.Bot(command_prefix=Config.COMMAND_PREFIX, intents=intents)

# Credenciales de Spotify desde variables de entorno
if not Config.SPOTIPY_CLIENT_ID or not Config.SPOTIPY_CLIENT_SECRET:
    raise ValueError("Las variables de entorno SPOTIPY_CLIENT_ID y SPOTIPY_CLIENT_SECRET deben estar configuradas.")

client_spotipy = spotipy.Spotify(
    auth_manager=SpotifyClientCredentials(
        client_id=Config.SPOTIPY_CLIENT_ID, client_secret=Config.SPOTIPY_CLIENT_SECRET
    )
)

if not Config.TOKEN_DISCORD:
    raise ValueError("La variable de entorno DISCORD_TOKEN debe estar configurada.")
