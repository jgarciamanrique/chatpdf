from __future__ import annotations

from typing import List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer


class EmbeddingService:
    """
    Encapsula el modelo sentence-transformers.
    Se carga una sola vez y se reutiliza.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model: Optional[SentenceTransformer] = None

    def load(self) -> None:
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self.load()
        assert self._model is not None
        return self._model

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """
        Devuelve embeddings en float32 normalizados (útil para cosine similarity).
        """
        if not texts:
            return np.zeros((0, self.model.get_sentence_embedding_dimension()), dtype=np.float32)

        try:
            embeddings = self.model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as e:
            raise RuntimeError(f"Error generando embeddings: {e}") from e

        return embeddings.astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        """
        Devuelve un vector 2D (shape: [1, dim]) normalizado.
        """
        try:
            emb = self.model.encode(
                [query],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as e:
            raise RuntimeError(f"Error generando embeddings de la consulta: {e}") from e

        return emb.astype(np.float32)

