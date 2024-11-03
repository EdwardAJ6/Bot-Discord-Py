import uvicorn
from fastapi import FastAPI, Request
from spotipy.oauth2 import SpotifyOAuth

from commons.config import Config
from commons.db import MongoDB
from spotify_operations.recolect_preference import recolecta_preferencias

app = FastAPI()


@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    user_id = request.query_params.get("state")  # Usar el ID de usuario como estado

    sp_oauth = SpotifyOAuth(
        client_id=Config.SPOTIPY_CLIENT_ID,
        client_secret=Config.SPOTIPY_CLIENT_SECRET,
        redirect_uri=Config.SPOTIPY_REDIRECT_URI,
    )
    token_info = sp_oauth.get_access_token(code, check_cache=False)

    if token_info:
        mongo = MongoDB("bot_spotipy")
        document = {
            "user_id": user_id,
            "token_info": token_info,
        }
        await mongo.insert_document(document, "users", upsert=True, query={"user_id": user_id})
        await recolecta_preferencias(user_id)
        return {"message": "Autenticación exitosa! Puedes cerrar esta ventana y regresar a Discord."}
    else:
        return {"message": "Error al obtener el token de acceso."}


def run_fastapi():
    uvicorn.run(app, host="127.0.0.1", port=Config.FAST_API_PORT)
