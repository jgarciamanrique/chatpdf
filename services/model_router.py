"""
Enrutador multi-modelo: solo Gemini (Google) y Grok (Groq).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

MODEL_TAG_PATTERN = re.compile(r"\[model:(\w+)\]", re.IGNORECASE)

DEFAULT_MODEL = "gemini"

# Solo Gemini y Grok, con versión visible en la etiqueta.
MODEL_CONFIG: Dict[str, Dict] = {
    "gemini": {
        "label": "Gemini 2.0 Flash · Google",
        "version": "gemini-2.0-flash",
        "provider": "gemini",
        "temperature": 0.35,
        "style": (
            "Responde de forma explicativa y educativa. "
            "Amplía conceptos clave, da contexto y ejemplos breves cuando sea útil."
        ),
    },
    "grok": {
        "label": "Grok · Llama 3.3 70B · Groq",
        "version": "llama-3.3-70b-versatile",
        "provider": "groq",
        "groq_model": "llama-3.3-70b-versatile",
        "temperature": 0.55,
        "style": (
            "Responde con tono informal, relajado y con un toque de humor inteligente. "
            "Puedes ser ligeramente sarcástico si encaja, pero mantén la utilidad."
        ),
    },
}


@dataclass
class RoutedModel:
    model_id: str
    label: str
    version: str
    provider: str
    temperature: float
    style: str
    groq_model: str = ""
    fallback_used: bool = False
    clean_question: str = ""


def parse_model_tag(question: str) -> Tuple[Optional[str], str]:
    match = MODEL_TAG_PATTERN.search(question)
    if not match:
        return None, question.strip()

    model_id = match.group(1).lower()
    clean = MODEL_TAG_PATTERN.sub("", question).strip()
    clean = re.sub(r"\s+", " ", clean)
    return model_id, clean


def resolve_model(question: str, ui_default: str = DEFAULT_MODEL) -> RoutedModel:
    tagged_model, clean_question = parse_model_tag(question)
    requested = (tagged_model or ui_default or DEFAULT_MODEL).lower().strip()

    fallback_used = requested not in MODEL_CONFIG
    model_id = DEFAULT_MODEL if fallback_used else requested
    config = MODEL_CONFIG[model_id]

    return RoutedModel(
        model_id=model_id,
        label=config["label"],
        version=config["version"],
        provider=config["provider"],
        groq_model=config.get("groq_model", ""),
        temperature=config["temperature"],
        style=config["style"],
        fallback_used=fallback_used,
        clean_question=clean_question or question.strip(),
    )


def format_answer(label: str, answer: str, fallback_used: bool = False) -> str:
    prefix = f"Model: {label}"
    if fallback_used:
        prefix += "\nModelo no disponible, usando predeterminado."
    return f"{prefix}\n{answer.strip()}"
