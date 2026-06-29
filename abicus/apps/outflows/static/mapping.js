(() => {
  const state = {
    table: null,
    categories: [],
    dirty: false,
  };

  // ---------- boot ----------
  async function boot() {
    let data;
    try {
      data = await api.get("/api/outflows/mapping");
    } catch (e) { return; }
    state.categories = data.categories || [];
    initTable(data.rules || []);
    wireButtons();
  }

  function initTable(rows) {
    state.table = new Tabulator("#mapping-table", {
      data: rows,
      layout: "fitColumns",
      height: 560,
      placeholder: "No mapping rules yet — use “+ Add rule”.",
      reactiveData: true,
      pagination: false,
      columns: [
        { title: "#", formatter: "rownum", width: 50, hozAlign: "center", headerSort: false, cssClass: "muted" },
        {
          title: "Partial string", field: "partial_string",
          editor: "input",
          headerFilter: "input",
          minWidth: 240,
          validator: ["required", { type: "minLength", parameters: 1 }],
        },
        {
          title: "Category", field: "category",
          editor: "list",
          editorParams: {
            values: state.categories,
            autocomplete: true,
            freetext: false,
            listOnEmpty: true,
            placeholderEmpty: "Pick a category…",
          },
          headerFilter: "list",
          headerFilterParams: { values: ["", ...state.categories], clearable: true },
          width: 240,
        },
        {
          title: "", width: 80, headerSort: false, hozAlign: "center",
          cssClass: "cell-delete",
          formatter: () => `<button class="rowact danger inline" type="button" title="Delete row">Delete</button>`,
          cellClick: (e, cell) => { cell.getRow().delete(); markDirty(); },
        },
      ],
      cellEdited: markDirty,
      dataChanged: updateRowCount,
    });
  }

  function markDirty() {
    state.dirty = true;
    document.getElementById("save-btn").disabled = false;
    updateRowCount();
  }

  function updateRowCount() {
    if (!state.table) return;
    const n = state.table.getDataCount("active");
    document.getElementById("row-count").textContent =
      `${n} rule${n === 1 ? "" : "s"}${state.dirty ? " · unsaved changes" : ""}`;
  }

  // ---------- buttons + filter ----------
  function wireButtons() {
    document.getElementById("add-row-btn").addEventListener("click", async () => {
      const row = await state.table.addRow({
        partial_string: "",
        category: state.categories[0] || "",
      }, false);
      row.getCell("partial_string").edit();
      markDirty();
    });

    document.getElementById("save-btn").addEventListener("click", save);

    document.getElementById("filter").addEventListener("input", (e) => {
      const q = e.target.value.trim();
      if (!q) { state.table.clearFilter(true); return; }
      // OR-match on partial_string OR category (case-insensitive "like")
      state.table.setFilter([
        [
          { field: "partial_string", type: "like", value: q },
          { field: "category", type: "like", value: q },
        ],
      ]);
    });

    // Warn on unload if there are unsaved edits
    window.addEventListener("beforeunload", (e) => {
      if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
    });

    // ⌘S / Ctrl-S triggers save
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        if (state.dirty) save();
      }
    });
  }

  // ---------- save ----------
  async function save() {
    const rows = state.table.getData()
      .map(r => ({
        partial_string: String(r.partial_string || "").trim(),
        category: String(r.category || "").trim(),
      }))
      .filter(r => r.partial_string || r.category);  // backend drops fully-blank rows too

    const statusEl = document.getElementById("save-status");
    const errEl = document.getElementById("save-error");
    statusEl.classList.add("hidden");
    errEl.classList.add("hidden");

    const btn = document.getElementById("save-btn");
    btn.disabled = true;
    btn.textContent = "Saving…";

    try {
      const res = await api.putJson("/api/outflows/mapping", { rules: rows });
      state.dirty = false;
      updateRowCount();
      statusEl.textContent =
        `Saved ${res.n_rules} rule${res.n_rules === 1 ? "" : "s"} to mapping.xlsx + mapping.json.`;
      statusEl.classList.remove("hidden");
      renderWarnings(res.warnings || []);
    } catch (e) {
      errEl.textContent = (e && e.message) || "Save failed.";
      errEl.classList.remove("hidden");
      // re-enable so they can fix and retry
      btn.disabled = false;
    } finally {
      btn.textContent = "Save changes";
      if (!state.dirty) btn.disabled = true;
      else btn.disabled = false;
    }
  }

  function renderWarnings(warnings) {
    const panel = document.getElementById("warnings-panel");
    const summary = document.getElementById("warnings-summary");
    const list = document.getElementById("warnings-list");
    if (!warnings.length) { panel.classList.add("hidden"); return; }
    panel.classList.remove("hidden");
    panel.open = true;
    summary.textContent = `⚠️ ${warnings.length} non-fatal warning${warnings.length === 1 ? "" : "s"}`;
    list.innerHTML = warnings.map(escapeHtml).map(w => `<li>${w}</li>`).join("");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  boot().catch(err => console.error("Mapping editor boot failed:", err));
})();
