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

  const state = {
    data: null,             // {months, by_category, lifetime_totals}
    selectedMonths: new Set(),
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
    redraw();
  }

  function wireExport() {
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
    document.getElementById("chip-all").addEventListener("click", () => {
      state.selectedMonths = new Set(state.data.months);
      syncChipsToState();
      redraw();
    });
    document.getElementById("chip-none").addEventListener("click", () => {
      state.selectedMonths.clear();
      syncChipsToState();
      redraw();
    });
  }

  function syncChipsToState() {
    for (const el of document.querySelectorAll(".month-chip")) {
      const input = el.querySelector("input");
      const on = state.selectedMonths.has(input.dataset.month);
      input.checked = on;
      el.classList.toggle("is-on", on);
    }
  }

  // ---- Grid render ----
  function redraw() {
    const grid = document.getElementById("breakdown-grid");
    grid.innerHTML = "";

    // Months in canonical order, restricted to what's selected.
    const months = state.data.months.filter((m) => state.selectedMonths.has(m));
    const byCat = state.data.by_category || {};

    // Compute per-category totals restricted to selected months.
    // Categories with $0 in the selection get filtered out — no point rendering an empty tile.
    const catTotals = {};
    for (const cat of Object.keys(byCat)) {
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

    let paletteIdx = 0;
    for (const cat of categories) {
      const tile = document.createElement("div");
      tile.className = "breakdown-tile";
      tile.innerHTML = `
        <div class="breakdown-tile-header">
          <span class="breakdown-tile-title">${escapeHtml(cat)}</span>
          <span class="breakdown-tile-total">${fmtSGD.format(catTotals[cat])}</span>
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
      );
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

    // Sum every category's spend for each selected month.
    const monthTotals = months.map((m) => {
      let t = 0;
      for (const cat of Object.keys(byCat)) t += byCat[cat][m] || 0;
      return t;
    });
    const grandTotal = monthTotals.reduce((a, b) => a + b, 0);

    tile.innerHTML = `
      <div class="breakdown-tile-header">
        <span class="breakdown-tile-title">Monthly total (${months.length} month${months.length === 1 ? "" : "s"}, ${categories.length} categor${categories.length === 1 ? "y" : "ies"})</span>
        <span class="breakdown-tile-total">${fmtSGDprecise.format(grandTotal)}</span>
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
    );
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
