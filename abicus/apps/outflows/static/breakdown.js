(() => {
  // Lighter earthy palette, kept in sync with outflows.js and pdf_export.py.
  // Rust reserved for Uncategorised so it stays visually distinctive.
  const PALETTE = [
    "#B49F7A", "#95B54F", "#B49877", "#8AA88A", "#BFA294",
    "#A59988", "#BFA284", "#968878", "#C4AE94", "#8FA075",
    "#C4B08C", "#8FA8A0", "#A0B482", "#B8C594",
  ];
  const TOTAL_COLOUR = "#8B7A6A"; // soft brown for the header total bars
  const UNCAT_COLOUR = "#C77B4F";
  const UNCAT = "Uncategorised";

  const fmtSGD = new Intl.NumberFormat("en-SG", {
    style: "currency", currency: "SGD", minimumFractionDigits: 0, maximumFractionDigits: 0,
  });
  const fmtSGDprecise = new Intl.NumberFormat("en-SG", {
    style: "currency", currency: "SGD", minimumFractionDigits: 2, maximumFractionDigits: 2,
  });

  // Categories the header toggle removes from totals (and whose tiles it
  // hides). Names must match config/categories.txt exactly.
  const EXCLUDABLE_CATS = ["Rent", "Education", "Holidays", "Exceptional"];

  const state = {
    data: null,             // {months, by_category, lifetime_totals}
    selectedMonths: new Set(),
    excludeHeavy: false,    // header toggle: drop EXCLUDABLE_CATS from view
  };

  // ---- Boot ----
  async function boot() {
    const status = document.getElementById("breakdown-status");
    const errEl = document.getElementById("breakdown-error");
    let data;
    try {
      data = await api.get("/api/outflows/breakdown");
    } catch (err) {
      status.classList.add("hidden");
      errEl.textContent = `Failed to load: ${err.message || err}`;
      errEl.classList.remove("hidden");
      return;
    }

    status.classList.add("hidden");
    if (!data.months || data.months.length === 0) {
      document.getElementById("breakdown-empty").classList.remove("hidden");
      return;
    }

    state.data = data;
    state.selectedMonths = new Set(data.months);
    renderChips();
    document.getElementById("breakdown-controls").classList.remove("hidden");
    document.getElementById("breakdown-grid").classList.remove("hidden");
    wireShortcuts();
    wireExport();
    document
      .getElementById("breakdown-detail-close")
      .addEventListener("click", hideDetail);
    wireDetailFilters();
    redraw();
  }

  function wireExport() {
    const htmlBtn = document.getElementById("export-html-btn");
    if (htmlBtn) {
      htmlBtn.addEventListener("click", async () => {
        htmlBtn.disabled = true;
        const originalText = htmlBtn.textContent;
        htmlBtn.textContent = "Generating…";
        try {
          await api.download("/api/outflows/breakdown/html", {
            method: "GET",
            fallbackName: "monthly_breakdown.html",
          });
        } catch (err) {
          alert(`Export failed: ${err.message || err}`);
        } finally {
          htmlBtn.disabled = false;
          htmlBtn.textContent = originalText;
        }
      });
    }

    const btn = document.getElementById("export-pdf-btn");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const originalText = btn.textContent;
      btn.textContent = "Generating…";
      try {
        // Reflect on-screen month order in the exported PDF.
        const months = state.data.months.filter((m) => state.selectedMonths.has(m));
        await api.download("/api/outflows/breakdown/pdf", {
          body: { selected_months: months },
          fallbackName: "monthly_breakdown.pdf",
        });
      } catch (err) {
        alert(`Export failed: ${err.message || err}`);
      } finally {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  }

  // ---- Month chips ----
  function renderChips() {
    const wrap = document.getElementById("month-chips");
    wrap.innerHTML = "";
    for (const m of state.data.months) {
      const label = document.createElement("label");
      label.className = "month-chip is-on";
      label.innerHTML = `<input type="checkbox" checked data-month="${m}">${monthLabel(m)}`;
      label.querySelector("input").addEventListener("change", (e) => {
        const month = e.target.dataset.month;
        if (e.target.checked) {
          state.selectedMonths.add(month);
          label.classList.add("is-on");
        } else {
          state.selectedMonths.delete(month);
          label.classList.remove("is-on");
        }
        redraw();
      });
      wrap.appendChild(label);
    }
  }

  function wireShortcuts() {
    document.getElementById("exclude-heavy").addEventListener("change", (e) => {
      state.excludeHeavy = e.target.checked;
      redraw();
    });
  }

  // ---- Grid render ----
  function redraw() {
    const grid = document.getElementById("breakdown-grid");
    grid.innerHTML = "";
    hideDetail(); // a bar selection is stale once the month set changes

    // Months in canonical order, restricted to what's selected.
    const months = state.data.months.filter((m) => state.selectedMonths.has(m));
    const byCat = state.data.by_category || {};

    // Compute per-category totals restricted to selected months.
    // Categories with $0 in the selection get filtered out — no point rendering an empty tile.
    const catNames = Object.keys(byCat).filter(
      (c) => !(state.excludeHeavy && EXCLUDABLE_CATS.includes(c)),
    );
    const catTotals = {};
    for (const cat of catNames) {
      let t = 0;
      for (const m of months) t += byCat[cat][m] || 0;
      if (t > 0) catTotals[cat] = t;
    }
    const categories = Object.keys(catTotals).sort(
      (a, b) => catTotals[b] - catTotals[a],
    );

    // --- Full-width Monthly Total tile ---
    renderTotalTile(grid, months, byCat, categories);

    // Per-tile chart height scales with month count (bar-based).
    const barPx = 22;
    const chartH = Math.min(520, Math.max(140, months.length * barPx + 60));
    grid.style.setProperty("--tile-chart-h", `${chartH}px`);
    // Total tile a bit bigger.
    grid.style.setProperty("--total-chart-h", `${Math.min(520, chartH + 60)}px`);

    // Grand total across the visible categories — the denominator for each
    // tile's %-of-expenditure badge. Respects the exclude toggle by
    // construction (excluded categories never reach catTotals).
    const visibleGrand = categories.reduce((a, c) => a + catTotals[c], 0);

    let paletteIdx = 0;
    for (const cat of categories) {
      const pct = visibleGrand > 0 ? (catTotals[cat] / visibleGrand) * 100 : 0;
      const pctLabel = pct >= 0.5 ? `${Math.round(pct)}%` : "<1%";
      const tile = document.createElement("div");
      tile.className = "breakdown-tile";
      tile.innerHTML = `
        <div class="breakdown-tile-header">
          <span class="breakdown-tile-title">${escapeHtml(cat)}</span>
          <span class="breakdown-tile-pct" title="${pct.toFixed(1)}% of expenditure across the selected months">${pctLabel}</span>
          <span class="breakdown-tile-amount">${fmtSGD.format(catTotals[cat])}</span>
        </div>
        <div class="breakdown-tile-chart"></div>
      `;
      grid.appendChild(tile);

      const chartEl = tile.querySelector(".breakdown-tile-chart");
      const colour = cat === UNCAT ? UNCAT_COLOUR : PALETTE[paletteIdx++ % PALETTE.length];
      const catMonths = byCat[cat] || {};
      const values = months.map((m) => catMonths[m] || 0);
      const labels = months.map(monthLabel);
      Plotly.react(
        chartEl,
        [{
          type: "bar",
          orientation: "h",
          x: values,
          y: labels,
          marker: { color: colour },
          text: values.map((v) => (v > 0 ? fmtSGD.format(v) : "")),
          textposition: "outside",
          cliponaxis: false,
          hovertemplate: "<b>%{y}</b><br>%{customdata}<extra></extra>",
          customdata: values.map((v) => fmtSGDprecise.format(v)),
        }],
        chartLayout(chartH),
        { displayModeBar: false, responsive: true },
      ).then((gd) => {
        gd.on("plotly_click", (ev) => {
          showDetail(months[ev.points[0].pointIndex], cat);
        });
      });
    }
  }

  function renderTotalTile(grid, months, byCat, categories) {
    const tile = document.createElement("div");
    tile.className = "breakdown-tile breakdown-tile-total";

    if (months.length === 0) {
      tile.innerHTML = `
        <div class="breakdown-tile-header">
          <span class="breakdown-tile-title">Monthly total</span>
        </div>
        <div class="caption" style="margin:0;">Pick at least one month to see totals.</div>
      `;
      grid.appendChild(tile);
      return;
    }

    // Sum each visible category's spend for each selected month — `categories`
    // already excludes the toggled-off ones (and $0 categories, which add nothing).
    const monthTotals = months.map((m) => {
      let t = 0;
      for (const cat of categories) t += byCat[cat][m] || 0;
      return t;
    });
    const grandTotal = monthTotals.reduce((a, b) => a + b, 0);
    const exclNote = state.excludeHeavy
      ? ` · excl. ${EXCLUDABLE_CATS.join("/")}`
      : "";

    tile.innerHTML = `
      <div class="breakdown-tile-header">
        <span class="breakdown-tile-title">Monthly total (${months.length} month${months.length === 1 ? "" : "s"}, ${categories.length} categor${categories.length === 1 ? "y" : "ies"}${exclNote})</span>
        <span class="breakdown-tile-amount">${fmtSGDprecise.format(grandTotal)}</span>
      </div>
      <div class="breakdown-tile-chart"></div>
    `;
    grid.appendChild(tile);

    const chartEl = tile.querySelector(".breakdown-tile-chart");
    const totalH = Math.min(520, Math.max(220, months.length * 28 + 80));
    grid.style.setProperty("--total-chart-h", `${totalH}px`);
    Plotly.react(
      chartEl,
      [{
        type: "bar",
        orientation: "h",
        x: monthTotals,
        y: months.map(monthLabel),
        marker: { color: TOTAL_COLOUR },
        text: monthTotals.map((v) => fmtSGD.format(v)),
        textposition: "outside",
        cliponaxis: false,
        hovertemplate: "<b>%{y}</b><br>%{customdata}<extra></extra>",
        customdata: monthTotals.map((v) => fmtSGDprecise.format(v)),
      }],
      chartLayout(totalH),
      { displayModeBar: false, responsive: true },
    ).then((gd) => {
      gd.on("plotly_click", (ev) => {
        showDetail(months[ev.points[0].pointIndex], null);
      });
    });
  }

  // ---- Per-bar transaction detail box ----
  // Mirrors the Spending Review page's Categorised Transactions section:
  // a Tabulator table (sortable columns) behind category/account/search
  // filters. Rows are fetched per clicked bar; filters are client-side.
  let detailToken = 0; // discards stale responses when bars are clicked quickly
  const detail = {
    rows: [],
    filter: { category: "All", account: "All", search: "" },
    table: null,
  };

  function hideDetail() {
    detailToken++;
    document.getElementById("breakdown-detail").classList.add("hidden");
  }

  function wireDetailFilters() {
    document.getElementById("bd-filter-category").addEventListener("change", (e) => {
      detail.filter.category = e.target.value;
      renderDetailTable();
    });
    document.getElementById("bd-filter-account").addEventListener("change", (e) => {
      detail.filter.account = e.target.value;
      renderDetailTable();
    });
    document.getElementById("bd-filter-search").addEventListener("input", (e) => {
      detail.filter.search = e.target.value;
      renderDetailTable();
    });
  }

  async function showDetail(month, cat) {
    const token = ++detailToken;
    const section = document.getElementById("breakdown-detail");
    const caption = document.getElementById("breakdown-detail-caption");
    const allLabel = state.excludeHeavy
      ? `All categories (excl. ${EXCLUDABLE_CATS.join("/")})`
      : "All categories";
    document.getElementById("breakdown-detail-title").textContent =
      `${cat === null ? allLabel : cat} — ${monthLabel(month)}`;
    caption.textContent = "Loading…";
    section.classList.remove("hidden");

    let data;
    try {
      const params = new URLSearchParams({ month });
      if (cat !== null) params.set("category", cat);
      data = await api.get(`/api/outflows/breakdown/transactions?${params}`);
    } catch (err) {
      if (token !== detailToken) return;
      caption.textContent = `Failed to load: ${err.message || err}`;
      return;
    }
    if (token !== detailToken) return; // a newer click superseded this one

    let rows = data.rows || [];
    // Keep the "All categories" detail box consistent with the total bar
    // that was clicked — excluded categories stay out of it too.
    if (cat === null && state.excludeHeavy) {
      rows = rows.filter((r) => !EXCLUDABLE_CATS.includes(r.category));
    }
    detail.rows = rows;
    detail.filter = { category: "All", account: "All", search: "" };
    document.getElementById("bd-filter-search").value = "";
    renderDetailTable();
    section.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderDetailTable() {
    refreshDetailFilterOptions("bd-filter-category", "category");
    refreshDetailFilterOptions("bd-filter-account", "account");

    const { category, account, search } = detail.filter;
    let view = detail.rows;
    if (category !== "All") view = view.filter((r) => r.category === category);
    if (account !== "All") view = view.filter((r) => r.account === account);
    const q = search.trim().toLowerCase();
    if (q) {
      view = view.filter((r) =>
        String(r.description ?? "").toLowerCase().includes(q));
    }

    const total = view.reduce((a, r) => a + r.amount, 0);
    document.getElementById("breakdown-detail-caption").textContent =
      `${view.length} transaction${view.length === 1 ? "" : "s"} · ${fmtSGDprecise.format(total)}`;

    if (!detail.table) {
      detail.table = new Tabulator("#breakdown-detail-table", {
        data: view,
        layout: "fitColumns",
        placeholder: "No transactions match the current filters.",
        pagination: false,
        maxHeight: "500px",
        columns: [
          { title: "Date", field: "date", width: 110, sorter: "string" },
          { title: "Description", field: "description", minWidth: 200 },
          { title: "Amount", field: "amount", hozAlign: "right", width: 110, sorter: "number",
            formatter: (cell) => fmtSGD.format(cell.getValue()) },
          { title: "Category", field: "category", width: 160 },
          { title: "Account", field: "account", width: 160 },
        ],
      });
    } else {
      detail.table.replaceData(view);
    }
  }

  function refreshDetailFilterOptions(selectId, field) {
    const select = document.getElementById(selectId);
    const current = detail.filter[field];
    const values = [...new Set(detail.rows.map((r) => r[field]))].sort();
    select.innerHTML = "";
    for (const v of ["All", ...values]) {
      const opt = document.createElement("option");
      opt.value = v; opt.textContent = v;
      if (v === current) opt.selected = true;
      select.appendChild(opt);
    }
    if (!["All", ...values].includes(current)) {
      detail.filter[field] = "All";
      select.value = "All";
    }
  }

  function chartLayout(height) {
    return {
      height,
      margin: { l: 62, r: 44, t: 6, b: 32 },
      xaxis: {
        tickprefix: "$",
        tickformat: ",.0f",
        gridcolor: "#EEE",
        zerolinecolor: "#DDD",
        fixedrange: true,
      },
      yaxis: {
        autorange: "reversed",
        automargin: true,
        fixedrange: true,
      },
      plot_bgcolor: "white",
      paper_bgcolor: "white",
      font: { family: "Source Sans Pro, sans-serif", size: 11 },
      bargap: 0.25,
    };
  }

  function monthLabel(iso) {
    // "2026-01" → "Jan 26"
    const [y, m] = iso.split("-");
    const names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return `${names[parseInt(m, 10) - 1]} ${y.slice(2)}`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  boot().catch((err) => console.error("Breakdown boot failed:", err));
})();
