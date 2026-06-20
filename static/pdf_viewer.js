(function () {
  const pdfjsLib = window.pdfjsLib;
  if (!pdfjsLib) {
    document.getElementById("status").textContent = "Error al cargar el visor PDF.";
    return;
  }

  pdfjsLib.GlobalWorkerOptions.workerSrc =
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

  const params = new URLSearchParams(window.location.search);
  const fileUrl = decodeURIComponent(params.get("file") || "");
  const initialPage = Math.max(1, parseInt(params.get("page") || "1", 10) || 1);

  const outer = document.getElementById("outer");
  const statusEl = document.getElementById("status");
  const pagesEl = document.getElementById("pages");
  const toolbar = document.getElementById("pdfToolbar");
  const pageInput = document.getElementById("pageInput");
  const pageTotalEl = document.getElementById("pageTotal");
  const btnZoomOut = document.getElementById("btnZoomOut");
  const btnZoomIn = document.getElementById("btnZoomIn");
  const btnFit = document.getElementById("btnFit");

  let pdfDoc = null;
  const rendered = new Set();
  let loadObserver = null;
  let pageTracker = null;
  let zoomFactor = 1;
  const defaultZoomFactor = 1;
  let currentPage = initialPage;
  let totalPages = 0;
  let pageInputFocused = false;

  const ZOOM_MIN = 0.55;
  const ZOOM_MAX = 2.4;
  const ZOOM_STEP = 1.15;

  function slotWidth() {
    return Math.max(200, outer.clientWidth - 24);
  }

  function pixelRatio() {
    return Math.min(window.devicePixelRatio || 1, 2.5);
  }

  function scaleForViewport(baseViewport) {
    return (slotWidth() / baseViewport.width) * zoomFactor;
  }

  function syncPageInput() {
    if (!pageInputFocused) {
      pageInput.value = String(currentPage);
    }
  }

  function updateToolbar() {
    pageInput.max = String(totalPages || 1);
    pageTotalEl.textContent = `de ${totalPages || 0}`;
    syncPageInput();
  }

  function showToolbar() {
    toolbar.classList.add("visible");
    updateToolbar();
  }

  async function renderPage(pageNum, force) {
    if (!pdfDoc) return;
    if (rendered.has(pageNum) && !force) return;
    if (force) rendered.delete(pageNum);

    const slot = document.getElementById(`page-${pageNum}`);
    if (!slot) return;

    rendered.add(pageNum);
    slot.classList.add("rendering");
    slot.textContent = `Página ${pageNum}...`;

    try {
      const page = await pdfDoc.getPage(pageNum);
      const base = page.getViewport({ scale: 1 });
      const scale = scaleForViewport(base);
      const viewport = page.getViewport({ scale });
      const ratio = pixelRatio();

      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d", { alpha: false });

      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;

      const renderViewport = ratio === 1 ? viewport : page.getViewport({ scale: scale * ratio });

      await page.render({
        canvasContext: ctx,
        viewport: renderViewport,
      }).promise;

      slot.classList.remove("rendering");
      slot.textContent = "";
      slot.appendChild(canvas);
    } catch (err) {
      rendered.delete(pageNum);
      slot.classList.remove("rendering");
      slot.textContent = `Error en página ${pageNum}`;
      console.error(err);
    }
  }

  function setupLoadObserver() {
    if (loadObserver) loadObserver.disconnect();

    loadObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const pageNum = parseInt(entry.target.dataset.page, 10);
          if (pageNum) renderPage(pageNum);
        });
      },
      { root: outer, rootMargin: "240px 0px" }
    );

    document.querySelectorAll(".page-slot").forEach((slot) => loadObserver.observe(slot));
  }

  function setupPageTracker() {
    if (pageTracker) pageTracker.disconnect();

    pageTracker = new IntersectionObserver(
      (entries) => {
        let bestPage = currentPage;
        let bestRatio = 0;

        entries.forEach((entry) => {
          if (entry.intersectionRatio > bestRatio) {
            bestRatio = entry.intersectionRatio;
            bestPage = parseInt(entry.target.dataset.page, 10) || bestPage;
          }
        });

        if (bestRatio > 0.15 && bestPage !== currentPage) {
          currentPage = bestPage;
          syncPageInput();
        }
      },
      { root: outer, threshold: [0.15, 0.35, 0.55, 0.75] }
    );

    document.querySelectorAll(".page-slot").forEach((slot) => pageTracker.observe(slot));
  }

  function scrollToPage(pageNum, smooth) {
    const slot = document.getElementById(`page-${pageNum}`);
    if (!slot) return;
    currentPage = pageNum;
    syncPageInput();
    slot.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
  }

  async function navigateToPage(rawValue) {
    let page = parseInt(String(rawValue).trim(), 10);
    if (Number.isNaN(page)) {
      syncPageInput();
      return;
    }

    page = Math.min(totalPages, Math.max(1, page));
    currentPage = page;
    pageInput.value = String(page);

    const slot = document.getElementById(`page-${page}`);
    if (slot) {
      slot.scrollIntoView({ behavior: "auto", block: "start" });
    }

    await renderPage(page, true);
  }

  function getVisiblePages() {
    const visible = [];
    const outerRect = outer.getBoundingClientRect();

    document.querySelectorAll(".page-slot").forEach((slot) => {
      const rect = slot.getBoundingClientRect();
      if (rect.bottom >= outerRect.top - 240 && rect.top <= outerRect.bottom + 240) {
        visible.push(parseInt(slot.dataset.page, 10));
      }
    });

    if (!visible.length && currentPage) visible.push(currentPage);
    return visible;
  }

  function clearRendered(pages) {
    const targets = pages || Array.from({ length: totalPages }, (_, i) => i + 1);
    targets.forEach((pageNum) => {
      rendered.delete(pageNum);
      const slot = document.getElementById(`page-${pageNum}`);
      if (slot) {
        slot.innerHTML = "";
        slot.classList.remove("rendering");
      }
    });
  }

  async function rerenderPages(pageNums) {
    const targets = pageNums && pageNums.length ? pageNums : getVisiblePages();
    clearRendered(targets);
    for (const pageNum of targets) {
      await renderPage(pageNum, true);
    }
  }

  async function applyZoom(nextFactor) {
    zoomFactor = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, nextFactor));
    await rerenderPages(getVisiblePages());
  }

  async function resetZoom() {
    zoomFactor = defaultZoomFactor;
    clearRendered();
    await rerenderPages(getVisiblePages());
  }

  let resizeTimer = null;
  function onPanelResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => rerenderPages(getVisiblePages()), 180);
  }

  btnZoomOut.addEventListener("click", (e) => {
    e.preventDefault();
    applyZoom(zoomFactor / ZOOM_STEP);
  });

  btnZoomIn.addEventListener("click", (e) => {
    e.preventDefault();
    applyZoom(zoomFactor * ZOOM_STEP);
  });

  btnFit.addEventListener("click", (e) => {
    e.preventDefault();
    resetZoom();
  });

  pageInput.addEventListener("focus", () => {
    pageInputFocused = true;
    pageInput.select();
  });

  pageInput.addEventListener("blur", () => {
    pageInputFocused = false;
    navigateToPage(pageInput.value);
  });

  pageInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      pageInput.blur();
    }
  });

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data || {};

    if (data.type === "panelResize") {
      onPanelResize();
    }

    if (data.type === "goToPage" && data.page) {
      const page = Math.min(totalPages, Math.max(1, parseInt(data.page, 10)));
      navigateToPage(page);
    }
  });

  async function init() {
    if (!fileUrl) {
      statusEl.textContent = "No se indicó archivo PDF.";
      return;
    }

    try {
      pdfDoc = await pdfjsLib.getDocument(fileUrl).promise;
      totalPages = pdfDoc.numPages;
      statusEl.textContent = "";

      for (let i = 1; i <= totalPages; i++) {
        const slot = document.createElement("div");
        slot.className = "page-slot";
        slot.id = `page-${i}`;
        slot.dataset.page = String(i);
        pagesEl.appendChild(slot);
      }

      setupLoadObserver();
      setupPageTracker();
      showToolbar();

      await renderPage(initialPage, true);
      scrollToPage(initialPage, false);
    } catch (err) {
      statusEl.textContent = "No se pudo cargar el PDF.";
      console.error(err);
    }
  }

  init();
})();
