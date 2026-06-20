from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from utils.chunking import PageText


@dataclass
class ExtractedPage:
    page_number: int
    text: str


class PDFService:
    def extract_pages(self, pdf_path: Path, max_pages: int = 500) -> List[ExtractedPage]:
        """
        Extrae texto página por página.

        - page_number es 1-indexado para mostrar fuentes de forma natural.
        - Si una página no tiene texto, se devuelve vacío para mantener el mapeo.
        """
        try:
            reader = PdfReader(str(pdf_path))
        except PdfReadError as e:
            raise ValueError(f"PDF corrupto o ilegible: {e}") from e

        total_pages = len(reader.pages)
        if total_pages == 0:
            raise ValueError("El PDF no contiene páginas.")
        if total_pages > max_pages:
            # Restricción requerida por el usuario.
            raise ValueError(f"El PDF tiene {total_pages} páginas. Máximo permitido: {max_pages}.")

        extracted: List[ExtractedPage] = []
        for idx, page in enumerate(reader.pages):
            page_num = idx + 1
            text = page.extract_text() or ""
            extracted.append(ExtractedPage(page_number=page_num, text=text))

        return extracted


def build_page_texts(pages: Sequence[ExtractedPage]) -> List[PageText]:
    """
    Convierte páginas extraídas a PageText (dataclass del chunker).
    """
    cleaned: List[PageText] = []
    for p in pages:
        # Conservamos el mapeo por página incluso si está vacía;
        # el chunker descartará oraciones vacías.
        cleaned.append(PageText(page_number=p.page_number, text=p.text or ""))
    return cleaned

