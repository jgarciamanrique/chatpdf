from __future__ import annotations

from typing import List, Optional

import numpy as np

try:
    from fastembed import TextEmbedding
except ImportError:  # pragma: no cover
    TextEmbedding = None  # type: ignore[misc, assignment]


class EmbeddingService:
    """
    Embeddings ligeros con fastembed (ONNX).
    Usa mucha menos RAM que sentence-transformers + PyTorch (ideal para Render Free).
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        aliases = {
            "all-minilm-l6-v2": "sentence-transformers/all-MiniLM-L6-v2",
            "all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
        }
        self.model_name = aliases.get(model_name, model_name)
        self._model: Optional["TextEmbedding"] = None
        self._dim = 384

    def load(self) -> None:
        if self._model is None:
            if TextEmbedding is None:
                raise RuntimeError("fastembed no está instalado.")
            self._model = TextEmbedding(model_name=self.model_name)
            sample = list(self._model.embed(["warmup"]))
            if sample:
                self._dim = len(sample[0])

    @property
    def model(self) -> "TextEmbedding":
        if self._model is None:
            self.load()
        assert self._model is not None
        return self._model

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.maximum(norms, 1e-12)

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)

        try:
            embeddings = np.array(list(self.model.embed(texts)), dtype=np.float32)
        except Exception as e:
            raise RuntimeError(f"Error generando embeddings: {e}") from e

        return self._normalize(embeddings).astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        try:
            emb = np.array(list(self.model.embed([query])), dtype=np.float32)
        except Exception as e:
            raise RuntimeError(f"Error generando embeddings de la consulta: {e}") from e

        return self._normalize(emb).astype(np.float32)
