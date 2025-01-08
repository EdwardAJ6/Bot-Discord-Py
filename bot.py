import asyncio
import logging
import threading
from datetime import datetime, timedelta

import discord
import requests
import spotipy
from commons.config import Config, bot_discord, loop_flags, queues, user_tokens, voice_clients
from commons.db import MongoDB
from discord.ext import commands
from dotenv import load_dotenv
from fastapi_app.app import run_fastapi
from play_music.bot_music import ensure_voice, format_duration, handle_spotify_playlist, handle_youtube
from spotipy.oauth2 import SpotifyOAuth

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


def calcular_tiempo_mejora(duracion_mejora, duracion_potenciador):
    try:
        # Potenciador 10x
        minutos_potenciador = duracion_potenciador.total_seconds() / 60
        avance_potenciador = minutos_potenciador * 10

        # Duración de la mejora en minutos
        minutos_mejora = duracion_mejora.total_seconds() / 60

        # Calcular el tiempo restante
        if avance_potenciador >= minutos_mejora:
            return timedelta(0)
        else:
            minutos_restantes = minutos_mejora - avance_potenciador
            return timedelta(minutes=minutos_restantes)
    except:
        raise Exception("Error en el formato de fechas, ejemplo: 12:00 12:00 Casa")


mejoras_activas = {}


@bot_discord.command(name="mejora_coc")
async def mejora(ctx, tiempo_mejora: str, tiempo_potenciador: str, nombre_estructura: str):
    try:
        usuario = ctx.author
        canal = ctx.channel

        # Parsear los tiempos
        tiempo_mejora_td = timedelta(hours=int(tiempo_mejora.split(":")[0]), minutes=int(tiempo_mejora.split(":")[1]))
        tiempo_potenciador_td = timedelta(
            hours=int(tiempo_potenciador.split(":")[0]), minutes=int(tiempo_potenciador.split(":")[1])
        )

        # Verificar si el potenciador dura más que el tiempo total de mejora
        if tiempo_potenciador_td >= tiempo_mejora_td:
            # Todo el tiempo de mejora estará potenciado
            tiempo_efectivo = tiempo_mejora_td / 10
        else:
            # Calcular el tiempo efectivo con el potenciador
            tiempo_reducido_con_potenciador = tiempo_potenciador_td * 10  # El potenciador multiplica el tiempo por 10.

            # Calcular el tiempo restante sin potenciador
            tiempo_restante_sin_potenciador = tiempo_mejora_td - tiempo_reducido_con_potenciador

            # Sumar ambos tiempos para obtener el tiempo efectivo total
            tiempo_efectivo = tiempo_potenciador_td + tiempo_restante_sin_potenciador

        # Calcular la hora de finalización
        hora_finalizacion = datetime.now() + tiempo_efectivo

        # Guardar la mejora en el diccionario
        mejoras_activas[nombre_estructura] = {
            "usuario": usuario,
            "hora_finalizacion": hora_finalizacion,
            "nombre": nombre_estructura,
        }

        # Enviar mensaje al usuario
        # Convertir tiempo efectivo a horas y minutos
        horas = int(tiempo_efectivo.total_seconds() // 3600)
        minutos = int((tiempo_efectivo.total_seconds() % 3600) // 60)

        await ctx.send(f"La mejora '{nombre_estructura}' estará lista en: {horas} horas y {minutos} minutos.")

        # Notificar al usuario cuando termine la mejora
        await notificar_mejora(canal, usuario, nombre_estructura, tiempo_efectivo)

    except Exception as e:
        await ctx.send(f"Error al calcular la mejora: {e}")


# Función para notificar cuando la mejora termina
async def notificar_mejora(canal, usuario, nombre_estructura, tiempo_espera):
    # Esperar el tiempo de la mejora
    await asyncio.sleep(tiempo_espera.total_seconds())
    await canal.send(f"🚀 {usuario.mention}, la mejora '{nombre_estructura}' ha terminado.")
    mejoras_activas.pop(nombre_estructura)


@bot_discord.command(name="tiempo_faltante")
async def tiempo_faltante(ctx):
    usuario = ctx.author
    mejoras_usuario = {k: v for k, v in mejoras_activas.items() if v["usuario"] == usuario}

    if not mejoras_usuario:
        await ctx.send("No tienes mejoras activas.")
        return

    # Crear menú interactivo
    opciones = "\n".join([f"{i+1}- {mejora}" for i, mejora in enumerate(mejoras_usuario.keys())])
    opciones += "\nall - Mostrar todas"

    await ctx.send(f"Selecciona una opción:\n{opciones}")

    def check(msg):
        return msg.author == usuario and msg.content.isdigit() or msg.content.lower() == "all"

    try:
        respuesta = await bot_discord.wait_for("message", check=check, timeout=30)
    except asyncio.TimeoutError:
        await ctx.send("Se agotó el tiempo de espera.")
        return

    if respuesta.content.lower() == "all":
        mensaje = ""
        for nombre, datos in mejoras_usuario.items():
            tiempo_restante = datos["hora_finalizacion"] - datetime.now()
            minutos, segundos = divmod(int(tiempo_restante.total_seconds()), 60)
            mensaje += f"⏳ **{nombre}**: {minutos} minutos y {segundos} segundos restantes.\n"
        await ctx.send(mensaje)

    else:
        indice = int(respuesta.content) - 1
        if indice < 0 or indice >= len(mejoras_usuario):
            await ctx.send("Opción inválida.")
            return

        nombre_seleccionado = list(mejoras_usuario.keys())[indice]
        datos_seleccionados = mejoras_usuario[nombre_seleccionado]
        tiempo_restante = datos_seleccionados["hora_finalizacion"] - datetime.now()

        await ctx.send(f"⏳ Tiempo restante para '{nombre_seleccionado}': {tiempo_restante}")


@bot_discord.command(name="shutdown_notice")
async def shutdown_notice(ctx, minutos: int = 15):
    """
    Envía un mensaje de aviso de cierre a todos los servidores donde está el bot.
    """
    message_content = f"⚠️ El bot se apgagara en {minutos} minutos."
    author = ctx.author.id
    delete_delay = 300  # 5 minutos en segundos
    notified_servers = 0

    if author != Config.ADMIN_ID:
        await ctx.send("No tienes permisos para ejecutar este comando.")
        return

    for guild in bot_discord.guilds:
        # if guild.id != 971889659468722288: # Server de pruebas
        #     continue
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                try:
                    message = await channel.send(message_content)
                    notified_servers += 1
                    # Programa la eliminación del mensaje después de 10 minutos
                    asyncio.create_task(delete_message_later(message, delete_delay))

                except Exception as e:
                    print(f"Error al enviar mensaje a {guild.name}: {e}")
                break  # Solo envía al primer canal encontrado con permisos
    await ctx.send(f"Mensaje de cierre enviado a ", "-".join([sv.name for sv in bot_discord.guilds]), " servidores.")


async def delete_message_later(message, delay):
    """
    Espera un tiempo específico antes de eliminar un mensaje.
    """
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception as e:
        print(f"Error al eliminar el mensaje en {message.channel.guild.name}: {e}")


if __name__ == "__main__":
    print("fast api up")
    fastapi_thread = threading.Thread(target=run_fastapi)
    fastapi_thread.start()

    bot_discord.run(Config.TOKEN_DISCORD)
