function el(id) {
  return document.getElementById(id);
}

async function readJsonResponse(res) {
  const text = await res.text();
  if (!text.trim()) {
    if (res.status === 502 || res.status === 503 || res.status === 504) {
      throw new Error(
        "El servidor no respondió a tiempo. En Render Free puede tardar ~1 min en despertar; espera y reintenta."
      );
    }
    throw new Error(`Respuesta vacía del servidor (HTTP ${res.status}).`);
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("Respuesta inválida del servidor. Recarga la página e inténtalo de nuevo.");
  }
}

const MODEL_TAG_REGEX = /\[model:(\w+)\]/gi;

const state = {
  sessionId: null,
  collectionId: null,
  filename: null,
  defaultModel: "gemini",
  attachedImage: null,
  speechRecognition: null,
  isListening: false,
};

function getOrCreateSessionId() {
  const key = "chatpdf_session_id";
  let existing = localStorage.getItem(key);
  if (existing) return existing;

  const id = crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2);
  localStorage.setItem(key, id);
  return id;
}

function getStoredCollectionId() {
  return localStorage.getItem("chatpdf_collection_id");
}

function setStoredCollectionId(id) {
  if (!id) {
    localStorage.removeItem("chatpdf_collection_id");
    localStorage.removeItem("chatpdf_filename");
    return;
  }
  localStorage.setItem("chatpdf_collection_id", id);
}

function getStoredFilename() {
  return localStorage.getItem("chatpdf_filename");
}

function setStoredFilename(name) {
  if (!name) {
    localStorage.removeItem("chatpdf_filename");
    return;
  }
  localStorage.setItem("chatpdf_filename", name);
}

function getStoredModel() {
  return localStorage.getItem("chatpdf_default_model") || "gemini";
}

function setStoredModel(model) {
  localStorage.setItem("chatpdf_default_model", model);
}

function parseModelTag(text) {
  MODEL_TAG_REGEX.lastIndex = 0;
  const match = MODEL_TAG_REGEX.exec(text);
  if (!match) {
    return { model: null, cleanText: text.trim() };
  }

  const model = match[1].toLowerCase();
  const cleanText = text.replace(MODEL_TAG_REGEX, "").replace(/\s+/g, " ").trim();
  return { model, cleanText };
}

function getSelectedModel() {
  return el("modelSelect").value || state.defaultModel;
}

function pdfUrl(collectionId, page) {
  const file = encodeURIComponent(`/pdf/${collectionId}`);
  let url = `/static/pdf_viewer.html?v=5&file=${file}`;
  if (page) url += `&page=${page}`;
  return url;
}

function notifyPdfViewerResize() {
  const iframe = el("pdfViewer");
  if (!iframe || iframe.classList.contains("hidden") || !iframe.contentWindow) return;
  iframe.contentWindow.postMessage({ type: "panelResize" }, window.location.origin);
}

let pdfResizeTimer = null;
function schedulePdfViewerResize() {
  clearTimeout(pdfResizeTimer);
  pdfResizeTimer = setTimeout(notifyPdfViewerResize, 120);
}

function showPdfViewer(collectionId, filename, page) {
  const iframe = el("pdfViewer");
  const placeholder = el("pdfPlaceholder");
  const nameEl = el("pdfFilename");

  iframe.src = pdfUrl(collectionId, page);
  iframe.classList.remove("hidden");
  placeholder.classList.add("hidden");
  nameEl.textContent = filename || "Documento PDF";
}

function appendMessage({ role, text, sourcesPages, modelLabel, imageUrl }) {
  const messages = el("messages");
  const msg = document.createElement("div");
  msg.className = "message " + (role === "user" ? "user" : "ai");

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (role !== "user" && modelLabel) {
    const badge = document.createElement("div");
    badge.className = "model-badge";
    badge.textContent = modelLabel;
    bubble.appendChild(badge);
  }

  const body = document.createElement("div");
  body.textContent = text || "";
  bubble.appendChild(body);

  if (imageUrl) {
    const img = document.createElement("img");
    img.src = imageUrl;
    img.alt = "Imagen adjunta";
    img.className = "message-image";
    bubble.appendChild(img);
  }

  msg.appendChild(bubble);

  if (role !== "user" && sourcesPages && sourcesPages.length) {
    const sources = document.createElement("div");
    sources.className = "sources";
    sources.appendChild(document.createTextNode("Fuentes: "));

    sourcesPages.forEach((page, index) => {
      if (index > 0) sources.appendChild(document.createTextNode(", "));

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "source-link";
      btn.textContent = `Página ${page}`;
      btn.addEventListener("click", () => goToPage(page));
      sources.appendChild(btn);
    });

    bubble.appendChild(sources);
  }

  messages.appendChild(msg);
  messages.scrollTop = messages.scrollHeight;
}

