from __future__ import annotations

from typing import Dict, List, Sequence

from groq import Groq

from services.vector_service import RetrievedChunk


class GroqService:
    def __init__(self, api_key: str, default_model: str = "llama-3.3-70b-versatile"):
        if not api_key or not api_key.strip():
            raise ValueError("GROQ_API_KEY no está configurada.")
        self.client = Groq(api_key=api_key)
        self.default_model = default_model

    def build_context(self, chunks: Sequence[RetrievedChunk], max_chars: int = 12000) -> str:
        parts: List[str] = []
        used = 0

        for idx, c in enumerate(chunks, start=1):
            pages_str = ", ".join(map(str, c.pages)) if c.pages else "N/A"
            header = f"[{idx}] Páginas: {pages_str}\n"
            body = c.text.strip()
            block = header + body

            if used + len(block) > max_chars:
                break

            parts.append(block)
            used += len(block)

        return "\n\n".join(parts).strip()

    def answer(
        self,
        question: str,
        context_chunks: Sequence[RetrievedChunk],
        history: Sequence[Dict[str, str]],
        *,
        groq_model: str,
        model_style: str,
        temperature: float = 0.3,
        max_tokens: int = 800,
    ) -> str:
        context = self.build_context(context_chunks)

        system_prompt = (
            "Eres un asistente que responde preguntas SOLO usando el contexto proporcionado del PDF. "
            "Si la información no aparece en el documento, responde claramente que NO está presente en el PDF. "
            "No inventes datos.\n\n"
            f"Estilo del modelo activo:\n{model_style}"
        )

        user_prompt = (
            f"Pregunta del usuario:\n{question}\n\n"
            f"Contexto recuperado del PDF:\n{context}\n\n"
            "Responde únicamente usando el contexto anterior. "
            "Si la información no existe en el documento, indica claramente que no aparece en el PDF. "
            "No inventes información."
        )

        trimmed_history = list(history)[-10:]
        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

        for m in trimmed_history:
            role = m.get("role", "")
            content = m.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_prompt})

        try:
            completion = self.client.chat.completions.create(
                model=groq_model or self.default_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            raise RuntimeError(f"Error consultando Groq: {e}") from e

        content = completion.choices[0].message.content if completion.choices else ""
        return (content or "").strip()
