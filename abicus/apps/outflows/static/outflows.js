(() => {
  const state = {
    config: { accounts: [], categories: [], excluded: [] },
    files: [],      // [{file: File, account: string}]
    session: null,  // {session_id, rows, mapping_warnings, history_warnings, ...}
    range: { from: null, to: null },
    lastAccount: null,
    tabulator: null,
  };

  const fmtSgd = (n) => new Intl.NumberFormat("en-SG", {
    style: "currency", currency: "SGD", maximumFractionDigits: 0,
  }).format(n || 0);
  const fmtPct = (n) => `${(n * 100).toFixed(1)}%`;

  // ---------- boot ----------

  async function boot() {
    try {
      state.config = await api.get("/api/outflows/config");
    } catch (e) { return; }
    wireDropzone();
    wireCompile();
    wireRange();
    wireDownloads();
  }

  // ---------- file list / dropzone ----------

  function wireDropzone() {
    const dz = document.getElementById("dropzone");
    const input = document.getElementById("file-input");
    document.getElementById("browse-btn").addEventListener("click", () => input.click());
    dz.addEventListener("click", (e) => {
      if (e.target.id === "browse-btn") return;
      input.click();
    });
    input.addEventListener("change", () => {
      addFiles(input.files);
      input.value = "";
    });
    ["dragenter","dragover"].forEach(ev => dz.addEventListener(ev, (e) => {
      e.preventDefault(); dz.classList.add("is-drag");
    }));
    ["dragleave","drop"].forEach(ev => dz.addEventListener(ev, (e) => {
      e.preventDefault(); dz.classList.remove("is-drag");
    }));
    dz.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
  }

  function addFiles(fileList) {
    for (const f of fileList) {
      state.files.push({
        file: f,
        account: state.lastAccount || (state.config.accounts[0] && state.config.accounts[0].name) || "",
      });
    }
    renderFileList();
  }

  function renderFileList() {
    const ul = document.getElementById("file-list");
    ul.innerHTML = state.files.map((entry, i) => `
      <li>
        <span class="filename" title="${entry.file.name}">${entry.file.name}</span>
        <select class="select file-account" data-i="${i}">
          ${state.config.accounts.map(a => `<option value="${a.name}" ${a.name === entry.account ? "selected" : ""}>${a.name} (${a.format})</option>`).join("")}
        </select>
        <button class="file-remove" data-i="${i}" title="Remove">✕</button>
      </li>
    `).join("");
    ul.querySelectorAll(".file-account").forEach(sel => {
      sel.addEventListener("change", (e) => {
        const i = Number(e.target.dataset.i);
        state.files[i].account = e.target.value;
        state.lastAccount = e.target.value;
      });
    });
    ul.querySelectorAll(".file-remove").forEach(btn => {
      btn.addEventListener("click", (e) => {
        state.files.splice(Number(e.currentTarget.dataset.i), 1);
        renderFileList();
      });
    });
    document.getElementById("compile-btn").disabled = state.files.length === 0;
  }

  // ---------- compile ----------

  function wireCompile() {
    document.getElementById("compile-btn").addEventListener("click", async () => {
      if (state.files.length === 0) return;
      const btn = document.getElementById("compile-btn");
      btn.disabled = true; btn.textContent = "Compiling…";
      try {
        const fd = new FormData();
        state.files.forEach(entry => {
          fd.append("files", entry.file, entry.file.name);
          fd.append("accounts", entry.account);
        });
        state.session = await api.postForm("/api/outflows/compile", fd);
        seedDateRange();
        renderAll();
        document.getElementById("results").classList.remove("hidden");
        toast(`Compiled ${state.session.rows.length} transactions`, "ok");
      } catch (e) {
        // toast already shown
      } finally {
        btn.disabled = false; btn.textContent = "Compile";
      }
    });
  }

  function seedDateRange() {
    const dates = state.session.rows.map(r => r.date).filter(Boolean).sort();
    const from = dates[0] || new Date().toISOString().slice(0, 10);
    const to = dates[dates.length - 1] || new Date().toISOString().slice(0, 10);
    document.getElementById("date-from").value = from;
    document.getElementById("date-to").value = to;
    state.range.from = from; state.range.to = to;
  }

  function wireRange() {
    document.getElementById("date-from").addEventListener("change", (e) => {
      state.range.from = e.target.value; renderAll();
    });
    document.getElementById("date-to").addEventListener("change", (e) => {
      state.range.to = e.target.value; renderAll();
    });
  }

  // ---------- view computation ----------

  function scopedRows() {
    if (!state.session) return [];
    const excluded = new Set(state.config.excluded || []);
    return state.session.rows.filter(r => {
      if (state.range.from && r.date < state.range.from) return false;
      if (state.range.to && r.date > state.range.to) return false;
      if (r.duplicate) return false;
      if (excluded.has(r.category)) return false;
      return true;
    });
  }

  function unmappedRows() {
    if (!state.session) return [];
    return state.session.rows.filter(r => {
      if (state.range.from && r.date < state.range.from) return false;
      if (state.range.to && r.date > state.range.to) return false;
      if (r.duplicate) return false;
      return r.category === "Uncategorised";
    });
  }

  // ---------- render ----------

  function renderAll() {
    renderWarnings();
    const rows = scopedRows();
    renderTiles(rows);
    renderChart(rows);
    renderFilters();
    renderTable(rows);
    document.getElementById("row-count").textContent = `${rows.length} in range`;
  }

  function renderWarnings() {
    const root = document.getElementById("warnings");
    if (!state.session) { root.innerHTML = ""; return; }
    const parts = [];
    const s = state.session;
    if (s.mapping_status) {
      parts.push(`<div class="card"><div class="muted">Mapping: ${s.mapping_status.n_rules} rules${s.mapping_status.rebuilt ? " (just rebuilt from xlsx)" : ""}</div></div>`);
    }
    if (s.unfamiliar_accounts && s.unfamiliar_accounts.length) {
      parts.push(`<div class="card warning-card"><strong>Unfamiliar accounts:</strong> ${s.unfamiliar_accounts.join(", ")}</div>`);
    }
    const warnPanel = (title, items) => {
      if (!items || items.length === 0) return "";
      return `<div class="card warning-card"><details><summary>${title} (${items.length})</summary><ul class="warning-list">${items.map(w => `<li>${escapeHtml(w)}</li>`).join("")}</ul></details></div>`;
    };
    parts.push(warnPanel("Mapping warnings", s.mapping_warnings));
    parts.push(warnPanel("History warnings", s.history_warnings));
    root.innerHTML = parts.join("");
  }

  function renderTiles(rows) {
    const total = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
    const unmappedCount = rows.filter(r => r.category === "Uncategorised").length;
    document.getElementById("tile-total").textContent = fmtSgd(total);
    document.getElementById("tile-txns").textContent = String(rows.length);
    document.getElementById("tile-unmapped").textContent = String(unmappedCount);
    document.getElementById("tile-unmapped-sub").textContent =
      rows.length ? `${Math.round(unmappedCount / rows.length * 100)}% of in-range` : "";
    document.getElementById("tile-dropped").textContent = String(state.session.dropped_negatives || 0);
    document.getElementById("tile-dropped-sub").textContent = `${state.session.duplicates_count || 0} duplicates`;
    document.getElementById("tile-total-sub").textContent =
      `${state.range.from || "—"} → ${state.range.to || "—"}`;
    document.getElementById("tile-txns-sub").textContent =
      `${state.config.excluded.length ? state.config.excluded.length + " categories excluded" : ""}`;
  }

  const PALETTE = ["#0b66ff","#18794e","#b54708","#b42318","#9333ea","#0d9488","#65a30d","#c2410c","#7c3aed","#0891b2","#be185d","#475569"];

  function renderChart(rows) {
    const byCat = new Map();
    rows.forEach(r => {
      const k = r.category || "Uncategorised";
      byCat.set(k, (byCat.get(k) || 0) + Number(r.amount || 0));
    });
    const data = [...byCat.entries()].sort((a, b) => b[1] - a[1]);
    Plotly.react("chart", [{
      type: "bar",
      orientation: "h",
      x: data.map(d => d[1]),
      y: data.map(d => d[0]),
      marker: { color: data.map((_, i) => PALETTE[i % PALETTE.length]) },
      hovertemplate: "%{y}: %{x:$,.0f}<extra></extra>",
    }], {
      margin: { l: 140, r: 24, t: 12, b: 32 },
      xaxis: { tickformat: "$,.0f" },
      yaxis: { autorange: "reversed" },
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { family: "-apple-system, Inter, sans-serif", size: 12 },
    }, { displayModeBar: false, responsive: true });
  }

  function renderFilters() {
    const cats = [...new Set(state.session.rows.map(r => r.category).filter(Boolean))].sort();
    const accts = [...new Set(state.session.rows.map(r => r.account).filter(Boolean))].sort();
    const c = document.getElementById("filter-category");
    const a = document.getElementById("filter-account");
    const curC = c.value, curA = a.value;
    c.innerHTML = '<option value="">All categories</option>' + cats.map(x => `<option value="${x}">${x}</option>`).join("");
    a.innerHTML = '<option value="">All accounts</option>' + accts.map(x => `<option value="${x}">${x}</option>`).join("");
    c.value = curC; a.value = curA;
    c.onchange = renderTableFromCurrent;
    a.onchange = renderTableFromCurrent;
  }

  function renderTableFromCurrent() { renderTable(scopedRows()); }

  function renderTable(rows) {
    const c = document.getElementById("filter-category").value;
    const a = document.getElementById("filter-account").value;
    const filtered = rows.filter(r => (!c || r.category === c) && (!a || r.account === a));
    const cols = [
      { title: "Date", field: "date", width: 100, sorter: "string" },
      { title: "Description", field: "description", minWidth: 220, sorter: "string" },
      { title: "Amount", field: "amount", hozAlign: "right", width: 110, sorter: "number",
        formatter: (cell) => fmtSgd(cell.getValue()) },
      { title: "Category", field: "category", width: 160, sorter: "string",
        formatter: (cell) => `<span class="tag ${cell.getValue() === "Uncategorised" ? "tag-warning" : ""}">${cell.getValue()}</span>` },
      { title: "Account", field: "account", width: 140, sorter: "string" },
      { title: "Matched pattern", field: "matched_pattern", minWidth: 160, sorter: "string" },
      { title: "Source", field: "source_file", minWidth: 140, sorter: "string" },
    ];
    if (state.tabulator) state.tabulator.destroy();
    state.tabulator = new Tabulator("#transactions-table", {
      data: filtered,
      columns: cols,
      layout: "fitColumns",
      height: 480,
      pagination: true,
      paginationSize: 50,
    });
  }

  // ---------- downloads ----------

  function wireDownloads() {
    const body = () => ({ start_date: state.range.from, end_date: state.range.to });
    const needSession = () => {
      if (!state.session) { toast("Compile first", "warn"); return null; }
      return state.session.session_id;
    };
    document.getElementById("dl-categorised").addEventListener("click", async () => {
      const sid = needSession(); if (!sid) return;
      await api.download(`/api/outflows/download/categorised/${sid}`, { body: body(), fallbackName: "categorised.xlsx" });
    });
    document.getElementById("dl-unmapped").addEventListener("click", async () => {
      const sid = needSession(); if (!sid) return;
      await api.download(`/api/outflows/download/unmapped/${sid}`, { body: body(), fallbackName: "unmapped.xlsx" });
    });
    document.getElementById("dl-html").addEventListener("click", async () => {
      const sid = needSession(); if (!sid) return;
      await api.download(`/api/outflows/download/html/${sid}`, { body: body(), fallbackName: "snapshot.html" });
    });
    document.getElementById("append-history").addEventListener("click", async () => {
      const sid = needSession(); if (!sid) return;
      const n = unmappedRows().length;
      if (n === 0) { toast("Nothing unmapped to append in this range", "warn"); return; }
      if (!confirm(`Append up to ${n} unmapped transactions to transaction_history.xlsx?`)) return;
      const res = await api.postJson(`/api/outflows/history/append/${sid}`, body());
      toast(`Added ${res.n_added}, skipped ${res.n_skipped}`, res.n_added ? "ok" : "info");
    });
  }

  // ---------- util ----------

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, m => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[m]));
  }

  boot();
})();
