(() => {
  const state = {
    config: null,                                  // {accounts, categories, excluded}
    files: [],                                     // [{file: File, id, account}]
    nextFileId: 1,
    session: null,                                 // /api/outflows/compile payload
    dateRange: { from: null, to: null },
    tableFilter: { category: "All", account: "All" },
    table: null,
    scoped: null,                                  // {rows, dedup, dashboardRows}
    // Per-row overrides toggled from the Duplicate / Excluded panels.
    // Stored as Sets of row _idx so persistence (below) is compact.
    unsuppressedDup: new Set(),
    reincludedExcl: new Set(),
  };

  // sessionStorage keys — cleared on tab close, per-tab so nothing leaks
  // across independent sessions.
  const SS_KEY = "abicus.outflows.session";

  // Original earthy chart palette with rust reserved for "Uncategorised".
  const PALETTE = [
    "#8B7355", "#6B8E23", "#8B6F47", "#5C7A5C", "#A0826D",
    "#7B6F5C", "#9B7E5A", "#6B5D4F", "#A89070", "#5D6B4E",
  ];
  const UNCAT_COLOUR = "#C77B4F";
  const UNCAT = "Uncategorised";

  const fmtSGD = new Intl.NumberFormat("en-SG", {
    style: "currency", currency: "SGD", minimumFractionDigits: 2,
  });

  const $ = (id) => document.getElementById(id);
  const show = (el) => el.classList.remove("hidden");
  const hide = (el) => el.classList.add("hidden");

  // ---- Boot ----
  async function boot() {
    try {
      state.config = await api.get("/api/outflows/config");
    } catch (err) {
      const el = $("config-error");
      el.textContent = `Configuration error: ${err.message}`;
      show(el);
      return;
    }
    wireDropzone();
    wireCompile();
    wireDateRange();
    wireTableFilters();
    wireDownloads();
    await tryRestoreSession();
  }

  // ---- Session persistence (survives Edit-mapping / Edit-history nav) ----
  function saveSession() {
    if (!state.session) return;
    try {
      sessionStorage.setItem(SS_KEY, JSON.stringify({
        session_id: state.session.session_id,
        dateRange: state.dateRange,
        tableFilter: state.tableFilter,
        unsuppressedDup: [...state.unsuppressedDup],
        reincludedExcl: [...state.reincludedExcl],
      }));
    } catch { /* quota / privacy mode — silently ignore */ }
  }
  function clearSavedSession() {
    try { sessionStorage.removeItem(SS_KEY); } catch { /* ignore */ }
  }
  async function tryRestoreSession() {
    let saved;
    try {
      const raw = sessionStorage.getItem(SS_KEY);
      if (!raw) return;
      saved = JSON.parse(raw);
    } catch { return; }
    if (!saved || !saved.session_id) return;

    try {
      state.session = await api.get(`/api/outflows/session/${saved.session_id}`);
    } catch {
      // Server restarted or session expired — clear and boot normally.
      clearSavedSession();
      return;
    }

    stampRowIndices();
    if (saved.dateRange) state.dateRange = saved.dateRange;
    if (saved.tableFilter) state.tableFilter = saved.tableFilter;
    // Re-apply per-row overrides. Silently drop any indices that no longer
    // exist (shouldn't happen unless the payload shape changed).
    for (const idx of saved.unsuppressedDup || []) {
      const r = state.session.rows[idx];
      if (r) { r.duplicate = false; state.unsuppressedDup.add(idx); }
    }
    for (const idx of saved.reincludedExcl || []) {
      const r = state.session.rows[idx];
      if (r) { r._reincluded = true; state.reincludedExcl.add(idx); }
    }
    // Duplicates count is a stored summary — decrement for restored un-suppresses.
    state.session.duplicates_count = Math.max(
      0, (state.session.duplicates_count || 0) - state.unsuppressedDup.size,
    );

    const notice = $("restored-notice");
    notice.textContent =
      "Restored previous compile. Re-Compile to apply any mapping or " +
      "history edits made since.";
    show(notice);
    renderResults(/* preserveDateRange */ true);
  }

  // Give every row a stable id so the un-suppress action can flip a
  // specific row's `duplicate` flag without ambiguity.
  function stampRowIndices() {
    if (!state.session || !state.session.rows) return;
    state.session.rows.forEach((r, i) => { r._idx = i; });
  }

  // ---- Dropzone / file list ----
  function wireDropzone() {
    const dz = $("dropzone");
    const input = $("file-input");
    $("browse-btn").addEventListener("click", (e) => { e.stopPropagation(); input.click(); });
    dz.addEventListener("click", (e) => { if (e.target.id !== "browse-btn") input.click(); });
    input.addEventListener("change", () => { addFiles(Array.from(input.files)); input.value = ""; });
    ["dragenter","dragover"].forEach((ev) => dz.addEventListener(ev, (e) => {
      e.preventDefault(); dz.classList.add("is-drag");
    }));
    ["dragleave","drop"].forEach((ev) => dz.addEventListener(ev, (e) => {
      e.preventDefault(); dz.classList.remove("is-drag");
    }));
    dz.addEventListener("drop", (e) => addFiles(Array.from(e.dataTransfer.files)));
  }

  function addFiles(fileList) {
    if (!fileList.length) return;
    const accountNames = state.config.accounts.map((a) => a.name);
    const lastAccount = state.files.length
      ? state.files[state.files.length - 1].account
      : accountNames[0];
    for (const file of fileList) {
      state.files.push({ file, id: `f${state.nextFileId++}`, account: lastAccount });
    }
    renderFileList();
  }

  function removeFile(id) {
    state.files = state.files.filter((f) => f.id !== id);
    renderFileList();
  }

  function renderFileList() {
    const wrap = $("file-list");
    const rows = $("file-rows");
    rows.innerHTML = "";
    if (state.files.length === 0) {
      hide(wrap);
      $("compile-btn").disabled = true;
      return;
    }
    show(wrap);
    $("compile-btn").disabled = false;

    const accountNames = state.config.accounts.map((a) => a.name);
    for (const f of state.files) {
      const row = document.createElement("div");
      row.className = "file-row";

      const name = document.createElement("div");
      name.className = "file-row-name";
      name.textContent = `📄 ${f.file.name}`;
      row.appendChild(name);

      const select = document.createElement("select");
      for (const acct of accountNames) {
        const opt = document.createElement("option");
        opt.value = acct; opt.textContent = acct;
        if (acct === f.account) opt.selected = true;
        select.appendChild(opt);
      }
      select.addEventListener("change", () => { f.account = select.value; });
      row.appendChild(select);

      const rm = document.createElement("button");
      rm.className = "remove-btn"; rm.type = "button"; rm.textContent = "×"; rm.title = "Remove file";
      rm.addEventListener("click", () => removeFile(f.id));
      row.appendChild(rm);

      rows.appendChild(row);
    }
  }

  // ---- Compile ----
  function wireCompile() { $("compile-btn").addEventListener("click", compile); }

  async function compile() {
    const btn = $("compile-btn");
    const errEl = $("compile-error");
    const statusEl = $("compile-status");
    hide(errEl);
    statusEl.textContent = "Parsing and categorising…";
    show(statusEl);
    btn.disabled = true;

    const form = new FormData();
    for (const f of state.files) {
      form.append("files", f.file, f.file.name);
      form.append("accounts", f.account);
    }
    try {
      state.session = await api.postForm("/api/outflows/compile", form);
      stampRowIndices();
      // Fresh session — clear any prior overrides.
      state.unsuppressedDup = new Set();
      state.reincludedExcl = new Set();
      hide($("restored-notice"));
      hide(statusEl);
      renderResults();
      saveSession();
    } catch (err) {
      hide(statusEl);
      errEl.textContent = String(err.message || err);
      show(errEl);
    } finally {
      btn.disabled = state.files.length === 0;
    }
  }

  // ---- Results ----
  function renderResults(preserveDateRange = false) {
    show($("results"));
    const s = state.session;

    // Mapping status caption
    const ms = $("mapping-status");
    if (s.mapping_status) {
      ms.textContent = s.mapping_status.rebuilt
        ? `Rebuilt mapping.json (${s.mapping_status.n_rules} rules)`
        : `mapping.json unchanged (${s.mapping_status.n_rules} rules)`;
      show(ms);
    } else hide(ms);

    renderWarnings(
      s.mapping_warnings,
      "mapping-warnings-panel", "mapping-warnings-summary", "mapping-warnings-list",
      (n) => `ℹ️ ${n} mapping-table note${n !== 1 ? "s" : ""}`
    );
    renderWarnings(
      s.history_warnings,
      "history-warnings-panel", "history-warnings-summary", "history-warnings-list",
      (n) => `⚠️ ${n} invalid categor${n === 1 ? "y" : "ies"} in transaction_history.xlsx`
    );

    const uaEl = $("unfamiliar-accounts");
    if (s.unfamiliar_accounts && s.unfamiliar_accounts.length) {
      uaEl.textContent =
        `Accounts in uploaded file(s) that aren't in accounts.yaml: ` +
        `${s.unfamiliar_accounts.join(", ")}. Transactions kept; ` +
        `these will appear in the Account filter as new options.`;
      show(uaEl);
    } else hide(uaEl);

    const dates = s.rows.map((r) => r.date).filter(Boolean).sort();
    if (dates.length === 0) {
      $("empty-range").textContent =
        "No spending transactions found after deduplication and dropping refunds/credits. " +
        "If you expected results, check that the right account format was selected for each file.";
      show($("empty-range"));
      return;
    }
    const dataFrom = dates[0];
    const dataTo = dates[dates.length - 1];
    $("date-from").min = dataFrom;
    $("date-from").max = dataTo;
    $("date-to").min = dataFrom;
    $("date-to").max = dataTo;

    // Keep the user's earlier range if we're restoring and it still fits.
    const keep = preserveDateRange && state.dateRange.from && state.dateRange.to
      && state.dateRange.from >= dataFrom && state.dateRange.to <= dataTo;
    if (!keep) {
      state.dateRange.from = dataFrom;
      state.dateRange.to = dataTo;
    }
    $("date-from").value = state.dateRange.from;
    $("date-to").value = state.dateRange.to;

    renderForDateRange();
  }

  function renderWarnings(warnings, panelId, summaryId, listId, titleFn) {
    const panel = $(panelId);
    if (!warnings || warnings.length === 0) { hide(panel); return; }
    show(panel);
    $(summaryId).textContent = titleFn(warnings.length);
    const list = $(listId);
    list.innerHTML = "";
    for (const w of warnings) {
      const li = document.createElement("li");
      li.textContent = w;
      list.appendChild(li);
    }
  }

  // ---- Date range filter ----
  function wireDateRange() {
    $("date-from").addEventListener("change", () => {
      state.dateRange.from = $("date-from").value;
      renderForDateRange();
      saveSession();
    });
    $("date-to").addEventListener("change", () => {
      state.dateRange.to = $("date-to").value;
      renderForDateRange();
      saveSession();
    });
  }

  function renderForDateRange() {
    if (!state.session) return;
    const { from, to } = state.dateRange;
    if (!from || !to || from > to) {
      $("empty-range").textContent = "Invalid date range.";
      show($("empty-range"));
      return;
    }
    const inRange = (r) => r.date >= from && r.date <= to;
    const rows = state.session.rows.filter(inRange);
    const dedup = rows.filter((r) => !r.duplicate);
    const excluded = new Set(state.config.excluded || []);
    // A row is hidden from the dashboard iff its category is excluded AND the
    // user hasn't re-included it individually via the ⟲ button.
    const isHidden = (r) => excluded.has(r.category) && !r._reincluded;
    const dashboardRows = excluded.size ? dedup.filter((r) => !isHidden(r)) : dedup;

    if (rows.length === 0) {
      $("empty-range").textContent = `No transactions in selected range (${from} to ${to}).`;
      show($("empty-range"));
    } else hide($("empty-range"));

    $("date-caption").textContent = `Showing ${formatDate(from)} → ${formatDate(to)}`;

    const total = dashboardRows.reduce((acc, r) => acc + r.amount, 0);
    const nTx = dashboardRows.length;
    const nUnmapped = dashboardRows.filter((r) => r.category === UNCAT).length;
    const pctUnmapped = nTx > 0 ? Math.round((nUnmapped / nTx) * 100) : 0;
    $("metric-total").textContent = fmtSGD.format(total);
    $("metric-count").textContent = nTx.toLocaleString();
    $("metric-unmapped").textContent = `${nUnmapped} (${pctUnmapped}%)`;
    $("metric-refunds").textContent = state.session.dropped_negatives;

    // Duplicates caption
    const dupCap = $("duplicates-caption");
    if (state.session.duplicates_count > 0) {
      dupCap.textContent =
        `Removed ${state.session.duplicates_count} duplicate row(s) ` +
        `across uploaded files (across all uploaded data).`;
      show(dupCap);
    } else hide(dupCap);

    // Exclusions caption — counts only rows that are still hidden after any
    // per-row re-inclusions.
    const excCap = $("exclusions-caption");
    if (excluded.size) {
      const hiddenRows = dedup.filter(isHidden);
      const excludedInData = [...new Set(hiddenRows.map((r) => r.category))].sort();
      if (excludedInData.length) {
        const nHidden = hiddenRows.length;
        excCap.textContent =
          `Hidden from dashboard: ${excludedInData.join(", ")} ` +
          `(${nHidden} transaction${nHidden !== 1 ? "s" : ""}). ` +
          `Downloads include all categories.`;
        show(excCap);
      } else hide(excCap);
    } else hide(excCap);

    state.scoped = { rows, dedup, dashboardRows };
    renderChart(dashboardRows);
    renderTable(dashboardRows);
    renderPanels(rows, dedup, dashboardRows, excluded);
  }

  // ---- Collapsible panels (unmapped / excluded / duplicates) ----
  function renderPanels(dated, dedup, dashboardRows, excluded) {
    const unmapped = dashboardRows.filter((r) => r.category === UNCAT);
    renderMiniPanel(
      "unmapped-panel", "unmapped-summary", "unmapped-intro", "unmapped-rows",
      `Unmapped transactions (${unmapped.length})`,
      unmapped.length
        ? "These descriptions did not match any pattern in your mapping table. " +
          "Use the download below to grow mapping.xlsx."
        : "Every transaction was mapped. Nice.",
      unmapped, ["date", "description", "amount", "account"],
    );

    const excludedRows = excluded.size
      ? dedup.filter((r) => excluded.has(r.category) && !r._reincluded)
      : [];
    let excludedIntro;
    if (!excluded.size) {
      excludedIntro = "No categories are flagged as excluded in categories.txt.";
    } else if (excludedRows.length === 0) {
      excludedIntro = `No transactions matched any excluded categories (${[...excluded].sort().join(", ")}).`;
    } else {
      excludedIntro =
        "These transactions are hidden from the dashboard view because " +
        "their category is flagged with ,exclude in categories.txt. " +
        "They are still included in the downloads. Click ⟲ to include a " +
        "row in the dashboard anyway.";
    }
    renderExcludedPanel(excludedRows, excludedIntro);

    const duplicates = dated.filter((r) => r.duplicate);
    renderDuplicatesPanel(duplicates);
  }

  function renderExcludedPanel(excludedRows, intro) {
    $("excluded-summary").textContent = `Excluded transactions (${excludedRows.length})`;
    $("excluded-intro").textContent = intro;

    const wrap = $("excluded-rows");
    wrap.innerHTML = "";
    if (excludedRows.length === 0) return;

    const table = document.createElement("table");
    table.className = "mini-table";
    table.innerHTML =
      "<thead><tr>" +
      "<th>Date</th><th>Description</th><th>Amount</th>" +
      "<th>Category</th><th>Account</th>" +
      "<th class=\"action-col\"></th>" +
      "</tr></thead>";
    const tbody = document.createElement("tbody");
    for (const r of excludedRows) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${escapeHtml(String(r.date ?? ""))}</td>` +
        `<td>${escapeHtml(String(r.description ?? ""))}</td>` +
        `<td class="amount">${fmtSGD.format(r.amount)}</td>` +
        `<td>${escapeHtml(String(r.category ?? ""))}</td>` +
        `<td>${escapeHtml(String(r.account ?? ""))}</td>`;
      const actionCell = document.createElement("td");
      actionCell.className = "action-col";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "unsuppress-btn";
      btn.title = "Include this row in the dashboard";
      btn.setAttribute("aria-label", "Include this excluded transaction in the dashboard");
      btn.textContent = "⟲";
      btn.addEventListener("click", () => reincludeExcluded(r._idx));
      actionCell.appendChild(btn);
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  function reincludeExcluded(idx) {
    if (typeof idx !== "number") return;
    const target = state.session.rows[idx];
    if (!target || target._reincluded) return;
    target._reincluded = true;
    state.reincludedExcl.add(idx);
    saveSession();
    renderForDateRange();
  }

  function renderDuplicatesPanel(duplicates) {
    $("duplicates-summary").textContent = `Duplicate transactions (${duplicates.length})`;
    $("duplicates-intro").textContent = duplicates.length
      ? "These rows were detected as duplicates of earlier rows on the same " +
        "date with the same amount and description, and excluded from " +
        "analysis. Click ⟲ to include a row in the dashboard anyway."
      : "No duplicate transactions in the selected range.";

    const wrap = $("duplicates-rows");
    wrap.innerHTML = "";
    if (duplicates.length === 0) return;

    const table = document.createElement("table");
    table.className = "mini-table";
    table.innerHTML =
      "<thead><tr>" +
      "<th>Date</th><th>Description</th><th>Amount</th><th>Account</th>" +
      "<th class=\"action-col\"></th>" +
      "</tr></thead>";
    const tbody = document.createElement("tbody");
    for (const r of duplicates) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${escapeHtml(String(r.date ?? ""))}</td>` +
        `<td>${escapeHtml(String(r.description ?? ""))}</td>` +
        `<td class="amount">${fmtSGD.format(r.amount)}</td>` +
        `<td>${escapeHtml(String(r.account ?? ""))}</td>`;
      const actionCell = document.createElement("td");
      actionCell.className = "action-col";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "unsuppress-btn";
      btn.title = "Include this row in the dashboard";
      btn.setAttribute("aria-label", "Include this duplicate in the dashboard");
      btn.textContent = "⟲";
      btn.addEventListener("click", () => unsuppressDuplicate(r._idx));
      actionCell.appendChild(btn);
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  function unsuppressDuplicate(idx) {
    if (typeof idx !== "number") return;
    const target = state.session.rows[idx];
    if (!target || !target.duplicate) return;
    target.duplicate = false;
    state.unsuppressedDup.add(idx);
    state.session.duplicates_count = Math.max(0, (state.session.duplicates_count || 0) - 1);
    saveSession();
    renderForDateRange();
  }

  function renderMiniPanel(panelId, summaryId, introId, rowsId, title, intro, rows, cols) {
    $(summaryId).textContent = title;
    $(introId).textContent = intro;
    const wrap = $(rowsId);
    if (rows.length === 0) { wrap.innerHTML = ""; return; }
    const headers = {
      date: "Date", description: "Description", amount: "Amount",
      category: "Category", account: "Account",
    };
    let html = '<table class="mini-table"><thead><tr>';
    for (const c of cols) html += `<th>${headers[c]}</th>`;
    html += "</tr></thead><tbody>";
    for (const r of rows) {
      html += "<tr>";
      for (const c of cols) {
        if (c === "amount") html += `<td class="amount">${fmtSGD.format(r[c])}</td>`;
        else html += `<td>${escapeHtml(String(r[c] ?? ""))}</td>`;
      }
      html += "</tr>";
    }
    html += "</tbody></table>";
    wrap.innerHTML = html;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  // ---- Chart (original earthy palette + Uncategorised rust) ----
  function renderChart(rows) {
    const totals = {};
    const counts = {};
    for (const r of rows) {
      totals[r.category] = (totals[r.category] || 0) + r.amount;
      counts[r.category] = (counts[r.category] || 0) + 1;
    }
    const categories = Object.keys(totals).sort((a, b) => totals[b] - totals[a]);
    const colors = [];
    let paletteIdx = 0;
    for (const cat of categories) {
      if (cat === UNCAT) colors.push(UNCAT_COLOUR);
      else { colors.push(PALETTE[paletteIdx % PALETTE.length]); paletteIdx++; }
    }
    const totalsK = categories.map((c) => totals[c] / 1000);

    const data = [{
      type: "bar",
      orientation: "h",
      x: totalsK,
      y: categories,
      marker: { color: colors },
      text: totalsK.map((v) => `$${v.toFixed(1)}K`),
      textposition: "outside",
      cliponaxis: false,
      customdata: categories.map((c) => [fmtSGD.format(totals[c]), counts[c]]),
      hovertemplate:
        "<b>%{y}</b><br>%{customdata[0]}<br>%{customdata[1]} transactions<extra></extra>",
    }];
    const layout = {
      height: Math.max(300, 40 * categories.length + 100),
      margin: { l: 160, r: 80, t: 20, b: 60 },
      xaxis: {
        title: "Total spend ($K)",
        tickprefix: "$",
        tickformat: ",.1f",
        gridcolor: "#EEE",
        showgrid: true,
      },
      yaxis: { autorange: "reversed", ticksuffix: "   " },
      plot_bgcolor: "white",
      paper_bgcolor: "white",
      font: { family: "Source Sans Pro, sans-serif" },
    };
    Plotly.react("chart", data, layout, { displayModeBar: false, responsive: true });
  }

  // ---- Table ----
  function wireTableFilters() {
    $("filter-category").addEventListener("change", () => {
      state.tableFilter.category = $("filter-category").value;
      if (state.scoped) renderTable(state.scoped.dashboardRows);
      saveSession();
    });
    $("filter-account").addEventListener("change", () => {
      state.tableFilter.account = $("filter-account").value;
      if (state.scoped) renderTable(state.scoped.dashboardRows);
      saveSession();
    });
  }

  function renderTable(rows) {
    refreshFilterOptions("filter-category", "category", rows);
    refreshFilterOptions("filter-account", "account", rows);

    const { category, account } = state.tableFilter;
    let view = rows;
    if (category !== "All") view = view.filter((r) => r.category === category);
    if (account !== "All") view = view.filter((r) => r.account === account);

    if (!state.table) {
      state.table = new Tabulator("#transactions-table", {
        data: view,
        layout: "fitColumns",
        placeholder: "No transactions match the current filters.",
        pagination: false,
        height: "500px",
        columns: [
          { title: "Date", field: "date", width: 110, sorter: "string" },
          { title: "Description", field: "description", minWidth: 200 },
          { title: "Amount", field: "amount", hozAlign: "right", width: 110, sorter: "number",
            formatter: (cell) => fmtSGD.format(cell.getValue()) },
          { title: "Category", field: "category", width: 160 },
          { title: "Account", field: "account", width: 160 },
          { title: "Matched pattern", field: "matched_pattern", minWidth: 140 },
        ],
      });
    } else {
      state.table.replaceData(view);
    }
  }

  function refreshFilterOptions(selectId, field, rows) {
    const select = $(selectId);
    const current = state.tableFilter[field];
    const values = [...new Set(rows.map((r) => r[field]))].sort();
    select.innerHTML = "";
    for (const v of ["All", ...values]) {
      const opt = document.createElement("option");
      opt.value = v; opt.textContent = v;
      if (v === current) opt.selected = true;
      select.appendChild(opt);
    }
    if (!["All", ...values].includes(current)) {
      state.tableFilter[field] = "All";
      select.value = "All";
    }
  }

  function formatDate(iso) {
    const [y, m, d] = iso.split("-");
    const monthNames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return `${d}-${monthNames[parseInt(m, 10) - 1]}-${y.slice(2)}`;
  }

  // ---- Downloads + history append ----
  function wireDownloads() {
    $("dl-categorised").addEventListener("click", () => downloadFile(
      `/api/outflows/download/categorised/${sessionId()}`,
      `spending_categorised_${nowStamp()}.xlsx`,
    ));
    $("dl-unmapped").addEventListener("click", () => downloadFile(
      `/api/outflows/download/unmapped/${sessionId()}`,
      `spending_unmapped_${nowStamp()}.xlsx`,
    ));
    $("dl-html").addEventListener("click", () => downloadFile(
      `/api/outflows/download/html/${sessionId()}`,
      `spending_snapshot_${state.dateRange.from}_${state.dateRange.to}.html`,
    ));
    $("append-history").addEventListener("click", appendHistory);
  }

  const sessionId = () => (state.session ? state.session.session_id : "");
  function nowStamp() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`;
  }

  async function downloadFile(endpoint, filename) {
    if (!state.session) return;
    clearDownloadBanners();
    try {
      await api.download(endpoint, {
        body: { start_date: state.dateRange.from, end_date: state.dateRange.to },
        fallbackName: filename,
      });
    } catch (err) {
      showDownloadError(String(err.message || err));
    }
  }

  async function appendHistory() {
    if (!state.session) return;
    clearDownloadBanners();
    try {
      const res = await api.postJson(`/api/outflows/history/append/${sessionId()}`, {
        start_date: state.dateRange.from,
        end_date: state.dateRange.to,
      });
      const { n_added, n_skipped } = res;
      let msg;
      if (n_added === 0 && n_skipped === 0) {
        msg = "Nothing to append — there are no unmapped rows in the selected range.";
      } else if (n_added === 0) {
        msg = `Nothing new to add — all ${n_skipped} unmapped row(s) are already in transaction_history.xlsx.`;
      } else {
        msg = `Appended ${n_added} new row(s) to transaction_history.xlsx.`;
        if (n_skipped) msg += ` Skipped ${n_skipped} duplicate(s).`;
        msg += " Opening the file for you to fill in categories.";
      }
      showDownloadStatus(msg);
      if (n_added > 0) {
        // Fire-and-forget: opening the file happens server-side via `open`
        // (macOS) / xdg-open / os.startfile. Errors surface as a banner but
        // don't block the append confirmation above.
        try { await api.postJson("/api/outflows/history/open", {}); }
        catch (err) { showDownloadError(String(err.message || err)); }
      }
    } catch (err) {
      showDownloadError(String(err.message || err));
    }
  }

  function clearDownloadBanners() {
    hide($("download-status"));
    hide($("download-error"));
  }
  function showDownloadStatus(msg) {
    $("download-status").textContent = msg;
    show($("download-status"));
  }
  function showDownloadError(msg) {
    $("download-error").textContent = msg;
    show($("download-error"));
  }

  boot().catch((err) => console.error("Outflows boot failed:", err));
})();
