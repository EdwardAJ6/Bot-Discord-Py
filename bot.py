import logging
import os
import threading

import discord
import requests
import spotipy
from discord.ext import commands
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

from commons.config import Config, bot_discord, loop_flags, queues, user_tokens, voice_clients
from commons.db import MongoDB
from fastapi_app.app import run_fastapi
from machine_learning.process import df_scaled, knn, recomienda_canciones_por_perfil
from play_music.bot_music import ensure_voice, format_duration, handle_spotify_playlist, handle_youtube
from spotify_operations.recommendation import spotipy_recomendar

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
    user_id = ctx.author.id
    mongo = MongoDB("bot_spotipy")
    user_data = await mongo.find_document({"user_id": str(user_id)}, "users")
    sp_oauth = SpotifyOAuth(
        client_id=Config.SPOTIPY_CLIENT_ID,
        client_secret=Config.SPOTIPY_CLIENT_SECRET,
        redirect_uri=Config.SPOTIPY_REDIRECT_URI,
    )
    token_info = sp_oauth.validate_token(user_data["token_info"])
    user_data["token_info"] = token_info
    user_data = await mongo.update_document("users", {"user_id": str(user_id)}, update={"$set": user_data})
    sp = spotipy.Spotify(auth=user_data["token_info"]["access_token"])

    if user_data and "top_tracks" in user_data:
        # Obtén las canciones y artistas favoritos
        top_tracks = user_data["top_tracks"]  # Asegúrate que esto contenga IDs de Spotify
        listened_tracks = user_data.get("listened_tracks", [])  # Lista de canciones que el usuario ha escuchado

        # Obtiene información de las canciones favoritas
        seed_tracks = []
        seed_artists = set()
        seed_genres = set()  # Esto será un conjunto para evitar duplicados

        for track_id in top_tracks:
            track_info = sp.track(track_id)
            # seed_tracks.append(track_id)  # ID de la canción
            seed_artists.add(track_info["artists"][0]["id"])  # Asumiendo que tomas el primer artista
            # Aquí puedes agregar lógica para obtener géneros, si es necesario
            # Ejemplo: seed_genres.update(track_info["genres"]) (esto requeriría información de géneros)

        # Llama a la función de recomendaciones de Spotipy
        try:
            recommendations = sp.recommendations(
                seed_tracks=seed_tracks,
                seed_artists=list(seed_artists)[:5],  # Convertir a lista
                seed_genres=list(seed_genres)[:5],  # Convertir a lista (vacío por ahora)
                limit=10,  # Ajusta el límite según sea necesario
            )
        except Exception as e:
            print(f"Error al obtener recomendaciones: {e}")
            await ctx.send("Hubo un error al obtener las recomendaciones.")
            return
            # Extrae el nombre y el ID de las canciones recomendadas
            # Obtener las canciones recomendadas junto con su ID y URL de imagen
        recommended_tracks = [
            (track["name"], track["id"], track["album"]["images"][0]["url"]) for track in recommendations["tracks"]
        ]

        # Filtrar las recomendaciones para excluir las que el usuario ya ha escuchado
        filtered_recommendations = [
            (name, track_id, img_url)
            for name, track_id, img_url in recommended_tracks
            if track_id not in listened_tracks
        ]

        # Si no hay recomendaciones filtradas, avisa al usuario
        if not filtered_recommendations:
            await ctx.send("No hay canciones recomendadas que no hayas escuchado.")
            return

        # Crear un embed para las recomendaciones
        embed = discord.Embed(title="Recomendaciones Musicales", color=discord.Color.blue())

        # Añadir las canciones recomendadas al embed con imágenes
        for name, track_id, img_url in filtered_recommendations:
            embed.add_field(name=name, value=f"[Escuchar](https://open.spotify.com/track/{track_id})", inline=False)
            embed.set_thumbnail(url=img_url)

        # Enviar el embed
        await ctx.send(embed=embed)

    else:
        await ctx.send("No se encontraron datos suficientes para recomendar.")


@bot_discord.command(name="login")
async def login(ctx):
    """
    Inicia el proceso de autenticación de Spotify.
    """
    sp_oauth = SpotifyOAuth(
        client_id=Config.SPOTIPY_CLIENT_ID,
        client_secret=Config.SPOTIPY_CLIENT_SECRET,
        redirect_uri=Config.SPOTIPY_REDIRECT_URI,
        scope="user-top-read",
    )
    try:
        if not Config.DEBUG:
            response = requests.get("http://127.0.0.1:4040/api/tunnels")
            response_data = response.json()
    except Exception as e:
        await ctx.send("Servicio de login inactivo, contacte al administrator")
        return

    auth_url = sp_oauth.get_authorize_url(state=str(ctx.author.id))
    await ctx.send(f"Por favor, autentícate usando este enlace: {auth_url}")


@bot_discord.command(name="mis-preferencias")
async def mis_preferencias(ctx):
    user_id = str(ctx.author.id)

    # Verifica que el usuario esté autenticado
    if user_id not in user_tokens:
        await ctx.send("Por favor, inicia sesión primero usando el comando `>login`.")
        return

    # Obtén el token de acceso y configura el cliente de Spotify
    token_info = user_tokens[user_id]
    sp = spotipy.Spotify(auth=token_info["access_token"])

    # Obtén las canciones o artistas favoritos
    top_tracks = sp.current_user_top_tracks(limit=10)  # puedes ajustar el límite según prefieras
    top_artists = sp.current_user_top_artists(limit=10)

    # Muestra la lista de canciones y artistas favoritos
    track_names = [track["name"] for track in top_tracks["items"]]
    artist_names = [artist["name"] for artist in top_artists["items"]]

    await ctx.send(f"**Tus canciones favoritas:** {', '.join(track_names)}")
    await ctx.send(f"**Tus artistas favoritos:** {', '.join(artist_names)}")


if __name__ == "__main__":
    print("fast api up")
    fastapi_thread = threading.Thread(target=run_fastapi)
    fastapi_thread.start()

    bot_discord.run(Config.TOKEN_DISCORD)
