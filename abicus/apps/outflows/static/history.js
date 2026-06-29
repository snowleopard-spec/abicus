(() => {
  const state = {
    table: null,
    categories: [],
    dirty: false,
    unfilledOnly: false,
  };

  // ---------- boot ----------
  async function boot() {
    let data;
    try {
      data = await api.get("/api/outflows/history");
    } catch (e) { return; }
    state.categories = data.categories || [];
    initTable(data.rows || []);
    wireButtons();
  }

  function initTable(rows) {
    state.table = new Tabulator("#history-table", {
      data: rows,
      layout: "fitColumns",
      height: 560,
      placeholder: "No history rows yet.",
      reactiveData: true,
      initialSort: [{ column: "date", dir: "desc" }],
      rowFormatter: (row) => {
        const d = row.getData();
        const cat = String(d.category || "").trim();
        row.getElement().classList.toggle("row-unfilled", !cat);
      },
      columns: [
        { title: "#", formatter: "rownum", width: 50, hozAlign: "center", headerSort: false },
        {
          title: "Date", field: "date",
          editor: "input", editorParams: { elementAttributes: { type: "date" } },
          headerFilter: "input",
          width: 130,
          sorter: "string",
        },
        {
          title: "Description", field: "description",
          editor: "textarea",
          headerFilter: "input",
          minWidth: 360,
          formatter: (cell) => {
            // Show first line only in the cell; full text appears on edit.
            const v = String(cell.getValue() || "");
            return v.replace(/\s*\n\s*/g, " · ");
          },
        },
        {
          title: "Amount", field: "amount", hozAlign: "right",
          editor: "number", editorParams: { step: 0.01 },
          headerFilter: "input",
          width: 120,
          sorter: "number",
          formatter: (cell) => {
            const v = cell.getValue();
            return v == null || v === "" ? "" :
              new Intl.NumberFormat("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);
          },
        },
        {
          title: "Category", field: "category",
          editor: "list",
          editorParams: {
            values: ["", ...state.categories],
            autocomplete: true,
            freetext: false,
            listOnEmpty: true,
            placeholderEmpty: "— blank (fall through) —",
          },
          headerFilter: "list",
          headerFilterParams: { values: ["", "(unfilled)", ...state.categories], clearable: true },
          headerFilterFunc: (header, value) => {
            if (!header) return true;
            if (header === "(unfilled)") return !String(value || "").trim();
            return String(value || "").trim() === header;
          },
          width: 200,
          formatter: (cell) => {
            const v = String(cell.getValue() || "").trim();
            if (!v) return `<span class="muted" style="font-style:italic;">unfilled</span>`;
            return v;
          },
        },
        {
          title: "", width: 80, headerSort: false, hozAlign: "center",
          cssClass: "cell-delete",
          formatter: () => `<button class="rowact danger inline" type="button" title="Delete row">Delete</button>`,
          cellClick: (e, cell) => { cell.getRow().delete(); markDirty(); },
        },
      ],
      cellEdited: (cell) => {
        // Re-run rowFormatter so the unfilled tint updates as user edits.
        cell.getRow().reformat();
        markDirty();
      },
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
    const unfilled = state.table.getData().filter(r => !String(r.category || "").trim()).length;
    document.getElementById("row-count").textContent =
      `${n} row${n === 1 ? "" : "s"} · ${unfilled} unfilled${state.dirty ? " · unsaved changes" : ""}`;
  }

  // ---------- buttons + filter ----------
  function wireButtons() {
    document.getElementById("add-row-btn").addEventListener("click", async () => {
      const today = new Date().toISOString().slice(0, 10);
      const row = await state.table.addRow({
        date: today, description: "", amount: 0, category: "",
      }, true /* top */);
      row.getCell("description").edit();
      markDirty();
    });

    document.getElementById("save-btn").addEventListener("click", save);

    document.getElementById("filter").addEventListener("input", (e) => {
      applyFilters(e.target.value);
    });
    document.getElementById("filter-unfilled").addEventListener("change", (e) => {
      state.unfilledOnly = e.target.checked;
      applyFilters(document.getElementById("filter").value);
    });

    window.addEventListener("beforeunload", (e) => {
      if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
    });
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        if (state.dirty) save();
      }
    });
  }

  function applyFilters(searchValue) {
    const q = (searchValue || "").trim();
    const filters = [];
    if (q) {
      filters.push([
        { field: "description", type: "like", value: q },
        { field: "category", type: "like", value: q },
        { field: "date", type: "like", value: q },
      ]);
    }
    if (state.unfilledOnly) {
      filters.push({
        field: "category",
        type: "=",
        value: "",
        // include rows where category is null/undefined too:
      });
      // For null-safe match, use a function filter instead
      filters.pop();
      filters.push({
        field: "category",
        type: "function",
        value: (cellValue) => !String(cellValue || "").trim(),
      });
    }
    if (!filters.length) { state.table.clearFilter(true); return; }
    state.table.setFilter(filters);
  }

  // ---------- save ----------
  async function save() {
    const rows = state.table.getData().map(r => ({
      date: String(r.date || "").trim(),
      description: String(r.description || "").trim(),
      amount: (r.amount === "" || r.amount == null) ? null : Number(r.amount),
      category: String(r.category || "").trim(),
    }));

    const statusEl = document.getElementById("save-status");
    const errEl = document.getElementById("save-error");
    statusEl.classList.add("hidden");
    errEl.classList.add("hidden");

    const btn = document.getElementById("save-btn");
    btn.disabled = true;
    btn.textContent = "Saving…";

    try {
      const res = await api.putJson("/api/outflows/history", { rows });
      state.dirty = false;
      updateRowCount();
      statusEl.textContent =
        `Saved ${res.n_rows} row${res.n_rows === 1 ? "" : "s"} to transaction_history.xlsx.`;
      statusEl.classList.remove("hidden");
      renderWarnings(res.warnings || []);
    } catch (e) {
      errEl.textContent = (e && e.message) || "Save failed.";
      errEl.classList.remove("hidden");
      btn.disabled = false;
    } finally {
      btn.textContent = "Save changes";
      btn.disabled = !state.dirty;
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

  boot().catch(err => console.error("History editor boot failed:", err));
})();
