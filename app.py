import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from services.embedding_service import EmbeddingService
from services.gemini_service import ALLOWED_IMAGE_TYPES, GeminiService
from services.groq_service import GroqService
from services.model_router import DEFAULT_MODEL, MODEL_CONFIG, format_answer, resolve_model
from services.pdf_service import PDFService, build_page_texts
from services.vector_service import RetrievedChunk, VectorService
from utils.chunking import chunk_pages


BASE_DIR = Path(__file__).parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)
UPLOAD_DIR = BASE_DIR / "uploads"
VECTOR_STORE_DIR = BASE_DIR / "vector_store"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ChatPDF - RAG con FastAPI + FAISS + Groq")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

embedding_service = EmbeddingService(model_name="all-MiniLM-L6-v2")
pdf_service = PDFService()

vector_service = VectorService(vector_store_dir=VECTOR_STORE_DIR, embedding_service=embedding_service)

groq_api_key = os.getenv("GROQ_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")

try:
    groq_service = GroqService(api_key=groq_api_key, default_model="llama-3.3-70b-versatile")
except ValueError as e:
    groq_service = None
    groq_init_error = str(e)

try:
    gemini_service = GeminiService(api_key=gemini_api_key, model_name="gemini-2.0-flash")
except ValueError as e:
    gemini_service = None
    gemini_init_error = str(e)


# Historial en memoria por sesión (solo dura mientras el servidor está encendido).
session_history: Dict[str, List[Dict[str, str]]] = {}


class UploadResponse(BaseModel):
    collection_id: str
    pages_extracted: int
    chunks_indexed: int
    filename: str


class ChatRequest(BaseModel):
    session_id: str
    collection_id: str
    question: str
    top_k: Optional[int] = 5
    model: Optional[str] = "gemini"


class ChatResponse(BaseModel):
    answer: str
    sources_pages: List[int]
    model: str
    model_label: str


@app.on_event("startup")
def _startup() -> None:
    # Carga anticipada del modelo de embeddings para evitar esperas en el primer request.
    embedding_service.load()


@app.get("/health")
def health():
    """Comprobación ligera para Render y monitores."""
    return {"status": "ok", "groq": groq_service is not None}


def _find_pdf_path(collection_id: str) -> Path:
    """Busca el PDF guardado asociado a un collection_id."""
    matches = list(UPLOAD_DIR.glob(f"{collection_id}_*.pdf"))
    if not matches:
        raise FileNotFoundError("PDF no encontrado para esta sesión.")
    return matches[0]


@app.get("/pdf/{collection_id}")
def get_pdf(collection_id: str):
    """Sirve el PDF subido para visualizarlo en el panel izquierdo."""
    try:
        pdf_path = _find_pdf_path(collection_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name.split("_", 1)[-1],
        headers={"Content-Disposition": "inline"},
    )


@app.get("/models")
def list_models():
    """Lista modelos disponibles para el selector de la UI."""
    return {
        "default": DEFAULT_MODEL,
        "models": [
            {
                "id": mid,
                "label": cfg["label"],
                "version": cfg["version"],
                "provider": cfg["provider"],
            }
            for mid, cfg in MODEL_CONFIG.items()
        ],
    }


@app.get("/")
def home(request: Request):
    # Compatibilidad con la firma actual de Starlette/FastAPI:
    # TemplateResponse(request=..., name=..., context=...)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request},
    )


