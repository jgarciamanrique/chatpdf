import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass
class PageText:
    page_number: int
    text: str


def _normalize_text(text: str) -> str:
    # Compacta espacios y saltos para mejorar el split por oraciones.
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def split_into_sentences(text: str) -> List[str]:
    """
    Divide en oraciones usando signos comunes de fin.
    Si el texto no tiene buena puntuación, se hace un fallback por saltos de línea.
    """
    text = _normalize_text(text)
    if not text:
        return []

    # Split por finales de oración (incluye . ! ? y casos con comillas).
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ0-9\"'¿¡])|(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if s and len(s.strip()) >= 20]

    # Fallback si el split falla (pocas oraciones).
    if len(sentences) <= 1:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip() and len(ln.strip()) >= 20]
        sentences = lines

    return sentences


def chunk_pages(
    pages: Sequence[PageText],
    target_min_chars: int = 800,
    target_max_chars: int = 1200,
    overlap_chars: int = 180,
) -> List[Dict]:
    """
    Chunking "inteligente" basado en oraciones (no solo caracteres).

    - Objetivo: ~target_min_chars a target_max_chars por chunk.
    - Overlap: se re-incluyen últimas oraciones de tamaño aproximado overlap_chars
      para preservar contexto entre chunks.

    Devuelve una lista de chunks con:
      - text: contenido del chunk
      - pages: lista de páginas que cubre el chunk
      - start_page / end_page: rangos (1-indexados)
    """
    # Convertimos cada página a (sentence, page_number)
    sentence_items: List[Tuple[str, int]] = []
    for p in pages:
        for sent in split_into_sentences(p.text):
            sentence_items.append((sent, p.page_number))

    if not sentence_items:
        return []

    chunks: List[Dict] = []
    current: List[Tuple[str, int]] = []
    current_len = 0

    def current_text(items: Iterable[Tuple[str, int]]) -> str:
        # Espaciado simple; al estar basado en oraciones suele mantener legibilidad.
        return " ".join(s for s, _ in items).strip()

    def pages_of(items: Iterable[Tuple[str, int]]) -> List[int]:
        return sorted({pg for _, pg in items})

    def take_overlap(items: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
        """
        Toma oraciones al final del chunk actual para el overlap.
        Mantiene el overlap por aproximación de caracteres.
        """
        overlap_items: List[Tuple[str, int]] = []
        acc = 0
        for sent, pg in reversed(items):
            sent_len = len(sent)
            if acc + sent_len > overlap_chars and overlap_items:
                break
            overlap_items.append((sent, pg))
            acc += sent_len
        overlap_items.reverse()
        return overlap_items

    for sent, pg in sentence_items:
        # Si el chunk está vacío, empezamos con la primera oración.
        if not current:
            current = [(sent, pg)]
            current_len = len(sent)
            continue

        tentative = current_text(current + [(sent, pg)])
        tentative_len = len(tentative)

        # Si cabe dentro del máximo objetivo, se agrega.
        if tentative_len <= target_max_chars:
            current.append((sent, pg))
            current_len = tentative_len
            continue

        # Si no cabe, finalizamos el chunk actual si ya alcanzó el mínimo.
        if current_len >= target_min_chars:
            text = current_text(current)
            pages_list = pages_of(current)
            chunks.append(
                {
                    "text": text,
                    "pages": pages_list,
                    "start_page": pages_list[0],
                    "end_page": pages_list[-1],
                }
            )
            # Preparar el nuevo chunk con overlap del anterior.
            current = take_overlap(current)
            current.append((sent, pg))
            current_len = len(current_text(current))
        else:
            # Aún no alcanzó el mínimo: forzamos a agregar hasta que progrese.
            current.append((sent, pg))
            current_len = len(current_text(current))

    # Finalizar último chunk
    if current:
        text = current_text(current)
        if text:
            pages_list = pages_of(current)
            chunks.append(
                {
                    "text": text,
                    "pages": pages_list,
                    "start_page": pages_list[0],
                    "end_page": pages_list[-1],
                }
            )

    return chunks

