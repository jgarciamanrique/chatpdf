# ChatPDF (FastAPI + RAG + FAISS + Groq)

Aplicación web tipo ChatGPT para subir PDFs, indexarlos con embeddings y conversar usando RAG (búsqueda semántica con FAISS).

## Requisitos

- Python 3.10+ recomendado
- Groq API Key

## Instalación

1. Crear entorno virtual:

```powershell
cd C:\phyton-practicas\chatpdf
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Instalar dependencias:

```powershell
pip install -r requirements.txt
```

3. Configurar variables de entorno:

Copias el ejemplo:

```powershell
copy .env.example .env
```

Y editas `GROQ_API_KEY=...`

## Ejecutar

```powershell
uvicorn app:app --reload --port 8000
```

Abre en el navegador:

`http://127.0.0.1:8000/`

## Flujo

1. Subes un PDF (hasta 50 MB).
2. El backend:
   - Extrae texto página por página con `pypdf`
   - Hace chunking inteligente basado en oraciones (objetivo ~800-1200 chars con overlap ~150-200 chars)
   - Calcula embeddings con `sentence-transformers (all-MiniLM-L6-v2)`
   - Indexa en FAISS y guarda metadata
3. Conversas: el sistema recupera top-K chunks relevantes, construye contexto y consulta Groq.

## Notas

- Los embeddings/índice se guardan en `vector_store/`.
- Los PDFs subidos se guardan en `uploads/`.