@app.post("/upload", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    session_id: str = Form(...),
):
    """
    Recibe un PDF, extrae texto, hace chunking inteligente, crea embeddings y guarda FAISS.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No se proporcionó un archivo.")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos PDF.")

    # Valida tamaño máximo (50MB)
    content = await file.read()
    max_bytes = 50 * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail="El PDF excede el tamaño máximo permitido (50 MB).")

    collection_id = str(uuid.uuid4())
    pdf_path = UPLOAD_DIR / f"{collection_id}_{file.filename}"
    pdf_path.write_bytes(content)

    # Asegura historial vacío si es primera vez.
    session_history.setdefault(session_id, [])

    try:
        extracted_pages = pdf_service.extract_pages(pdf_path, max_pages=500)

        # Convierte a PageText que usa el chunker.
        page_texts = build_page_texts(extracted_pages)

        # Detecta PDF "vacío"
        total_text_chars = sum(len(p.text or "") for p in page_texts)
        if total_text_chars == 0:
            raise ValueError("El PDF no contiene texto extraíble.")

        chunks = chunk_pages(
            pages=page_texts,
            target_min_chars=800,
            target_max_chars=1200,
            overlap_chars=180,
        )

        if not chunks:
            raise ValueError("No se pudieron crear chunks a partir del PDF.")

        # Indexa y persiste
        vector_service.build_and_save(collection_id=collection_id, chunks=chunks)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando el PDF: {e}") from e

    return UploadResponse(
        collection_id=collection_id,
        pages_extracted=len(extracted_pages),
        chunks_indexed=len(chunks),
        filename=file.filename,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    session_id: str = Form(...),
    collection_id: str = Form(...),
    question: str = Form(...),
    model: Optional[str] = Form(DEFAULT_MODEL),
    top_k: Optional[int] = Form(5),
    image: Optional[UploadFile] = File(None),
):
    question = (question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")

    routed = resolve_model(question, ui_default=model or DEFAULT_MODEL)
    clean_question = routed.clean_question
    if not clean_question:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")

    image_bytes: Optional[bytes] = None
    image_mime: Optional[str] = None
    image_forced_gemini = False

    if image and image.filename:
        if routed.provider != "gemini":
            image_forced_gemini = True
            routed = resolve_model("[model:gemini] " + clean_question, ui_default="gemini")

        if gemini_service is None:
            raise HTTPException(status_code=500, detail=f"Gemini no configurado: {gemini_init_error}")

        image_mime = image.content_type or "application/octet-stream"
        if image_mime not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Imagen no válida. Usa JPG, PNG, WEBP o GIF.",
            )

        image_bytes = await image.read()
        max_image_bytes = 5 * 1024 * 1024
        if len(image_bytes) > max_image_bytes:
            raise HTTPException(status_code=400, detail="La imagen excede 5 MB.")

    if routed.provider == "gemini" and gemini_service is None:
        raise HTTPException(status_code=500, detail=f"Gemini no configurado: {gemini_init_error}")
    if routed.provider == "groq" and groq_service is None:
        raise HTTPException(status_code=500, detail=f"Groq no configurado: {groq_init_error}")

    session_id = session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id requerido.")

    history = session_history.setdefault(session_id, [])

    retrieved = []
    sources: List[int] = []

    if collection_id:
        try:
            retrieved = vector_service.search(
                collection_id=collection_id,
                query=clean_question,
                top_k=int(top_k or 5),
            )
            sources = sorted({pg for c in retrieved for pg in c.pages if isinstance(pg, int)})
        except FileNotFoundError:
            if not image_bytes:
                raise HTTPException(status_code=400, detail="PDF no cargado. Sube un PDF primero.") from None

    if not retrieved and not image_bytes:
        answer = format_answer(
            routed.label,
            "No encuentro información relevante en el PDF para responder a tu pregunta.",
            fallback_used=routed.fallback_used,
        )
        history.append({"role": "user", "content": clean_question})
        history.append({"role": "assistant", "content": answer})
        return ChatResponse(
            answer=answer,
            sources_pages=[],
            model=routed.model_id,
            model_label=routed.label,
        )

    try:
        if routed.provider == "gemini":
            raw_answer = gemini_service.answer(
                question=clean_question,
                context_chunks=retrieved,
                history=history,
                model_style=routed.style,
                temperature=routed.temperature,
                image_bytes=image_bytes,
                image_mime=image_mime,
            )
        else:
            raw_answer = groq_service.answer(
                question=clean_question,
                context_chunks=retrieved,
                history=history,
                groq_model=routed.groq_model,
                model_style=routed.style,
                temperature=routed.temperature,
            )

        if image_forced_gemini:
            raw_answer = (
                "Nota: las imágenes solo funcionan con Gemini; se usó Gemini 2.0 Flash.\n\n" + raw_answer
            )

        answer = format_answer(routed.label, raw_answer, fallback_used=routed.fallback_used)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    user_note = clean_question
    if image_bytes:
        user_note += " [imagen adjunta]"

    history.append({"role": "user", "content": user_note})
    history.append({"role": "assistant", "content": answer})

    if len(history) > 20:
        del history[:-20]

    return ChatResponse(
        answer=answer,
        sources_pages=sources,
        model=routed.model_id,
        model_label=routed.label,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Evita revelar detalles técnicos a usuario final.
    return JSONResponse(status_code=500, content={"detail": "Ocurrió un error inesperado."})

