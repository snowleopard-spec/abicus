(() => {
  const state = {
    config: null,
    files: [],
    session: null,
    lastSource: null,
    tabulator: null,
    hideBalances: false,
    lookthrough: false,
  };

  const PALETTE = ["#8B7355","#B8860B","#6B8E6B","#A0522D","#708090","#CD853F","#556B2F","#8B6914","#7B6B5A","#9E7B5B"];

  const fmtUsd = (v) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v || 0);
  const fmtPct = (v) => `${(v || 0).toFixed(1)}%`;
  const fmtLocal = (v) => v == null || Number.isNaN(v) ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });

  // ---------- boot ----------

  async function boot() {
    try {
      state.config = await api.get("/api/assets/config");
    } catch (e) { return; }
    renderSavedMeta();
    wireDropzone();
    wireCompile();
    wireLoadLast();
    wireOptions();
    wireDownloads();
    wireSave();
    wireUnmappedAdd();
  }

  function renderSavedMeta() {
    const c = state.config;
    const el = document.getElementById("saved-meta");
    if (c.saved && c.saved.exists) {
      el.textContent = `Last saved: ${c.saved.timestamp} (${c.saved.item_count} items)`;
      document.getElementById("load-last-btn").disabled = false;
    } else {
      el.textContent = "No saved snapshot yet";
    }
  }

  // ---------- file list / dropzone ----------

  function wireDropzone() {
    const dz = document.getElementById("dropzone");
    const input = document.getElementById("file-input");
    document.getElementById("browse-btn").addEventListener("click", (e) => {
      e.stopPropagation(); input.click();
    });
    dz.addEventListener("click", (e) => {
      if (e.target.id !== "browse-btn") input.click();
    });
    input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
    ["dragenter","dragover"].forEach(ev => dz.addEventListener(ev, (e) => {
      e.preventDefault(); dz.classList.add("is-drag");
    }));
    ["dragleave","drop"].forEach(ev => dz.addEventListener(ev, (e) => {
      e.preventDefault(); dz.classList.remove("is-drag");
    }));
    dz.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
  }

  function addFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const defaultSrc = state.lastSource || (state.config.sources[0] && state.config.sources[0].name) || "";
    for (const f of fileList) {
      state.files.push({ file: f, source: defaultSrc });
    }
    renderFileList();
  }

  function renderFileList() {
    const wrap = document.getElementById("file-list");
    const rows = document.getElementById("file-rows");
    rows.innerHTML = "";
    if (state.files.length === 0) {
      wrap.classList.add("hidden");
      document.getElementById("compile-btn").disabled = true;
      return;
    }
    wrap.classList.remove("hidden");
    document.getElementById("compile-btn").disabled = false;

    state.files.forEach((entry, i) => {
      const row = document.createElement("div");
      row.className = "file-row";

      const name = document.createElement("div");
      name.className = "file-row-name";
      name.textContent = `📄 ${entry.file.name}`;
      row.appendChild(name);

      const select = document.createElement("select");
      state.config.sources.forEach(s => {
        const opt = document.createElement("option");
        opt.value = s.name;
        opt.textContent = `${s.name} (${s.parser})`;
        if (s.name === entry.source) opt.selected = true;
        select.appendChild(opt);
      });
      select.addEventListener("change", () => {
        state.files[i].source = select.value;
        state.lastSource = select.value;
      });
      row.appendChild(select);

      const rm = document.createElement("button");
      rm.className = "remove-btn"; rm.type = "button"; rm.textContent = "×"; rm.title = "Remove file";
      rm.addEventListener("click", () => {
        state.files.splice(i, 1);
        renderFileList();
      });
      row.appendChild(rm);

      rows.appendChild(row);
    });
  }

  // ---------- compile / load ----------

  function wireCompile() {
    document.getElementById("compile-btn").addEventListener("click", async () => {
      if (state.files.length === 0) return;
      const btn = document.getElementById("compile-btn");
      btn.disabled = true; btn.textContent = "Compiling…";
      try {
        const fd = new FormData();
        state.files.forEach(e => fd.append("files", e.file, e.file.name));
        const assignments = state.files.map(e => ({ filename: e.file.name, source: e.source }));
        fd.append("assignments", JSON.stringify(assignments));
        state.session = await api.postForm("/api/assets/compile", fd);
        renderAll();
        document.getElementById("results").classList.remove("hidden");
        toast(`Compiled ${state.session.holdings.length} holdings`, "ok");
      } catch (e) {} finally {
        btn.disabled = false; btn.textContent = "Compile";
      }
    });
  }

  function wireLoadLast() {
    document.getElementById("load-last-btn").addEventListener("click", async () => {
      try {
        state.session = await api.postJson("/api/assets/load", {});
        renderAll();
        document.getElementById("results").classList.remove("hidden");
        toast(`Loaded ${state.session.holdings.length} holdings`, "ok");
      } catch (e) {}
    });
  }

  function wireOptions() {
    document.getElementById("opt-hide-balances").addEventListener("change", (e) => {
      state.hideBalances = e.target.checked;
      renderAllocations();
    });
    document.getElementById("opt-lookthrough").addEventListener("change", (e) => {
      state.lookthrough = e.target.checked;
      renderAllocations();
    });
  }

  // ---------- render ----------

  function renderAll() {
    renderBanners();
    renderTiles();
    renderHoldings();
    renderAllocations();
    renderUnmapped();
    renderReferences();
  }

  function renderBanners() {
    const s = state.session;
    const root = document.getElementById("banners");
    const parts = [];
    if (s.fx_error) {
      parts.push(`<div class="card banner-error"><strong>FX error:</strong> Live rates could not be retrieved. Balance (USD) values may be missing.</div>`);
    }
    if (s.yfinance_error) {
      parts.push(`<div class="card banner-warning"><strong>Stock prices:</strong> yfinance unavailable; using fallback values where possible.</div>`);
    }
    if (s.compile_errors && s.compile_errors.length) {
      parts.push(`<div class="card banner-error"><strong>Compile errors:</strong><ul>${s.compile_errors.map(e => `<li><pre style="white-space:pre-wrap;margin:0;">${escapeHtml(e)}</pre></li>`).join("")}</ul></div>`);
    }
    if (s.compile_log && s.compile_log.length) {
      parts.push(`<div class="card banner-info"><strong>Compile log:</strong><ul>${s.compile_log.map(e => `<li>${escapeHtml(e)}</li>`).join("")}</ul></div>`);
    }
    if (s.price_errors && s.price_errors.length) {
      parts.push(`<div class="card banner-warning"><strong>Price errors:</strong> ${s.price_errors.slice(0, 6).map(escapeHtml).join("; ")}${s.price_errors.length > 6 ? "…" : ""}</div>`);
    }
    root.innerHTML = parts.join("");
  }

  function renderTiles() {
    const s = state.session;
    document.getElementById("tile-total").textContent = fmtUsd(s.total_usd);
    document.getElementById("tile-total-sub").textContent =
      s.fetched_prices && Object.keys(s.fetched_prices).length
        ? `${Object.keys(s.fetched_prices).length} live prices`
        : "";
    document.getElementById("tile-count").textContent = s.holdings.length;
    const cashCount = s.holdings.filter(h => h["Asset Class"] === "Cash").length;
    document.getElementById("tile-count-sub").textContent = `${cashCount} cash positions`;
    document.getElementById("tile-fx").textContent = s.fx_error ? "error" : "live";
    document.getElementById("tile-fx-sub").textContent = s.fx_rates
      ? `${Object.keys(s.fx_rates).length} currencies`
      : "";
  }

  function renderHoldings() {
    const cols = [
      { title: "Asset Name", field: "Asset Name", minWidth: 200 },
      { title: "Asset Class", field: "Asset Class", width: 130 },
      { title: "Broad", field: "Broad Asset Class", width: 110 },
      { title: "Currency", field: "Currency", width: 80, hozAlign: "center" },
      { title: "Institution", field: "Institution", width: 140 },
      { title: "Account Type", field: "Account Type", width: 130 },
      { title: "Jurisdiction", field: "Jurisdiction", width: 110 },
      { title: "Local", field: "Balance (Local)", hozAlign: "right", width: 110,
        formatter: (cell) => fmtLocal(cell.getValue()) },
      { title: "USD", field: "Balance (USD)", hozAlign: "right", width: 110,
        formatter: (cell) => fmtUsd(cell.getValue()) },
      { title: "US Situs", field: "US Situs Flag", width: 90, hozAlign: "center" },
      { title: "Tag", field: "Tag", width: 100 },
    ];
    if (state.tabulator) state.tabulator.destroy();
    state.tabulator = new Tabulator("#holdings-table", {
      data: state.session.holdings,
      columns: cols,
      layout: "fitColumns",
      height: 480,
      pagination: true,
      paginationSize: 50,
    });
  }

  const CHART_LABELS = {
    broad_asset_class: "Broad asset class",
    asset_class: "Asset class",
    currency: "Currency",
    currency_lookthrough: "Currency (look-through)",
    jurisdiction: "Jurisdiction",
    institution: "Institution",
    account_type: "Account type",
    us_situs: "US situs",
    cash_by_institution: "Cash by institution",
  };

  function renderAllocations() {
    const root = document.getElementById("alloc-charts");
    const A = state.session.allocations || {};
    const ordered = state.lookthrough
      ? ["broad_asset_class","asset_class","currency_lookthrough","jurisdiction","institution","account_type","us_situs","cash_by_institution"]
      : ["broad_asset_class","asset_class","currency","jurisdiction","institution","account_type","us_situs","cash_by_institution"];
    root.innerHTML = ordered.map(key => {
      const chart = A[key];
      if (!chart) return "";
      const title = CHART_LABELS[key] || key;
      if (!chart.rows || chart.rows.length === 0) {
        return `<div class="card alloc-chart"><div class="card__header"><h2 class="card__title">${title}</h2></div><div class="muted">No data.</div></div>`;
      }
      const segs = chart.rows.map((r, i) => `<span class="seg" style="width:${r.pct}%;background:${PALETTE[i % PALETTE.length]}" title="${escapeHtml(r.label)}: ${fmtPct(r.pct)}"></span>`).join("");
      const rows = chart.rows.map((r, i) => `
        <tr>
          <td class="swatch"><span style="display:inline-block;width:10px;height:10px;background:${PALETTE[i % PALETTE.length]};border-radius:2px;"></span></td>
          <td class="label">${escapeHtml(r.label)}</td>
          ${state.hideBalances ? "" : `<td class="amount">${fmtUsd(r.value)}</td>`}
          <td class="pct">${fmtPct(r.pct)}</td>
        </tr>
      `).join("");
      const totalRow = `<tr class="total"><td></td><td>Total</td>${state.hideBalances ? "" : `<td class="amount">${fmtUsd(chart.total)}</td>`}<td class="pct">100.0%</td></tr>`;
      return `
        <div class="card alloc-chart">
          <div class="card__header"><h2 class="card__title">${title}</h2></div>
          <div class="chart-bar">${segs}</div>
          <table>${rows}${totalRow}</table>
        </div>`;
    }).join("");
  }

  function renderUnmapped() {
    const card = document.getElementById("unmapped-card");
    const body = document.getElementById("unmapped-body");
    const u = state.session.unmapped || { asset_class: [], us_situs: [] };
    const total = u.asset_class.length + u.us_situs.length;
    if (total === 0) { card.style.display = "none"; return; }
    card.style.display = "";
    body.innerHTML = `
      <div class="form-row">
        <div>
          <strong>Asset class</strong> (${u.asset_class.length})
          <ul style="margin-top:6px;">${u.asset_class.map(n => `<li>${escapeHtml(n)}</li>`).join("") || "<li class='muted'>—</li>"}</ul>
        </div>
        <div>
          <strong>US situs</strong> (${u.us_situs.length})
          <ul style="margin-top:6px;">${u.us_situs.map(n => `<li>${escapeHtml(n)}</li>`).join("") || "<li class='muted'>—</li>"}</ul>
        </div>
      </div>`;
  }

  function renderReferences() {
    const fx = state.session.fx_rates || {};
    const fxOrder = ["GBP","EUR","SGD","AUD","HKD","JPY"];
    const fxRows = fxOrder.filter(c => c in fx).map(c => `<tr><td>${c}/USD</td><td>${(1/fx[c]).toFixed(4)}</td></tr>`).join("");
    document.getElementById("fx-table").innerHTML = fxRows || `<tr><td class="muted">No live FX rates</td></tr>`;

    const prices = state.session.fetched_prices || {};
    const tickers = Object.keys(prices).sort();
    const priceRows = tickers.map(t => `<tr><td>${escapeHtml(t)}</td><td>${prices[t].toLocaleString(undefined,{maximumFractionDigits:4})}</td></tr>`).join("");
    document.getElementById("prices-table").innerHTML = priceRows || `<tr><td class="muted">No stock prices fetched</td></tr>`;
  }

  // ---------- downloads / save / unmapped-add ----------

  function wireDownloads() {
    document.getElementById("dl-pdf").addEventListener("click", async () => {
      if (!state.session) return;
      await api.download(`/api/assets/download/pdf/${state.session.session_id}`, {
        body: { hide_balances: state.hideBalances, lookthrough: state.lookthrough },
        fallbackName: "asset_allocation.pdf",
      });
    });
    document.getElementById("dl-excel").addEventListener("click", async () => {
      if (!state.session) return;
      await api.download(`/api/assets/download/excel/${state.session.session_id}`, {
        body: { hide_balances: state.hideBalances, lookthrough: state.lookthrough },
        fallbackName: "portfolio_holdings.xlsx",
      });
    });
  }

  function wireSave() {
    document.getElementById("save-btn").addEventListener("click", async () => {
      if (!state.session) return;
      const r = await api.postJson(`/api/assets/save/${state.session.session_id}`, {});
      toast(`Saved ${r.count} items (${r.saved.timestamp})`, "ok");
      // refresh saved meta from /api/config for the header chip
      state.config = await api.get("/api/assets/config");
      renderSavedMeta();
    });
  }

  function wireUnmappedAdd() {
    document.getElementById("add-unmapped-btn").addEventListener("click", async () => {
      if (!state.session) return;
      if (!confirm("Append all unmapped instruments to mapping_asset_class.csv and mapping_us_situs.csv?")) return;
      const r = await api.postJson(`/api/assets/unmapped/add/${state.session.session_id}`, {});
      const nChanged = (r.changed_paths || []).length;
      const suffix = nChanged
        ? ` — opening ${nChanged} file${nChanged === 1 ? "" : "s"} for editing`
        : "";
      toast(`Added ${r.added_asset_class} to asset_class, ${r.added_us_situs} to us_situs${suffix}`, "ok");
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
