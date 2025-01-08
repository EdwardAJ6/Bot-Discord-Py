import discord
import spotipy

from commons.config import bot_discord, client_spotipy


async def spotipy_recomendar(ctx, client_spotipy: spotipy.Spotify, tipo: str):
    try:
        if tipo == "cancion":
            top_tracks = client_spotipy.current_user_top_tracks(limit=1)
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
            top_artists = client_spotipy.current_user_top_artists(limit=1)
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
