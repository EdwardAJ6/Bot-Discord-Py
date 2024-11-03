import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler

# Carga el dataset
df = pd.read_csv("dataset.csv")

# Limpia valores nulos si existen
df.dropna(inplace=True)

# Escala características
scaler = MinMaxScaler()
scaled_features = scaler.fit_transform(df[["danceability", "energy", "valence", "tempo", "popularity"]])
df_scaled = pd.DataFrame(scaled_features, columns=["danceability", "energy", "valence", "tempo", "popularity"])

# Agrega el user_id y track_id de vuelta si los necesitas en el dataset
df_scaled["user_id"] = df["user_id"]
df_scaled["track_id"] = df["track_id"]

# Divide en conjunto de entrenamiento y prueba
train, test = train_test_split(df_scaled, test_size=0.2, random_state=42)


from sklearn.neighbors import NearestNeighbors

# Entrena el modelo K-Nearest Neighbors con características de las canciones
knn = NearestNeighbors(n_neighbors=5, metric="cosine")
knn.fit(train[["danceability", "energy", "valence", "tempo", "popularity"]])

# Prueba el modelo con canciones en el conjunto de prueba (usualmente basado en el promedio de un usuario o de una canción específica)


import numpy as np


def recomienda_canciones_por_perfil(user_profile, knn_model, df, n_recommendations=5):
    """
    Genera recomendaciones basadas en el perfil promedio de un usuario.
    """
    # Encuentra los vecinos más cercanos en base al perfil promedio
    distances, indices = knn_model.kneighbors(user_profile, n_neighbors=n_recommendations + 1)

    # Obtiene las canciones recomendadas excluyendo los top_tracks
    recommended_indices = indices[0]
    recommended_songs = df.iloc[recommended_indices]["track_id"].values
    return recommended_songs