function showError(text) {
  el("chatError").textContent = text || "";
}

function setTyping(on) {
  el("typing").style.display = on ? "block" : "none";
}

function clearChat() {
  el("messages").innerHTML = "";
  showError("");
  clearAttachedImage();
}

function goToPage(page) {
  if (!state.collectionId || !page) return;
  const iframe = el("pdfViewer");
  if (iframe && !iframe.classList.contains("hidden") && iframe.contentWindow) {
    iframe.contentWindow.postMessage({ type: "goToPage", page }, window.location.origin);
    return;
  }
  showPdfViewer(state.collectionId, state.filename, page);
}

function clearAttachedImage() {
  state.attachedImage = null;
  el("imageInput").value = "";
  el("imagePreview").classList.add("hidden");
  el("imagePreviewImg").src = "";
  updateSendButton();
}

function setAttachedImage(file) {
  if (!file) {
    clearAttachedImage();
    return;
  }

  const allowed = ["image/jpeg", "image/png", "image/webp", "image/gif"];
  if (!allowed.includes(file.type)) {
    showError("Formato no válido. Usa JPG, PNG, WEBP o GIF.");
    return;
  }

  if (file.size > 5 * 1024 * 1024) {
    showError("La imagen no puede superar 5 MB.");
    return;
  }

  state.attachedImage = file;
  const previewUrl = URL.createObjectURL(file);
  el("imagePreviewImg").src = previewUrl;
  el("imagePreview").classList.remove("hidden");
  showError("");
  updateSendButton();
}

function updateSendButton() {
  const input = el("questionInput");
  const hasText = input.value.length > 0;
  const hasImage = !!state.attachedImage;
  const show = hasText || hasImage;

  el("btnSend").classList.toggle("visible", show);
  input.classList.toggle("has-send-btn", show);
}

function setupVoiceInput() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    el("btnMic").disabled = true;
    el("btnMic").title = "Voz no soportada en este navegador (usa Chrome o Edge)";
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = "es-ES";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    state.isListening = true;
    el("btnMic").classList.add("listening");
    el("btnMic").title = "Escuchando... pulsa para detener";
  };

  recognition.onend = () => {
    state.isListening = false;
    el("btnMic").classList.remove("listening");
    el("btnMic").title = "Consulta por voz";
  };

  recognition.onerror = (event) => {
    showError("Error de voz: " + (event.error || "desconocido"));
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    const input = el("questionInput");
    input.value = (input.value ? input.value + " " : "") + transcript.trim();
    input.focus();
    updateSendButton();
  };

  state.speechRecognition = recognition;

  el("btnMic").addEventListener("click", () => {
    if (state.isListening) {
      state.speechRecognition.stop();
      return;
    }
    showError("");
    try {
      state.speechRecognition.start();
    } catch {
      showError("No se pudo iniciar el micrófono.");
    }
  });
}

async function verifyPdfExists(collectionId) {
  const res = await fetch(`/pdf/${collectionId}`, { method: "HEAD" });
  return res.ok;
}

async function restoreSession() {
  const collectionId = getStoredCollectionId();
  const filename = getStoredFilename();

  if (!collectionId) return;

  const exists = await verifyPdfExists(collectionId);
  if (!exists) {
    setStoredCollectionId(null);
    setStoredFilename(null);
    return;
  }

  state.collectionId = collectionId;
  state.filename = filename;
  showPdfViewer(collectionId, filename);
  el("chatHint").textContent = "PDF listo. Puedes escribir, hablar o adjuntar imagen.";
}

