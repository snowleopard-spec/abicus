(() => {
  // Same earthy palette as the main outflows chart, rust reserved for Uncategorised.
  const PALETTE = [
    "#8B7355", "#6B8E23", "#8B6F47", "#5C7A5C", "#A0826D",
    "#7B6F5C", "#9B7E5A", "#6B5D4F", "#A89070", "#5D6B4E",
  ];
  const UNCAT_COLOUR = "#C77B4F";
  const UNCAT = "Uncategorised";

  const fmtSGD = new Intl.NumberFormat("en-SG", {
    style: "currency", currency: "SGD", minimumFractionDigits: 0, maximumFractionDigits: 0,
  });
  const fmtSGDprecise = new Intl.NumberFormat("en-SG", {
    style: "currency", currency: "SGD", minimumFractionDigits: 2, maximumFractionDigits: 2,
  });

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
    const categories = Object.keys(data.lifetime_totals || {});
    if (categories.length === 0) {
      document.getElementById("breakdown-empty").classList.remove("hidden");
      return;
    }

    render(data);
  }

  // ---- Render ----
  function render(data) {
    const grid = document.getElementById("breakdown-grid");
    grid.classList.remove("hidden");

    const months = data.months || [];
    const byCat = data.by_category || {};
    const lifetime = data.lifetime_totals || {};
    // Order: lifetime total desc (already sorted by the backend but be safe).
    const categories = Object.keys(lifetime).sort(
      (a, b) => lifetime[b] - lifetime[a],
    );

    // Chart height scales with month count so every tile has room for the
    // full month axis — cap so a single 60-month dataset doesn't dwarf the page.
    const barPx = 22;
    const chartH = Math.min(
      520,
      Math.max(140, months.length * barPx + 60),
    );
    grid.style.setProperty("--tile-chart-h", `${chartH}px`);

    grid.innerHTML = "";
    let paletteIdx = 0;
    for (const cat of categories) {
      const tile = document.createElement("div");
      tile.className = "breakdown-tile";
      tile.innerHTML = `
        <div class="breakdown-tile-header">
          <span class="breakdown-tile-title">${escapeHtml(cat)}</span>
          <span class="breakdown-tile-total">${fmtSGD.format(lifetime[cat] || 0)}</span>
        </div>
        <div class="breakdown-tile-chart"></div>
      `;
      grid.appendChild(tile);

      const chartEl = tile.querySelector(".breakdown-tile-chart");
      const colour = cat === UNCAT ? UNCAT_COLOUR : PALETTE[paletteIdx++ % PALETTE.length];
      const catMonths = byCat[cat] || {};
      // Every tile shares the same x-axis of all known months so panels
      // read as a consistent time-series across the page.
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
        {
          height: chartH,
          margin: { l: 58, r: 40, t: 6, b: 32 },
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
        },
        { displayModeBar: false, responsive: true, staticPlot: false },
      );
    }
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
