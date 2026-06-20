from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import faiss
import numpy as np

from services.embedding_service import EmbeddingService


@dataclass
class RetrievedChunk:
    text: str
    pages: List[int]
    score: float
    start_page: int
    end_page: int


class VectorService:
    def __init__(self, vector_store_dir: Path, embedding_service: EmbeddingService):
        self.vector_store_dir = vector_store_dir
        self.embedding_service = embedding_service

        # Cache simple para no recargar FAISS y metadata constantemente.
        self._cache: Dict[str, Tuple[faiss.Index, List[Dict[str, Any]]]] = {}
        self._cache_max = 3

    def _collection_dir(self, collection_id: str) -> Path:
        return self.vector_store_dir / collection_id

    def _index_path(self, collection_id: str) -> Path:
        return self._collection_dir(collection_id) / "index.faiss"

    def _meta_path(self, collection_id: str) -> Path:
        return self._collection_dir(collection_id) / "chunks.json"

    def _ensure_dir(self, collection_id: str) -> None:
        self._collection_dir(collection_id).mkdir(parents=True, exist_ok=True)

    def build_and_save(
        self,
        collection_id: str,
        chunks: Sequence[Dict[str, Any]],
    ) -> None:
        """
        Crea índice FAISS y guarda:
          - index.faiss
          - chunks.json (texto + páginas y metadata)
        """
        if not chunks:
            raise ValueError("No hay chunks para indexar.")

        self._ensure_dir(collection_id)

        texts = [c["text"] for c in chunks]
        embeddings = self.embedding_service.embed_texts(texts)

        dim = embeddings.shape[1]
        # Índice con similitud coseno por embeddings normalizados.
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)

        faiss.write_index(index, str(self._index_path(collection_id)))
        with open(self._meta_path(collection_id), "w", encoding="utf-8") as f:
            json.dump(list(chunks), f, ensure_ascii=False)

        # Limpia cache para evitar inconsistencias.
        if collection_id in self._cache:
            del self._cache[collection_id]

    def _load_collection(self, collection_id: str) -> Tuple[faiss.Index, List[Dict[str, Any]]]:
        if collection_id in self._cache:
            return self._cache[collection_id]

        idx_path = self._index_path(collection_id)
        meta_path = self._meta_path(collection_id)
        if not idx_path.exists() or not meta_path.exists():
            raise FileNotFoundError("Índice no encontrado. Sube un PDF primero.")

        index = faiss.read_index(str(idx_path))
        with open(meta_path, "r", encoding="utf-8") as f:
            chunks = json.load(f)

        # Cache simple.
        if len(self._cache) >= self._cache_max:
            # Borra el primero insertado.
            first_key = next(iter(self._cache.keys()))
            del self._cache[first_key]
        self._cache[collection_id] = (index, chunks)

        return index, chunks

    def search(self, collection_id: str, query: str, top_k: int = 5) -> List[RetrievedChunk]:
        index, chunks = self._load_collection(collection_id)

        top_k = max(1, int(top_k))
        top_k = min(top_k, len(chunks))

        query_vec = self.embedding_service.embed_query(query)
        # FAISS espera shape [nq, dim]
        scores, indices = index.search(query_vec, top_k)

        results: List[RetrievedChunk] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(chunks):
                continue
            c = chunks[idx]
            pages = c.get("pages", [])
            start_page = int(c.get("start_page", pages[0] if pages else 1))
            end_page = int(c.get("end_page", pages[-1] if pages else start_page))

            results.append(
                RetrievedChunk(
                    text=c["text"],
                    pages=pages,
                    score=float(score),
                    start_page=start_page,
                    end_page=end_page,
                )
            )

        return results