async function uploadPDF() {
  const fileInput = el("pdfFile");
  const file = fileInput.files && fileInput.files[0];

  if (!file) {
    showError("Selecciona un archivo PDF.");
    return;
  }

  showError("");
  const status = el("uploadStatus");
  const btnUpload = el("btnUpload");
  const btnSend = el("btnSend");

  btnUpload.disabled = true;
  btnSend.disabled = true;
  status.textContent = "Indexando PDF...";

  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("session_id", state.sessionId);

    const res = await fetch(window.__APP__.uploadEndpoint, {
      method: "POST",
      body: formData,
    });

    const data = await readJsonResponse(res);
    if (!res.ok) throw new Error(data.detail || "Error al subir PDF.");

    state.collectionId = data.collection_id;
    state.filename = data.filename;
    setStoredCollectionId(state.collectionId);
    setStoredFilename(state.filename);

    showPdfViewer(state.collectionId, state.filename);
    status.textContent = `Listo · ${data.pages_extracted} págs · ${data.chunks_indexed} chunks`;
    el("chatHint").textContent = "PDF listo. Puedes escribir, hablar o adjuntar imagen.";
    clearChat();
  } catch (err) {
    status.textContent = "";
    showError(String(err.message || err));
  } finally {
    btnUpload.disabled = false;
    btnSend.disabled = false;
  }
}

async function ask(rawQuestion) {
  const hasImage = !!state.attachedImage;

  if (!state.collectionId && !hasImage) {
    showError("Primero sube un PDF o adjunta una imagen.");
    return;
  }

  const { cleanText } = parseModelTag(rawQuestion);
  const displayText = cleanText || rawQuestion.trim();

  if (!displayText && !hasImage) {
    showError("Escribe una pregunta o adjunta una imagen.");
    return;
  }

  const questionText = displayText || "Describe la imagen adjunta en relación al documento.";
  const imagePreviewUrl = hasImage ? URL.createObjectURL(state.attachedImage) : null;

  showError("");
  el("questionInput").value = "";
  updateSendButton();

  appendMessage({
    role: "user",
    text: questionText,
    imageUrl: imagePreviewUrl,
  });

  setTyping(true);

  const formData = new FormData();
  formData.append("session_id", state.sessionId);
  formData.append("collection_id", state.collectionId || "");
  formData.append("question", rawQuestion.trim() || questionText);
  formData.append("model", getSelectedModel());
  formData.append("top_k", "5");

  if (state.attachedImage) {
    formData.append("image", state.attachedImage);
  }

  const attachedCopy = state.attachedImage;
  clearAttachedImage();

  try {
    const res = await fetch(window.__APP__.chatEndpoint, {
      method: "POST",
      body: formData,
    });

    const data = await readJsonResponse(res);
    if (!res.ok) throw new Error(data.detail || "Error al consultar.");

    appendMessage({
      role: "ai",
      text: data.answer,
      sourcesPages: data.sources_pages,
      modelLabel: data.model_label || data.model,
    });
  } catch (err) {
    appendMessage({
      role: "ai",
      text: "Ocurrió un error: " + String(err.message || err),
      sourcesPages: [],
    });
    if (attachedCopy) setAttachedImage(attachedCopy);
  } finally {
    setTyping(false);
  }
}

