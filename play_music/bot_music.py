import asyncio
import logging
import re
import urllib.parse
import urllib.request

import aiohttp
import discord
import yt_dlp
from discord.ext import commands

from commons.config import (
    bot_discord,
    client_spotipy,
    loop_flags,
    loop_song,
    queues,
    voice_clients,
)

# Configuración de logging
logging.basicConfig(level=logging.DEBUG)


# Configuración de yt_dlp y ffmpeg
yt_dl_options = {"format": "bestaudio/best","noplaylist": True,}
ytdl = yt_dlp.YoutubeDL(yt_dl_options)
ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": '-vn -filter:a "volume=0.25"',
}


async def ensure_voice(ctx):
    try:
        channel = ctx.author.voice.channel
        perms = channel.permissions_for(ctx.guild.me)
        if not perms.connect or not perms.speak:
            await ctx.send("No tengo permisos para unirme o hablar en tu canal de voz.")
            return

        if ctx.voice_client and not ctx.voice_client.is_connected():
            await ctx.voice_client.disconnect(force=True)

        try:
            voice_client = await channel.connect()
            return voice_client
        except asyncio.TimeoutError as e:
            await ctx.send("❌ No se pudo conectar al canal de voz: tiempo de espera agotado.")
            raise e  

    except AttributeError:
        await ctx.send("¡Debes estar en un canal de voz para usar este comando!")
    except Exception as e:
        logging.exception("Error inesperado al conectar al canal de voz")
        await ctx.send(f"Error al conectar: {e}")

# Función para manejar playlists de Spotify
async def handle_spotify_playlist(ctx, playlist_url, voice_client, is_loop):
    guild_id = ctx.guild.id
    try:
        tracks_info = get_spotify_playlist_tracks(playlist_url)
        if not tracks_info:
            await ctx.send("No se pudieron obtener las canciones de la playlist.")
            return

        tracks = tracks_info["tracks"]
        if guild_id not in queues:
            queues[guild_id] = []

        for track_info in tracks:
            query_string = (
                f"{track_info['artist']} - {track_info['title']} audio oficial"
            )
            youtube_link = await search_youtube(query_string)
            if youtube_link:
                data = await ytdl_extract_info(youtube_link)
                song_info = {
                    "title": data["title"],
                    "duration": data["duration"],
                    "thumbnail": data["thumbnail"],
                    "song_url": data["url"],
                    "youtube_url": data["original_url"],
                }
                queues[guild_id].append(song_info)
            if not voice_client.is_playing() and not voice_client.is_paused():
                queues[guild_id].remove(song_info)
                await play_song(ctx, song_info, voice_client, is_loop=False)
        # Si no se está reproduciendo nada, comenzar a reproducir
        if not voice_client.is_playing() and not voice_client.is_paused():
            await play_next(ctx)

        # Enviar un embed con la información de la playlist
        embed = discord.Embed(
            title=tracks_info["name"],
            description=f"Duración {tracks_info['total_duration']} - {tracks_info['total_tracks']} canciones",
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=tracks_info.get("image"))
        await ctx.send(
            f"Se añadieron {tracks_info['total_tracks']} canciones de la playlist a la cola.",
            embed=embed,
        )

    except Exception as e:
        logging.exception("Error al manejar la playlist de Spotify")
        await ctx.send(f"Ocurrió un error: {e}")


# Función para extraer información con yt_dlp
async def ytdl_extract_info(url):
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, lambda: ytdl.extract_info(url, download=False)
    )
    return data


# Función para manejar canciones de YouTube
async def handle_youtube(ctx, query, voice_client, is_loop):
    guild_id = ctx.guild.id
    # Verificar si la consulta es una URL de YouTube
    if "youtube.com/watch?v=" in query or "youtu.be/" in query:
        youtube_url = query
    else:
        # Buscar en YouTube
        youtube_url = await search_youtube(query)
        if not youtube_url:
            await ctx.send("No se encontró la canción en YouTube.")
            return

    # Extraer información
    try:
        data = await ytdl_extract_info(youtube_url)

        song_info = {
            "title": data["title"],
            "duration": data["duration"],
            "thumbnail": data["thumbnail"],
            "song_url": data["url"],
            "youtube_url": data["original_url"],
        }

        # Si hay una canción reproduciéndose, añadir a la cola
        if voice_client.is_playing() or voice_client.is_paused():
            if guild_id not in queues:
                queues[guild_id] = []

            # Verificar si la canción ya está en la cola
            if any(
                song["youtube_url"] == song_info["youtube_url"]
                for song in queues[guild_id]
            ):
                await ctx.send("La canción ya está en la cola.")
                return

            queues[guild_id].append(song_info)
            # Enviar un embed
            embed = discord.Embed(
                title="🎶 Canción añadida a la cola",
                description=f"[{song_info['title']}]({song_info['youtube_url']})",
                color=discord.Color.green(),
            )
            embed.set_thumbnail(url=song_info["thumbnail"])
            embed.add_field(
                name="Duración",
                value=format_duration(song_info["duration"]),
                inline=True,
            )
            embed.add_field(
                name="En cola",
                value=f"{len(queues.get(guild_id, []))} canciones",
                inline=True,
            )
            embed.set_footer(text=f"Pedida por {ctx.author.display_name}")
            await ctx.send(embed=embed)
        else:
            # Si no hay nada reproduciéndose, reproducir la canción
            if is_loop:
                loop_song[guild_id] = song_info

            await play_song(ctx, song_info, voice_client, is_loop)

    except Exception as e:
        logging.exception("Error al manejar la canción de YouTube")
        await ctx.send(f"Ocurrió un error: {e}")


