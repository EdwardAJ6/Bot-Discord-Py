import uvicorn
from fastapi import FastAPI, Request
from spotipy.oauth2 import SpotifyOAuth

from variables import SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI, user_tokens

app = FastAPI()


@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    user_id = request.query_params.get("state")  # Usar el ID de usuario como estado

    sp_oauth = SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET, redirect_uri=SPOTIPY_REDIRECT_URI
    )
    token_info = sp_oauth.get_access_token(code)

    if token_info:
        user_tokens[user_id] = token_info
        return {"message": "Autenticación exitosa! Puedes cerrar esta ventana y regresar a Discord."}
    else:
        return {"message": "Error al obtener el token de acceso."}


def run_fastapi():
    uvicorn.run(app, host="127.0.0.1", port=8001)
