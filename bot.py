import logging
import os
import threading

import discord
import requests
import spotipy
from discord.ext import commands
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

from fastapi_app.app import run_fastapi
from play_music.bot_music import (
    bot_discord,
    ensure_voice,
    format_duration,
    handle_spotify_playlist,
    handle_youtube,
    loop_flags,
    queues,
    voice_clients,
)
from variables import SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI, TOKEN_DISCORD, user_tokens

STATUS_URL = "http://localhost:8000/current-status"  # URL del endpoint de consulta de estado
load_dotenv()


# Comando 'hola'
@bot_discord.command(name="hola")
async def hola(ctx):
    logging.info("El comando hola se ha ejecutado.")
    await ctx.send("¡Hola!")


# Evento 'on_ready'
@bot_discord.event
async def on_ready():
    await bot_discord.change_presence(activity=discord.Streaming(name="Reproduciendo música", url="https://discord"))
    logging.info(f"Bot conectado como {bot_discord.user}")


# Comando 'status'
@bot_discord.command(name="status")
async def status(ctx):
    try:
        response = requests.get(STATUS_URL)
        status = response.json().get("status", "No status available")
        await ctx.send(f"Status del servidor: {status}")
    except Exception as e:
        logging.exception("Error al obtener el estado")
        await ctx.send(f"Error al obtener el estado: {e}")


# Comando 'ip_server'
@bot_discord.command(name="ip_server")
async def ip_server(ctx):
    try:
        response = requests.get("http://127.0.0.1:4040/api/tunnels")
        response_data = response.json()

        for tunnel in response_data.get("tunnels", []):
            if tunnel.get("proto") == "tcp":
                public_url = tunnel.get("public_url")
                await ctx.send(f"IP del servidor: {public_url}")
                return
        await ctx.send("No se encontró un túnel TCP activo.")
    except Exception as e:
        logging.exception("Error al obtener la IP del servidor")
        await ctx.send(f"Error: {e}")


# Comando 'play'
@bot_discord.command(name="p")
async def play(ctx, *, query):
    guild_id = ctx.guild.id
    is_loop = False

    # Verificar si 'loop' está en la consulta
    if " loop" in query:
        is_loop = True
        query = query.replace(" loop", "")

    loop_flags[guild_id] = is_loop

    # Verificar si el usuario está en un canal de voz
    if not ctx.author.voice:
        await ctx.send("¡Tienes que estar en un canal de voz para reproducir música!")
        return

    # Conectar al canal de voz
    try:
        voice_client = await ensure_voice(ctx)
    except commands.CommandError:
        return

    # Manejar playlist de Spotify
    if "open.spotify.com/playlist/" in query:
        await handle_spotify_playlist(ctx, query, voice_client, is_loop)
        return

    # Manejar enlace o búsqueda de YouTube
    await handle_youtube(ctx, query, voice_client, is_loop)


# Comando 'pause'
@bot_discord.command(name="pause")
async def pause(ctx):
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await ctx.send("Canción pausada.")
    else:
        await ctx.send("No hay ninguna canción reproduciéndose.")


# Comando 'resume'
@bot_discord.command(name="resume")
async def resume(ctx):
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await ctx.send("Reproducción reanudada.")
    else:
        await ctx.send("No hay ninguna canción pausada.")


# Comando 'stop'
@bot_discord.command(name="stop")
async def stop(ctx):
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        voice_clients.pop(ctx.guild.id, None)
        queues.pop(ctx.guild.id, None)
        loop_flags.pop(ctx.guild.id, None)
        await ctx.send("Deteniendo la reproducción y saliendo del canal de voz.")
    else:
        await ctx.send("No estoy conectado a ningún canal de voz.")


# Comando 'queue'
@bot_discord.command(name="queue")
async def show_queue(ctx):
    guild_id = ctx.guild.id
    if guild_id in queues and queues[guild_id]:
        queue_list = queues[guild_id]
        queue_message = ""
        for i, song in enumerate(queue_list[:10], 1):
            queue_message += f"{i}. {song['title']} - {format_duration(song['duration'])}\n"
        embed = discord.Embed(title="🎶 Canciones en cola", description=queue_message, color=discord.Color.green())
        embed.set_footer(text=f"Mostrando las primeras {min(10, len(queue_list))} canciones")
        await ctx.send(embed=embed)
    else:
        await ctx.send("La cola está vacía.")


# Comando 'skip'
@bot_discord.command(name="skip")
async def skip(ctx):
    voice_client = ctx.voice_client
    guild_id = ctx.guild.id
    if voice_client and voice_client.is_playing():
        loop_flags[guild_id] = False  # Desactivar loop
        voice_client.stop()
        await ctx.send("Canción actual saltada.")
    else:
        await ctx.send("No hay ninguna canción reproduciéndose.")


# Comando 'clear_queue'
@bot_discord.command(name="clear_queue")
async def clear_queue(ctx):
    guild_id = ctx.guild.id
    if guild_id in queues:
        queues[guild_id].clear()
        await ctx.send("Cola borrada.")
    else:
        await ctx.send("La cola ya está vacía.")


@bot_discord.command(name="recomendar")
async def recomendar(ctx, tipo: str = "cancion"):
    """
    Comando para recomendar canciones o artistas.
    """
    user_id = ctx.author.id
    token_info = user_tokens.get(str(user_id))

    if not token_info:
        await ctx.send("Necesitas autenticarte primero usando el comando >login.")
        return

    sp = spotipy.Spotify(auth=token_info["access_token"])

    try:
        if tipo == "cancion":
            top_tracks = sp.current_user_top_tracks(limit=1)
            if top_tracks["items"]:
                track = top_tracks["items"][0]
                embed = discord.Embed(
                    title="🎶 Canción Recomendada",
                    description=f"Te recomiendo escuchar **{track['name']}** de **{track['artists'][0]['name']}**.",
                    color=discord.Color.green(),
                )
                embed.add_field(name="Escuchar en Spotify", value=track["external_urls"]["spotify"], inline=False)
                embed.set_image(url=track["album"]["images"][1]["url"])  # Imagen del álbum
                await ctx.send(embed=embed)
            else:
                await ctx.send("No pude encontrar recomendaciones de canciones para ti.")

        elif tipo == "artista":
            top_artists = sp.current_user_top_artists(limit=1)
            if top_artists["items"]:
                artist = top_artists["items"][0]
                embed = discord.Embed(
                    title="🎤 Artista Recomendado",
                    description=f"Te recomiendo el artista **{artist['name']}**. ¡Es uno de tus favoritos!",
                    color=discord.Color.blue(),
                )
                embed.add_field(name="Escuchar en Spotify", value=artist["external_urls"]["spotify"], inline=False)
                embed.set_image(url=artist["images"][1]["url"])  # Imagen del artista

                await ctx.send(embed=embed)
            else:
                await ctx.send("No pude encontrar recomendaciones de artistas para ti.")
        else:
            await ctx.send("Especifica `cancion` o `artista` para recibir una recomendación.")

    except Exception as e:
        await ctx.send("Ocurrió un error al obtener las recomendaciones.")
        print(e)


@bot_discord.command(name="login")
async def login(ctx):
    """
    Inicia el proceso de autenticación de Spotify.
    """
    sp_oauth = SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope="user-top-read",
    )
    auth_url = sp_oauth.get_authorize_url(state=str(ctx.author.id))
    await ctx.send(f"Por favor, autentícate usando este enlace: {auth_url}")


if __name__ == "__main__":
    fastapi_thread = threading.Thread(target=run_fastapi)
    fastapi_thread.start()

    bot_discord.run(TOKEN_DISCORD)
