console.log("KIOSK JS cargado");

document.addEventListener("DOMContentLoaded", () => {
  const els = {
    fecha: document.getElementById("fecha"),
    sucursal: document.getElementById("sucursal"),
    q: document.getElementById("q"),
    results: document.getElementById("results"),
    seleccion: document.getElementById("seleccion"),
    obs: document.getElementById("obs"),
    btnMarcar: document.getElementById("btnMarcar"),
    btnLimpiar: document.getElementById("btnLimpiar"),
    warning: document.getElementById("resultsWarning"),
    feedback: document.getElementById("feedback"),
    toastHost: document.getElementById("toastHost"),
    stateButtons: Array.from(document.querySelectorAll("[data-estado]")),
  };

  const state = {
    alumno: null,
    estado: "P",
    abortController: null,
  };

  function escapeHtml(text) {
    return String(text)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function setFeedback(message, kind = "info") {
    if (!els.feedback) return;
    if (!message) {
      els.feedback.className = "d-none";
      els.feedback.textContent = "";
      return;
    }
    els.feedback.className = `alert alert-${kind} mt-3 mb-0`;
    els.feedback.textContent = message;
  }

  function setWarning(message) {
    if (!els.warning) return;
    if (!message) {
      els.warning.className = "d-none";
      els.warning.textContent = "";
      return;
    }
    els.warning.className = "alert alert-warning mb-3";
    els.warning.textContent = message;
  }

  function setEstado(estado) {
    state.estado = estado;
    els.stateButtons.forEach((btn) => {
      const active = btn.dataset.estado === estado;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function clearSelection({ keepQuery = false } = {}) {
    state.alumno = null;
    els.seleccion.textContent = "—";
    els.btnMarcar.disabled = true;
    els.obs.value = "";
    setEstado("P");
    if (!keepQuery) {
      els.q.value = "";
      els.results.innerHTML = `<div class="text-muted p-3">Escribe para buscar...</div>`;
      setWarning(null);
    }
  }

  function selectAlumno(alumno) {
    state.alumno = alumno;
    els.seleccion.textContent = `${alumno.nombre}${alumno.identidad ? ` · ${alumno.identidad}` : ""}`;
    els.btnMarcar.disabled = false;

    document.querySelectorAll(".kiosk-result-item").forEach((item) => {
      item.classList.toggle("active", Number(item.dataset.alumnoId) === Number(alumno.id));
    });
  }

  function renderResults(data) {
    if (!Array.isArray(data) || data.length === 0) {
      els.results.innerHTML = `
        <div class="results-placeholder">
          No se encontraron alumnos.
        </div>
      `;
      return;
    }

    els.results.innerHTML = data.map((alumno) => `
      <button
        type="button"
        class="result-item kiosk-result-item"
        data-alumno-id="${alumno.id}"
      >
        <div class="result-main">
          <div>
            <div class="result-name">${escapeHtml(alumno.nombre)}</div>
            <div class="result-meta">
              ${alumno.identidad ? escapeHtml(alumno.identidad) : "Sin identificación"}
            </div>
          </div>
          <span class="pill">Sucursal ${alumno.sucursal_id ?? "—"}</span>
        </div>
      </button>
    `).join("");

    document.querySelectorAll(".kiosk-result-item").forEach((item) => {
      item.addEventListener("click", () => {
        const alumno = data.find((row) => Number(row.id) === Number(item.dataset.alumnoId));
        if (alumno) {
          selectAlumno(alumno);
        }
      });
    });
  }

  async function buscar() {
    const q = (els.q.value || "").trim();
    const sucursalId = els.sucursal.value;

    clearSelection({ keepQuery: true });
    setFeedback(null);

    if (q.length < 2) {
      els.results.innerHTML = `<div class="results-placeholder">Escribe al menos 2 caracteres.</div>`;
      setWarning(null);
      return;
    }

    if (state.abortController) {
      state.abortController.abort();
    }

    state.abortController = new AbortController();
    console.log("Buscando:", q, sucursalId);
    els.results.innerHTML = `<div class="results-placeholder">Buscando alumnos...</div>`;
    setWarning(null);

    try {
      const url = new URL("/kiosk/buscar", window.location.origin);
      url.searchParams.set("q", q);
      if (sucursalId) {
        url.searchParams.set("sucursal_id", sucursalId);
      }

      const res = await fetch(url, {
        headers: { "X-Requested-With": "fetch" },
        signal: state.abortController.signal,
      });
      const payload = await res.json();
      console.log("Respuesta búsqueda:", payload);

      if (!res.ok || !payload.ok) {
        throw new Error(payload.error || "No se pudo buscar alumnos.");
      }

      setWarning(payload.warning || null);
      renderResults(payload.data || []);
    } catch (error) {
      if (error.name === "AbortError") {
        return;
      }
      els.results.innerHTML = `
        <div class="results-placeholder">
          ${escapeHtml(error.message || "Error de búsqueda")}
        </div>
      `;
      setWarning(null);
    }
  }

  function showToast(message, kind = "success") {
    if (!els.toastHost) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${kind}`;
    toast.textContent = message;
    els.toastHost.appendChild(toast);
    window.setTimeout(() => {
      toast.remove();
    }, 3200);
  }

  async function marcarAsistencia() {
    if (!state.alumno) {
      setFeedback("Selecciona un alumno antes de guardar.", "warning");
      return;
    }

    const payload = {
      alumno_id: state.alumno.id,
      fecha: els.fecha.value,
      sucursal_id: Number(els.sucursal.value),
      estado: state.estado,
      observacion: (els.obs.value || "").trim(),
    };

    els.btnMarcar.disabled = true;
    setFeedback("Guardando asistencia...", "info");

    try {
      const res = await fetch("/kiosk/marcar", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "fetch",
        },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || "No se pudo guardar la asistencia.");
      }

      setFeedback(null);
      showToast(`${data.message}: ${state.alumno.nombre} (${state.estado})`, "success");

      if (data.aviso) {
        showToast(data.aviso, "warning");
      }

      clearSelection({ keepQuery: false });
      els.q.focus();
    } catch (error) {
      setFeedback(error.message || "Error al guardar asistencia.", "danger");
      els.btnMarcar.disabled = false;
    }
  }

  let debounceTimer = null;
  function debounceBuscar() {
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(buscar, 250);
  }

  els.q.addEventListener("input", debounceBuscar);
  els.sucursal.addEventListener("change", () => {
    clearSelection({ keepQuery: true });
    debounceBuscar();
  });
  els.fecha.addEventListener("change", () => {
    setFeedback(null);
  });
  els.stateButtons.forEach((btn) => {
    btn.addEventListener("click", () => setEstado(btn.dataset.estado));
  });
  els.btnMarcar.addEventListener("click", marcarAsistencia);
  els.btnLimpiar.addEventListener("click", () => {
    setFeedback(null);
    clearSelection();
    els.q.focus();
  });

  setEstado("P");
});
