// DB Edit — direct row-level editing of transactions.db. Loads every DB
// row once, filters/sorts client-side, and writes each E/× action to the
// server immediately. Deletes get an undo toast that restores the row
// verbatim (same tx_hash, same committed_at).
(() => {
  const state = {
    rows: [],        // /api/outflows/db/rows payload, server order (date desc)
    categories: [],  // valid categories for the E dropdown
    filter: { category: "All", account: "All", search: "", from: "", to: "" },
    sort: null,      // {key, dir} — null = keep server order
  };

  // Per-tab persistence of filters + sort, mirroring the Spending Review
  // table filters (the rows themselves always come fresh from the DB).
  const SS_KEY = "abicus.outflows.dbedit";

  const fmtSGD = new Intl.NumberFormat("en-SG", {
    style: "currency", currency: "SGD", minimumFractionDigits: 2,
  });

  const $ = (id) => document.getElementById(id);

  async function boot() {
    restoreUi();
    let resp;
    try {
      resp = await api.get("/api/outflows/db/rows");
    } catch {
      return; // api.js already toasted the error
    }
    state.rows = resp.rows || [];
    state.categories = resp.categories || [];
    wireFilters();
    refreshFilterOptions();
    render();
    loadHistory();
  }

  // Re-fetch the rows after a rollback — the DB changed underneath us.
  async function reloadRows() {
    let resp;
    try {
      resp = await api.get("/api/outflows/db/rows");
    } catch {
      return;
    }
    state.rows = resp.rows || [];
    refreshFilterOptions();
    render();
  }

  function saveUi() {
    try {
      sessionStorage.setItem(
        SS_KEY, JSON.stringify({ filter: state.filter, sort: state.sort }),
      );
    } catch { /* quota / privacy mode — silently ignore */ }
  }

  function restoreUi() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(SS_KEY));
      if (saved && saved.filter) state.filter = { ...state.filter, ...saved.filter };
      if (saved && saved.sort) state.sort = saved.sort;
    } catch { /* ignore */ }
  }

  // ---- Filters ----
  function wireFilters() {
    $("filter-search").value = state.filter.search;
    $("filter-from").value = state.filter.from;
    $("filter-to").value = state.filter.to;
    $("filter-category").addEventListener("change", (e) => {
      state.filter.category = e.target.value;
      saveUi(); render();
    });
    $("filter-account").addEventListener("change", (e) => {
      state.filter.account = e.target.value;
      saveUi(); render();
    });
    $("filter-search").addEventListener("input", (e) => {
      state.filter.search = e.target.value;
      saveUi(); render();
    });
    $("filter-from").addEventListener("change", (e) => {
      state.filter.from = e.target.value;
      saveUi(); render();
    });
    $("filter-to").addEventListener("change", (e) => {
      state.filter.to = e.target.value;
      saveUi(); render();
    });
  }

  // Dropdown options come from the values actually in the DB, "All" first,
  // preserving the current selection where it still exists.
  function refreshFilterOptions() {
    for (const [id, field] of [
      ["filter-category", "category"],
      ["filter-account", "account"],
    ]) {
      const select = $(id);
      const values = [...new Set(state.rows.map((r) => String(r[field] ?? "")))]
        .sort((a, b) => a.localeCompare(b));
      const current = state.filter[field];
      select.innerHTML = "";
      for (const v of ["All", ...values]) {
        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = v;
        select.appendChild(opt);
      }
      select.value = values.includes(current) || current === "All" ? current : "All";
      state.filter[field] = select.value;
    }
  }

  function filteredRows() {
    const f = state.filter;
    const needle = f.search.trim().toLowerCase();
    return state.rows.filter((r) =>
      (f.category === "All" || r.category === f.category) &&
      (f.account === "All" || r.account === f.account) &&
      (!needle || String(r.description ?? "").toLowerCase().includes(needle)) &&
      (!f.from || String(r.date) >= f.from) &&
      (!f.to || String(r.date) <= f.to)
    );
  }

  // ---- Sorting (same interaction as the Spending Review panels) ----
  function toggleSort(key) {
    const cur = state.sort;
    state.sort = cur && cur.key === key ? { key, dir: -cur.dir } : { key, dir: 1 };
    saveUi(); render();
  }

  function sortedRows(rows) {
    if (!state.sort) return rows;
    const { key, dir } = state.sort;
    const val = (r) =>
      key === "amount" ? (r.amount ?? 0) : String(r[key] ?? "").toLowerCase();
    return [...rows].sort((a, b) => {
      const va = val(a), vb = val(b);
      return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
    });
  }

  function tableHead() {
    const cols = [
      { key: "date", label: "Date" },
      { key: "description", label: "Description" },
      { key: "amount", label: "Amount" },
      { key: "category", label: "Category" },
      { key: "account", label: "Account" },
      { label: "", cls: "dbedit-actions-col" },
    ];
    const thead = document.createElement("thead");
    const tr = document.createElement("tr");
    for (const c of cols) {
      const th = document.createElement("th");
      if (c.cls) th.className = c.cls;
      th.textContent = c.label;
      if (c.key) {
        th.classList.add("sortable");
        th.title = `Sort by ${c.label}`;
        if (state.sort && state.sort.key === c.key) {
          th.textContent = `${c.label} ${state.sort.dir === 1 ? "▲" : "▼"}`;
        }
        th.addEventListener("click", () => toggleSort(c.key));
      }
      tr.appendChild(th);
    }
    thead.appendChild(tr);
    return thead;
  }

  // ---- Render ----
  function render() {
    const rows = filteredRows();
    const total = rows.reduce((sum, r) => sum + (r.amount ?? 0), 0);
    const filtered = rows.length !== state.rows.length;
    $("db-summary").textContent =
      `${rows.length} transaction${rows.length !== 1 ? "s" : ""}` +
      (filtered ? ` of ${state.rows.length} in the database` : "") +
      ` · ${fmtSGD.format(total)}`;
    $("db-empty").classList.toggle("hidden", state.rows.length > 0);

    const wrap = $("db-rows");
    wrap.innerHTML = "";
    if (rows.length === 0) return;

    const table = document.createElement("table");
    table.className = "mini-table";
    table.appendChild(tableHead());
    const tbody = document.createElement("tbody");
    for (const r of sortedRows(rows)) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${escapeHtml(String(r.date ?? ""))}</td>` +
        `<td>${escapeHtml(String(r.description ?? ""))}</td>` +
        `<td class="amount">${fmtSGD.format(r.amount)}</td>` +
        `<td>${escapeHtml(String(r.category ?? ""))}</td>` +
        `<td>${escapeHtml(String(r.account ?? ""))}</td>`;

      const actionCell = document.createElement("td");
      actionCell.className = "dbedit-actions-col";
      const actions = document.createElement("span");
      actions.className = "dbedit-actions";

      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "unsuppress-btn editcat-btn";
      editBtn.title = "Edit this row's category";
      editBtn.setAttribute("aria-label", "Edit this row's category");
      editBtn.textContent = "E";
      editBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openCategoryMenu(
          editBtn.getBoundingClientRect(),
          (cat) => updateCategory(r, cat),
        );
      });
      actions.appendChild(editBtn);

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "unsuppress-btn row-excl-btn";
      delBtn.title = "Delete this row from the database";
      delBtn.setAttribute("aria-label", "Delete this row from the database");
      delBtn.textContent = "×";
      delBtn.addEventListener("click", () => deleteRow(r));
      actions.appendChild(delBtn);

      actionCell.appendChild(actions);
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  // ---- Actions ----
  async function updateCategory(row, category) {
    if (category === row.category) return;
    try {
      await api.postJson("/api/outflows/db/update-category", {
        tx_hash: row.tx_hash, category,
      });
    } catch {
      return; // api.js already toasted the error
    }
    const old = row.category;
    row.category = category;
    toast(`"${row.description}" recategorised ${old} → ${category}.`, "info");
    refreshFilterOptions();
    render();
    loadHistory();
  }

  async function deleteRow(row) {
    let resp;
    try {
      resp = await api.postJson("/api/outflows/db/delete-row", {
        tx_hash: row.tx_hash,
      });
    } catch {
      return; // api.js already toasted the error
    }
    const idx = state.rows.indexOf(row);
    if (idx !== -1) state.rows.splice(idx, 1);
    refreshFilterOptions();
    render();
    loadHistory();
    showUndoToast(
      `Deleted "${row.description}" (${fmtSGD.format(row.amount)}) from the database.`,
      () => restoreRow(resp.deleted, idx),
    );
  }

  async function restoreRow(row, idx) {
    try {
      await api.postJson("/api/outflows/db/restore-row", { row });
    } catch {
      return; // api.js already toasted the error
    }
    state.rows.splice(Math.min(idx < 0 ? 0 : idx, state.rows.length), 0, row);
    toast(`Restored "${row.description}".`, "info");
    refreshFilterOptions();
    render();
    loadHistory();
  }

  // Delete toast with an inline Undo button; longer TTL than the shared
  // toast() so there's comfortable time to change your mind.
  function showUndoToast(message, onUndo) {
    const root = $("toasts");
    if (!root) return;
    const el = document.createElement("div");
    el.className = "toast toast--info";
    el.appendChild(document.createTextNode(message));
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "undo-btn";
    btn.textContent = "Undo";
    btn.addEventListener("click", () => {
      el.remove();
      onUndo();
    });
    el.appendChild(btn);
    root.appendChild(el);
    setTimeout(() => {
      el.style.transition = "opacity 200ms";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 220);
    }, 8000);
  }

  // ---- Category dropdown ----
  // Same behaviour as the +H menu on Spending Review (outflows.js):
  // appended to <body> because the table wrapper clips overflow, opens on
  // whichever side of the anchor has more room, closes on outside click /
  // Escape / page scroll but not on scrolls inside the menu.
  let openMenu = null;

  function closeCategoryMenu() {
    if (!openMenu) return;
    openMenu.remove();
    openMenu = null;
    document.removeEventListener("click", closeCategoryMenu);
    document.removeEventListener("keydown", onMenuKeydown);
    window.removeEventListener("scroll", onMenuScroll, true);
  }

  function onMenuKeydown(e) {
    if (e.key === "Escape") closeCategoryMenu();
  }

  function onMenuScroll(e) {
    if (openMenu && openMenu.contains(e.target)) return;
    closeCategoryMenu();
  }

  function openCategoryMenu(rect, onPick) {
    closeCategoryMenu();
    const cats = state.categories;
    if (!cats.length) {
      toast("No categories found in categories.txt.", "error");
      return;
    }

    const menu = document.createElement("div");
    menu.className = "cat-menu";
    menu.setAttribute("role", "menu");
    for (const cat of cats) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "cat-menu-item";
      item.setAttribute("role", "menuitem");
      item.textContent = cat;
      item.addEventListener("click", (e) => {
        e.stopPropagation();
        closeCategoryMenu();
        onPick(cat);
      });
      menu.appendChild(item);
    }
    menu.addEventListener("click", (e) => e.stopPropagation());

    document.body.appendChild(menu);
    const spaceBelow = window.innerHeight - rect.bottom - 12;
    const spaceAbove = rect.top - 12;
    const openBelow = spaceBelow >= Math.min(240, spaceAbove) || spaceBelow >= spaceAbove;
    menu.style.maxHeight = `${Math.max(120, openBelow ? spaceBelow : spaceAbove)}px`;
    const menuRect = menu.getBoundingClientRect();
    const top = openBelow
      ? rect.bottom + 4
      : Math.max(8, rect.top - menuRect.height - 4);
    let left = rect.right - menuRect.width;
    if (left < 8) left = 8;
    menu.style.top = `${top}px`;
    menu.style.left = `${left}px`;

    openMenu = menu;
    // Deferred so the click that opened the menu doesn't immediately close it.
    setTimeout(() => {
      document.addEventListener("click", closeCategoryMenu);
      document.addEventListener("keydown", onMenuKeydown);
      window.addEventListener("scroll", onMenuScroll, true);
    }, 0);
  }

  // ---- History panel (V3 Feature A) ----
  // Commit list newest-first; View changes expands an inline diff of the
  // rows that write touched; Roll back restores the DB to that commit's
  // state behind an explicit confirm (the server snapshots first, and the
  // rollback lands as a new `restore → <sha8>` commit).

  function fmtCommitDate(iso) {
    return String(iso || "").slice(0, 19).replace("T", " ");
  }

  function summaryText(s) {
    const parts = [];
    if (s.added) parts.push(`+${s.added} added`);
    if (s.changed) parts.push(`${s.changed} changed`);
    if (s.removed) parts.push(`−${s.removed} removed`);
    return parts.join(" · ") || "no row changes";
  }

  async function loadHistory() {
    let resp;
    try {
      resp = await api.get("/api/outflows/db/history");
    } catch {
      return; // api.js already toasted the error
    }
    renderHistory(resp.commits || []);
  }

  function renderHistory(commits) {
    $("hist-empty").classList.toggle("hidden", commits.length > 0);
    const wrap = $("hist-rows");
    wrap.innerHTML = "";
    if (!commits.length) return;

    const table = document.createElement("table");
    table.className = "mini-table";
    const thead = document.createElement("thead");
    thead.innerHTML =
      "<tr><th>Commit</th><th>Date</th><th>Operation</th>" +
      "<th>Changes</th><th class='dbedit-actions-col'></th></tr>";
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    commits.forEach((commit, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td><code>${escapeHtml(commit.sha8)}</code></td>` +
        `<td>${escapeHtml(fmtCommitDate(commit.date))}</td>` +
        `<td>${escapeHtml(commit.label)}</td>` +
        `<td>${escapeHtml(summaryText(commit.summary || {}))}</td>`;

      const actionCell = document.createElement("td");
      actionCell.className = "dbedit-actions-col";
      const actions = document.createElement("span");
      actions.className = "dbedit-actions";

      const viewBtn = document.createElement("button");
      viewBtn.type = "button";
      viewBtn.className = "hist-btn";
      viewBtn.textContent = "View changes";
      viewBtn.addEventListener("click", () => toggleDiff(commit, tr, viewBtn));
      actions.appendChild(viewBtn);

      // The newest commit IS the current state — say so instead of
      // offering a no-op Roll back.
      if (i > 0) {
        const rollBtn = document.createElement("button");
        rollBtn.type = "button";
        rollBtn.className = "hist-btn hist-btn-danger";
        rollBtn.textContent = "Roll back";
        rollBtn.addEventListener("click", () => rollBack(commit));
        actions.appendChild(rollBtn);
      } else {
        const tag = document.createElement("span");
        tag.className = "hist-current";
        tag.textContent = "current";
        tag.title = "This commit is the database's current state.";
        actions.appendChild(tag);
      }

      actionCell.appendChild(actions);
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  function diffLine(prefix, r) {
    return `${prefix} ${r.date}  ${r.description}  ${fmtSGD.format(r.amount)}` +
      `  [${r.category}]  ${r.account}`;
  }

  async function toggleDiff(commit, tr, btn) {
    const existing = tr.nextElementSibling;
    if (existing && existing.classList.contains("hist-diff-row")) {
      existing.remove();
      btn.textContent = "View changes";
      return;
    }
    let d;
    try {
      d = await api.get(`/api/outflows/db/history/diff/${commit.sha8}`);
    } catch {
      return; // api.js already toasted the error
    }
    const lines = [
      ...(d.added || []).map((r) => diffLine("+", r)),
      ...(d.removed || []).map((r) => diffLine("−", r)),
      ...(d.changed || []).flatMap((c) => [
        diffLine("~", c.before), "  → " + diffLine("", c.after).trim(),
      ]),
    ];
    const diffTr = document.createElement("tr");
    diffTr.className = "hist-diff-row";
    const td = document.createElement("td");
    td.colSpan = 5;
    const pre = document.createElement("pre");
    pre.className = "hist-diff";
    pre.textContent = lines.length ? lines.join("\n") : "No row changes.";
    td.appendChild(pre);
    diffTr.appendChild(td);
    tr.after(diffTr);
    btn.textContent = "Hide changes";
  }

  async function rollBack(commit) {
    const ok = window.confirm(
      "Roll the database back to this state?\n\n" +
      `${commit.sha8} · ${fmtCommitDate(commit.date)}\n${commit.label}\n\n` +
      "The current state is snapshotted first, so this is reversible."
    );
    if (!ok) return;
    let resp;
    try {
      resp = await api.postJson("/api/outflows/db/history/restore", {
        ref: commit.sha8,
      });
    } catch {
      return; // api.js already toasted the error
    }
    toast(
      `Rolled back to ${resp.restored_to} — ${resp.rows} rows restored.`,
      "info",
    );
    await reloadRows();
    loadHistory();
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  boot();
})();