function setupSplitResize() {
  const shell = document.querySelector(".split-shell");
  const layout = document.querySelector(".split-layout");
  const resizer = el("splitResizer");
  const pdfPanel = document.querySelector(".panel-pdf");

  if (!shell || !layout || !resizer || !pdfPanel) return;

  const STORAGE_KEY = "chatpdf_split_ratio";
  const GAP = 12;
  const MIN_PDF = 280;
  const MIN_CHAT = 320;
  const MOBILE_MQ = window.matchMedia("(max-width: 900px)");

  function isEnabled() {
    return !MOBILE_MQ.matches;
  }

  function getAvailableWidth() {
    return shell.clientWidth - GAP;
  }

  function clampLeft(px) {
    const available = getAvailableWidth();
    const minLeft = MIN_PDF;
    const maxLeft = Math.max(minLeft, available - MIN_CHAT);
    return Math.min(maxLeft, Math.max(minLeft, px));
  }

  function positionResizer() {
    const shellRect = shell.getBoundingClientRect();
    const pdfRect = pdfPanel.getBoundingClientRect();
    resizer.style.left = `${pdfRect.right - shellRect.left + GAP / 2}px`;
  }

  function widthFromClientX(clientX) {
    const layoutRect = layout.getBoundingClientRect();
    return clientX - layoutRect.left;
  }

  function setLeftWidth(px) {
    if (!isEnabled()) return MIN_PDF;
    const width = clampLeft(px);
    layout.style.setProperty("--pdf-col-width", `${width}px`);
    layout.classList.add("has-custom-split");
    positionResizer();
    schedulePdfViewerResize();
    return width;
  }

  function clearResizeStyles() {
    layout.style.removeProperty("--pdf-col-width");
    layout.classList.remove("has-custom-split");
    resizer.style.left = "";
  }

  function saveWidth(width) {
    const available = getAvailableWidth();
    if (available <= 0) return;
    localStorage.setItem(STORAGE_KEY, String(width / available));
  }

  function restoreWidth() {
    if (!isEnabled()) {
      clearResizeStyles();
      return;
    }
    const saved = parseFloat(localStorage.getItem(STORAGE_KEY) || "");
    const ratio = Number.isNaN(saved) ? 0.5 : saved;
    setLeftWidth(ratio * getAvailableWidth());
    positionResizer();
  }

  function startDrag(clientX) {
    document.body.classList.add("split-dragging");
    layout.classList.add("is-resizing");
    setLeftWidth(widthFromClientX(clientX));

    function onMove(ev) {
      ev.preventDefault();
      const x = ev.touches ? ev.touches[0].clientX : ev.clientX;
      setLeftWidth(widthFromClientX(x));
    }

    function onUp(ev) {
      document.body.classList.remove("split-dragging");
      layout.classList.remove("is-resizing");
      const x = ev.changedTouches ? ev.changedTouches[0].clientX : ev.clientX;
      saveWidth(setLeftWidth(widthFromClientX(x)));
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onUp);
      document.removeEventListener("touchcancel", onUp);
    }

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.addEventListener("touchmove", onMove, { passive: false });
    document.addEventListener("touchend", onUp);
    document.addEventListener("touchcancel", onUp);
  }

  restoreWidth();
  window.addEventListener("load", restoreWidth);
  window.addEventListener("resize", restoreWidth);

  MOBILE_MQ.addEventListener("change", restoreWidth);

  resizer.addEventListener("mousedown", (e) => {
    if (!isEnabled()) return;
    e.preventDefault();
    e.stopPropagation();
    startDrag(e.clientX);
  });

  resizer.addEventListener(
    "touchstart",
    (e) => {
      if (!isEnabled() || !e.touches[0]) return;
      e.preventDefault();
      startDrag(e.touches[0].clientX);
    },
    { passive: false }
  );

  resizer.addEventListener("dblclick", (e) => {
    if (!isEnabled()) return;
    e.preventDefault();
    saveWidth(setLeftWidth(getAvailableWidth() * 0.5));
  });

  resizer.addEventListener("keydown", (e) => {
    if (!isEnabled()) return;
    const current = pdfPanel.getBoundingClientRect().width;
    const step = e.shiftKey ? 48 : 24;

    if (e.key === "ArrowLeft") {
      e.preventDefault();
      saveWidth(setLeftWidth(current - step));
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      saveWidth(setLeftWidth(current + step));
    }
  });
}

function bindUI() {
  state.sessionId = getOrCreateSessionId();
  state.defaultModel = getStoredModel();

  const modelSelect = el("modelSelect");
  modelSelect.value = state.defaultModel;
  modelSelect.addEventListener("change", () => {
    state.defaultModel = modelSelect.value;
    setStoredModel(modelSelect.value);
  });

  setupVoiceInput();
  setupSplitResize();
  restoreSession();
  updateSendButton();

  el("btnUpload").addEventListener("click", uploadPDF);
  el("btnSend").addEventListener("click", () => {
    const q = el("questionInput").value.trim();
    if (q || state.attachedImage) ask(q);
  });

  el("questionInput").addEventListener("input", updateSendButton);

  el("questionInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      el("btnSend").click();
    }
  });

  el("btnAttachImage").addEventListener("click", () => el("imageInput").click());

  el("imageInput").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) setAttachedImage(file);
  });

  el("btnRemoveImage").addEventListener("click", clearAttachedImage);

  el("btnNewChat").addEventListener("click", () => {
    const key = "chatpdf_session_id";
    const newId = crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2);
    localStorage.setItem(key, newId);
    state.sessionId = newId;
    clearChat();
    el("chatHint").textContent = state.collectionId
      ? "Historial limpiado. PDF listo."
      : "Sube un PDF para habilitar la conversación.";
  });
}

bindUI();
