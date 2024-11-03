import pandas as pd
from spotipy import Spotify

from commons.db import MongoDB


async def recolecta_preferencias(user_id):
    # Obtén el token del usuario desde MongoDB
    mongo = MongoDB("bot_spotipy")
    user = await mongo.find_document(
        query={
            "user_id": user_id,
        },
        collection="users",
    )
    if user is None and not user.get("token_info"):
        return {"message": "Error al obtener el token de acceso."}

    sp = Spotify(auth=user["token_info"]["access_token"])

    # Extrae canciones y artistas favoritos
    top_tracks = sp.current_user_top_tracks(limit=10)
    top_artists = sp.current_user_top_artists(limit=10)

    track_ids = [track["id"] for track in top_tracks["items"]]
    artist_ids = [artist["id"] for artist in top_artists["items"]]

    # Guarda los datos en la colección de preferencias

    user = await mongo.update_document(
        "users",
        {"user_id": user_id},
        {"$set": {"top_tracks": track_ids, "top_artists": artist_ids}},
        upsert=True,  # Crea el documento si no existe
    )
    await construye_dataset(user)
    return


async def construye_dataset(user: dict):

    sp = Spotify(auth=user["token_info"]["access_token"])

    await guarda_caracteristicas_en_mongo(user, sp)  # Guarda como CSV
    return


async def guarda_dataset_csv(dataset):
    df = pd.DataFrame(dataset)
    # 'a' para agregar y 'header=False' para no duplicar los encabezados si el archivo ya existe
    df.to_csv("dataset.csv", mode="a", header=not pd.io.common.file_exists("dataset.csv"), index=False)


async def extrae_caracteristicas_canciones(track_ids, sp: Spotify):
    audio_features = sp.audio_features(track_ids)

    caracteristicas_canciones = []
    for features in audio_features:
        if features:
            caracteristicas_canciones.append(
                {
                    "track_id": features["id"],
                    "danceability": features["danceability"],
                    "energy": features["energy"],
                    "valence": features["valence"],
                    "tempo": features["tempo"],
                    "popularity": sp.track(features["id"])["popularity"],  # Añade popularidad
                    # Agrega más atributos relevantes aquí si es necesario
                }
            )
    return caracteristicas_canciones


async def guarda_caracteristicas_en_mongo(user: dict, sp: Spotify):
    mongo = MongoDB("bot_spotipy")  # Instancia MongoDB si no lo tienes globalmente

    track_ids = user["top_tracks"]

    caracteristicas_canciones = await extrae_caracteristicas_canciones(track_ids, sp)
    data_set = []
    for caracteristica in caracteristicas_canciones:
        document = {
            "user_id": user["user_id"],
            "track_id": caracteristica["track_id"],
            **caracteristica,  # Agrega más atributos relevantes aquí si es necesario
        }
        await mongo.insert_document(collection="dataset", document=document)
        del document["_id"]
        data_set.append(document)
    await guarda_dataset_csv(data_set)
