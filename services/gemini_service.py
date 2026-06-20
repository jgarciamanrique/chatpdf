from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import google.generativeai as genai

from services.vector_service import RetrievedChunk

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class GeminiService:
    """Cliente real de Google Gemini para respuestas RAG y visión."""

    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        if not api_key or not api_key.strip():
            raise ValueError("GEMINI_API_KEY no está configurada.")
        genai.configure(api_key=api_key)
        self.model_name = model_name
        self.model = genai.GenerativeModel(model_name)

    def build_context(self, chunks: Sequence[RetrievedChunk], max_chars: int = 12000) -> str:
        parts: List[str] = []
        used = 0

        for idx, chunk in enumerate(chunks, start=1):
            pages_str = ", ".join(map(str, chunk.pages)) if chunk.pages else "N/A"
            block = f"[{idx}] Páginas: {pages_str}\n{chunk.text.strip()}"

            if used + len(block) > max_chars:
                break

            parts.append(block)
            used += len(block)

        return "\n\n".join(parts).strip()

    def _build_prompt(
        self,
        question: str,
        context: str,
        model_style: str,
        history: Sequence[Dict[str, str]],
        has_image: bool = False,
    ) -> str:
        image_note = (
            "También se adjuntó una imagen. Analízala junto con el contexto del PDF si es relevante.\n\n"
            if has_image
            else ""
        )

        prompt = (
            "Eres un asistente que responde usando el contexto del PDF"
            + (" y la imagen adjunta" if has_image else "")
            + ".\n"
            "Si la información no aparece en el documento ni en la imagen, indícalo claramente.\n"
            "No inventes datos.\n\n"
            f"Estilo: {model_style}\n\n"
            f"{image_note}"
            f"Contexto del PDF:\n{context or '(Sin contexto relevante del PDF)'}\n\n"
            f"Pregunta: {question}\n\n"
            "Responde de forma clara y útil."
        )

        if history:
            recent = history[-6:]
            history_lines = []
            for msg in recent:
                role = "Usuario" if msg.get("role") == "user" else "Asistente"
                content = msg.get("content", "")
                if content:
                    history_lines.append(f"{role}: {content[:400]}")
            if history_lines:
                prompt = "Historial reciente:\n" + "\n".join(history_lines) + "\n\n" + prompt

        return prompt

    def _extract_text(self, response) -> str:
        text = getattr(response, "text", "") or ""
        if not text and getattr(response, "candidates", None):
            parts = response.candidates[0].content.parts
            text = "".join(getattr(part, "text", "") for part in parts)
        return text.strip()

    def answer(
        self,
        question: str,
        context_chunks: Sequence[RetrievedChunk],
        history: Sequence[Dict[str, str]],
        model_style: str,
        temperature: float = 0.35,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None,
    ) -> str:
        context = self.build_context(context_chunks)
        has_image = bool(image_bytes and image_mime)
        prompt = self._build_prompt(question, context, model_style, history, has_image=has_image)

        content_parts: List = [prompt]
        if has_image:
            content_parts.append({"mime_type": image_mime, "data": image_bytes})

        try:
            response = self.model.generate_content(
                content_parts,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": 800,
                },
            )
        except Exception as e:
            raise RuntimeError(f"Error consultando Gemini: {e}") from e

        return self._extract_text(response)