# Función para reproducir una canción
async def play_song(ctx, song_info, voice_client, is_loop):
    guild_id = ctx.guild.id

    # Función 'after' para manejar el fin de la canción
    def after_playing(error):
        if error:
            logging.error(f"Error en after_playing: {error}")
        if loop_flags.get(guild_id):
            # Reproducir la misma canción
            coro = play_song(ctx, song_info, voice_client, is_loop)
            asyncio.run_coroutine_threadsafe(coro, bot_discord.loop)
        else:
            # Reproducir la siguiente canción
            coro = play_next(ctx)
            asyncio.run_coroutine_threadsafe(coro, bot_discord.loop)

    # Reproducir la canción
    try:
        player = discord.FFmpegOpusAudio(song_info["song_url"], **ffmpeg_options)
        voice_client.play(player, after=after_playing)
    except Exception as e:
        logging.exception("Error al reproducir la canción")

    # Enviar un embed
    embed = discord.Embed(
        title="🎶 Ahora suena",
        description=f"[{song_info['title']}]({song_info['youtube_url']})",
        color=discord.Color.blue(),
    )
    embed.set_thumbnail(url=song_info["thumbnail"])
    embed.add_field(
        name="Duración", value=format_duration(song_info["duration"]), inline=True
    )
    embed.add_field(
        name="En cola", value=f"{len(queues.get(guild_id, []))} canciones", inline=True
    )
    embed.set_footer(text=f"Pedida por {ctx.author.display_name}")
    await ctx.send(embed=embed)


# Función para reproducir la siguiente canción
async def play_next(ctx):
    guild_id = ctx.guild.id
    voice_client = ctx.voice_client

    # Si la cola no está vacía
    if guild_id in queues and queues[guild_id]:
        next_song = queues[guild_id].pop(0)
        await play_song(ctx, next_song, voice_client, is_loop=False)
    else:
        # No hay más canciones, desconectar
        loop_flags[guild_id] = False
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()
            voice_clients.pop(guild_id, None)


# Función para formatear duración
def format_duration(duration):
    minutes = duration // 60
    seconds = duration % 60
    return f"{minutes}:{seconds:02d}"


# Función para buscar en YouTube
async def search_youtube(query):
    query_string = urllib.parse.urlencode({"search_query": query})
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://www.youtube.com/results?{query_string}"
        ) as response:
            if response.status == 200:
                html = await response.text()
                search_results = re.findall(r"/watch\?v=(.{11})", html)
                if search_results:
                    return f"https://www.youtube.com/watch?v={search_results[0]}"
    return None


# Función para obtener canciones de una playlist de Spotify
def get_spotify_playlist_tracks(playlist_url):
    try:
        playlist = client_spotipy.playlist(playlist_url)
        playlist_name = playlist["name"]
        playlist_owner = playlist["owner"]["display_name"]
        tracks = []
        total_duration_ms = 0

        for item in playlist["tracks"]["items"]:
            track = item["track"]
            artist_name = track["artists"][0]["name"]
            song_name = track["name"]
            song_duration_ms = track["duration_ms"]
            tracks.append({"artist": artist_name, "title": song_name})
            total_duration_ms += song_duration_ms

        total_duration_minutes = total_duration_ms // 60000
        total_duration_hours = total_duration_minutes // 60
        total_duration_str = f"{total_duration_hours}h {total_duration_minutes % 60}m"

        image_url = playlist["images"][0]["url"] if playlist["images"] else None

        return {
            "name": playlist_name,
            "owner": playlist_owner,
            "tracks": tracks,
            "total_duration": total_duration_str,
            "total_tracks": len(tracks),
            "image": image_url,
        }
    except Exception as e:
        logging.exception("Error al obtener canciones de la playlist de Spotify")
        return None
