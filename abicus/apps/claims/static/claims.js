(() => {
  const state = {
    claims: [],
    claimants: [],
    institutions: [],
    showArchived: false,
    sortKey: "date_incurred",
    sortDir: -1,
  };

  const ADD_NEW = "__add_new__";

  // ---------- formatting ----------

  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const money = (n) =>
    Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtDate = (iso) => {
    if (!iso) return "";
    const [y, m, d] = iso.split("-");
    return `${d}-${MONTHS[Number(m) - 1]}-${y.slice(2)}`;
  };
  const sgd = (n) => "SGD " + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  // ---------- status mapping ----------

  function statusClass(s) {
    if (s === "Excluded") return "st-excluded";
    if (s.startsWith("Check")) return "st-warn";
    if (s === "Complete") return "st-done";
    if (s === "Claim submitted") return "st-claim";
    if (s === "Ready to claim") return "st-ready";
    return "st-await";
  }
  function rowClass(s) {
    if (s === "Excluded") return "row-excluded";
    if (s.startsWith("Check")) return "row-warn";
    if (s === "Complete") return "row-done";
    if (s === "Claim submitted") return "row-claim";
    if (s === "Ready to claim") return "row-ready";
    return "row-await";
  }

  function daysAged(r) {
    if (r.status === "Complete" || r.status === "Excluded") return null;
    const incurred = new Date(r.date_incurred + "T00:00:00");
    const today = new Date(); today.setHours(0, 0, 0, 0);
    return Math.max(0, Math.floor((today - incurred) / 86400000));
  }

  // ---------- boot ----------

  async function boot() {
    document.getElementById("filter-from").value = "2026-01-01";
    document.getElementById("filter-to").value = new Date().toISOString().slice(0, 10);

    const cfg = await api.get("/api/claims/config");
    state.claimants = cfg.claimants || [];
    const cfFilter = document.getElementById("filter-claimant");
    const cfForm = document.getElementById("f_claimant");
    state.claimants.forEach((c) => {
      cfFilter.insertAdjacentHTML("beforeend", `<option>${esc(c)}</option>`);
      cfForm.insertAdjacentHTML("beforeend", `<option>${esc(c)}</option>`);
    });
    await loadInstitutions();
    wireControls();
    wireModal();
    await reload();
  }

  async function loadInstitutions() {
    state.institutions = await api.get("/api/claims/institutions");
    renderInstitutionSelect();
  }

  function renderInstitutionSelect(selected) {
    const sel = document.getElementById("f_institution");
    const opts = [
      `<option value="" disabled ${selected ? "" : "selected"}>— pick one —</option>`,
    ];
    state.institutions.forEach((i) => {
      const v = i.replace(/"/g, "&quot;");
      opts.push(`<option value="${v}" ${i === selected ? "selected" : ""}>${esc(i)}</option>`);
    });
    opts.push('<option disabled>──────────</option>');
    opts.push(`<option value="${ADD_NEW}">+ Add new institution…</option>`);
    sel.innerHTML = opts.join("");
  }

  async function handleInstitutionChange() {
    const sel = document.getElementById("f_institution");
    if (sel.value !== ADD_NEW) return;
    const name = (prompt("New institution name:") || "").trim();
    if (!name) { renderInstitutionSelect(); return; }
    try {
      const fresh = await api.postJson("/api/claims/institutions", { name });
      state.institutions = fresh;
      const stored = state.institutions.find((x) => x.toLowerCase() === name.toLowerCase()) || name;
      renderInstitutionSelect(stored);
      document.getElementById("form-err").textContent = "";
    } catch (err) {
      document.getElementById("form-err").textContent = "Could not add institution.";
      renderInstitutionSelect();
    }
  }

  async function reload() {
    const url = state.showArchived ? "/api/claims/claims/archived" : "/api/claims/claims";
    state.claims = await api.get(url);
    state.claims.forEach((r) => { r.shortfall = (r.amount || 0) - (r.amount_rebated || 0); });
    state.sortKey = "date_incurred"; state.sortDir = -1;
    render();
  }

  // ---------- filter + sort + render ----------

  function sortBy(k) {
    if (state.sortKey === k) state.sortDir *= -1;
    else { state.sortKey = k; state.sortDir = 1; }
    render();
  }

  function currentFilterValues() {
    return {
      q: document.getElementById("filter-search").value.toLowerCase().trim(),
      fcl: document.getElementById("filter-claimant").value,
      fst: document.getElementById("filter-status").value,
      fop: document.getElementById("filter-open").value,
      dFrom: document.getElementById("filter-from").value,
      dTo: document.getElementById("filter-to").value,
    };
  }

  function filterClaims(claims, f) {
    const inWindow = claims.filter((r) => {
      if (f.dFrom && r.date_incurred < f.dFrom) return false;
      if (f.dTo && r.date_incurred > f.dTo) return false;
      return true;
    });
    const rows = inWindow.filter((r) => {
      if (f.fcl && r.claimant !== f.fcl) return false;
      if (f.fst && r.status !== f.fst) return false;
      if (f.fop === "open" && r.status === "Complete") return false;
      if (f.q && !(r.institution.toLowerCase().includes(f.q) || (r.notes || "").toLowerCase().includes(f.q))) return false;
      return true;
    });
    return { inWindow, rows };
  }

  function render() {
    const { inWindow, rows: rowsUnsorted } = filterClaims(state.claims, currentFilterValues());
    let rows = rowsUnsorted;

    const getSort = (r, k) => (k === "days_aged" ? (daysAged(r) ?? -Infinity) : r[k]);
    rows.sort((a, b) => {
      let x = getSort(a, state.sortKey);
      let y = getSort(b, state.sortKey);
      if (typeof x === "string") { x = (x || "").toLowerCase(); y = (y || "").toLowerCase(); }
      return x < y ? -state.sortDir : x > y ? state.sortDir : 0;
    });

    // table
    document.getElementById("claims-tbody").innerHTML = rows.map((r) => {
      const aged = daysAged(r);
      return `
        <tr class="${rowClass(r.status)}">
          <td style="white-space:nowrap">${fmtDate(r.date_incurred)}</td>
          <td class="center">${aged ?? ""}</td>
          <td>${esc(r.claimant)}</td>
          <td>${esc(r.institution)}</td>
          <td class="num">${money(r.amount)}</td>
          <td class="center"><span class="flag ${r.invoice_received ? "" : "off"}" data-toggle="invoice_received" data-id="${r.id}" title="Invoice received">●</span></td>
          <td class="center"><span class="flag ${r.claimed ? "" : "off"}" data-toggle="claimed" data-id="${r.id}" title="Claimed">●</span></td>
          <td class="center"><span class="flag ${r.rebated ? "" : "off"}" data-toggle="rebated" data-id="${r.id}" title="Rebated">●</span></td>
          <td class="center"><span class="flag ${r.excluded ? "" : "off"}" data-toggle="excluded" data-id="${r.id}" title="Excluded">●</span></td>
          <td class="num">${r.rebated ? money(r.amount_rebated) : "—"}</td>
          <td class="num">${money(r.shortfall)}</td>
          <td><span class="pill ${statusClass(r.status)}">${r.status}</span></td>
          <td>${
            r.invoice_file
              ? `<a class="linkbtn" href="/api/claims/claims/${r.id}/invoice" target="_blank">View ↗</a>`
              : state.showArchived
                ? `<span class="nofile">none</span>`
                : `<button class="file-add" data-action="upload-invoice" data-id="${r.id}" title="Add invoice">+ Add</button>`
          }</td>
          <td style="white-space:nowrap">
            ${state.showArchived
              ? `<span class="rowact" data-action="restore" data-id="${r.id}">Restore</span>
                 <span class="rowact danger" data-action="delete" data-id="${r.id}">Delete</span>`
              : `<span class="rowact" data-action="edit" data-id="${r.id}">Edit</span>
                 <span class="rowact" data-action="archive" data-id="${r.id}">Archive</span>
                 <span class="rowact danger" data-action="delete" data-id="${r.id}">Delete</span>`}
          </td>
        </tr>`;
    }).join("");

    document.getElementById("empty").classList.toggle("hidden", rows.length > 0);
    document.getElementById("row-count").textContent = `${rows.length} of ${state.claims.length}`;

    renderSortMarks();
    renderSummary(inWindow);
  }

  function renderSortMarks() {
    document.querySelectorAll(".claims-table thead th[data-sort]").forEach((th) => {
      const mark = th.querySelector(".sort-mark");
      if (!mark) return;
      mark.textContent = th.dataset.sort === state.sortKey ? (state.sortDir > 0 ? "▲" : "▼") : "";
    });
  }

  function renderSummary(scope) {
    const incurred = scope.reduce((s, r) => s + (r.amount || 0), 0);
    const rebate = scope.reduce((s, r) => s + (r.amount_rebated || 0), 0);
    const shortfall = incurred - rebate;
    document.getElementById("summary").innerHTML = `
      <div class="stat"><div class="n">${sgd(incurred)}</div><div class="l">Total amount incurred</div></div>
      <div class="stat"><div class="n">${sgd(rebate)}</div><div class="l">Total rebate</div></div>
      <div class="stat"><div class="n">${sgd(shortfall)}</div><div class="l">Shortfall</div></div>`;
  }

  // ---------- controls ----------

  function wireControls() {
    ["filter-from","filter-to","filter-claimant","filter-status","filter-open"].forEach((id) => {
      document.getElementById(id).addEventListener("change", render);
    });
    document.getElementById("filter-search").addEventListener("input", render);

    document.querySelectorAll(".claims-table thead th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => sortBy(th.dataset.sort));
    });

    document.getElementById("toggle-archive-btn").addEventListener("click", async () => {
      state.showArchived = !state.showArchived;
      const btn = document.getElementById("toggle-archive-btn");
      btn.textContent = state.showArchived ? "Show active" : "Show archived";
      btn.classList.toggle("primary", state.showArchived);
      document.getElementById("arch-banner").classList.toggle("hidden", !state.showArchived);
      await reload();
    });

    document.getElementById("new-claim-btn").addEventListener("click", openNew);

    document.getElementById("export-html-btn").addEventListener("click", exportDashboardHtml);

    // table delegation: toggle dots + row actions + invoice + other-docs
    document.getElementById("claims-tbody").addEventListener("click", onRowClick);
  }

  async function onRowClick(e) {
    const flag = e.target.closest(".flag");
    if (flag) {
      const fd = new FormData();
      fd.set("field", flag.dataset.toggle);
      await api.postForm(`/api/claims/claims/${flag.dataset.id}/toggle`, fd);
      reload();
      return;
    }
    const actEl = e.target.closest("[data-action]");
    if (!actEl) return;
    const id = Number(actEl.dataset.id);
    const claim = state.claims.find((c) => c.id === id);
    switch (actEl.dataset.action) {
      case "edit": openEdit(claim); break;
      case "archive":
        if (!confirm("Archive this entry? The invoice file stays on disk.")) return;
        await api.del(`/api/claims/claims/${id}`);
        reload();
        break;
      case "restore":
        await api.postJson(`/api/claims/claims/${id}/restore`, {});
        reload();
        break;
      case "delete": {
        const desc = claim ? `${claim.claimant} · ${claim.institution} · ${fmtDate(claim.date_incurred)}` : `entry ${id}`;
        const hasFile = claim && claim.invoice_file;
        const msg = `Permanently delete this entry?\n\n  ${desc}\n\n`
          + (hasFile ? `The invoice file (${claim.invoice_file}) will also be deleted from disk.\n\n` : "")
          + `This cannot be undone.`;
        if (!confirm(msg)) return;
        await api.del(`/api/claims/claims/${id}/permanent`);
        reload();
        break;
      }
      case "upload-invoice": uploadInvoiceFor(id); break;
    }
  }

  function uploadInvoiceFor(claimId) {
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = ".pdf,.png,.jpg,.jpeg,.heic,.webp";
    inp.onchange = async () => {
      if (!inp.files || !inp.files[0]) return;
      const fd = new FormData();
      fd.append("file", inp.files[0]);
      await api.postForm(`/api/claims/claims/${claimId}/invoice`, fd);
      reload();
    };
    inp.click();
  }

  // ---------- modal ----------

  function wireModal() {
    document.getElementById("f_rebated").addEventListener("change", (e) => {
      document.getElementById("rebated-wrap").classList.toggle("hidden", !e.target.checked);
    });
    document.getElementById("f_institution").addEventListener("change", handleInstitutionChange);
    document.getElementById("modal-cancel-btn").addEventListener("click", closeModal);
    document.getElementById("modal-save-btn").addEventListener("click", save);
    document.getElementById("claim-overlay").addEventListener("click", (e) => {
      if (e.target.id === "claim-overlay") closeModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeModal();
    });

    document.getElementById("upload-other-btn").addEventListener("click", async () => {
      const id = document.getElementById("f_id").value;
      if (!id) { toast("Save the entry first, then attach docs", "warn"); return; }
      const input = document.getElementById("f_other_doc");
      if (!input.files || !input.files[0]) { toast("Choose a file first", "warn"); return; }
      const fd = new FormData();
      fd.append("file", input.files[0]);
      const rec = await api.postForm(`/api/claims/claims/${id}/files`, fd);
      input.value = "";
      // re-fetch claim row to refresh other_files list
      const fresh = await api.get(`/api/claims/claims`);
      const claim = fresh.find((c) => c.id === Number(id));
      if (claim) renderOtherDocsInModal(claim);
      state.claims = state.claims.map((c) => (c.id === Number(id) ? { ...c, other_files: (c.other_files || []).concat(rec) } : c));
      toast("Document attached", "ok");
    });
  }

  function openNew() {
    document.getElementById("modal-title").textContent = "New entry";
    document.getElementById("f_id").value = "";
    document.getElementById("f_claimant").value = state.claimants[0] || "";
    document.getElementById("f_date").value = new Date().toISOString().slice(0, 10);
    renderInstitutionSelect();
    document.getElementById("f_amount").value = "";
    document.getElementById("f_currency").value = "SGD";
    ["f_received","f_claimed","f_rebated","f_excluded"].forEach((id) => { document.getElementById(id).checked = false; });
    document.getElementById("f_amount_rebated").value = "";
    document.getElementById("rebated-wrap").classList.add("hidden");
    document.getElementById("f_invoice").value = "";
    document.getElementById("f_notes").value = "";
    document.getElementById("form-err").textContent = "";
    document.getElementById("file-hint").textContent = "";
    document.getElementById("other-docs-section").style.display = "none";
    document.getElementById("claim-overlay").classList.remove("hidden");
  }

  function openEdit(claim) {
    document.getElementById("modal-title").textContent = "Edit entry";
    document.getElementById("f_id").value = String(claim.id);
    document.getElementById("f_claimant").value = claim.claimant;
    document.getElementById("f_date").value = claim.date_incurred;
    renderInstitutionSelect(claim.institution);
    document.getElementById("f_amount").value = claim.amount;
    document.getElementById("f_currency").value = claim.currency;
    document.getElementById("f_received").checked = !!claim.invoice_received;
    document.getElementById("f_claimed").checked = !!claim.claimed;
    document.getElementById("f_rebated").checked = !!claim.rebated;
    document.getElementById("f_excluded").checked = !!claim.excluded;
    document.getElementById("f_amount_rebated").value = claim.amount_rebated || "";
    document.getElementById("rebated-wrap").classList.toggle("hidden", !claim.rebated);
    document.getElementById("f_invoice").value = "";
    document.getElementById("file-hint").textContent = claim.invoice_file
      ? `Current: ${claim.invoice_file} — choose a file only to replace it.` : "";
    document.getElementById("f_notes").value = claim.notes || "";
    document.getElementById("form-err").textContent = "";
    document.getElementById("other-docs-section").style.display = "block";
    renderOtherDocsInModal(claim);
    document.getElementById("claim-overlay").classList.remove("hidden");
  }

  function renderOtherDocsInModal(claim) {
    const list = document.getElementById("other-docs-list");
    list.innerHTML = (claim.other_files || []).map((f) => `
      <li>
        <a class="linkbtn" href="/api/claims/claims/${claim.id}/files/${f.id}" target="_blank">${esc(f.original_name)}</a>
        <span class="rowact danger" data-fid="${f.id}">Delete</span>
      </li>
    `).join("") || `<li class="nofile">No documents attached.</li>`;
    list.querySelectorAll("[data-fid]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this document?")) return;
        await api.del(`/api/claims/claims/${claim.id}/files/${btn.dataset.fid}`);
        claim.other_files = (claim.other_files || []).filter((f) => String(f.id) !== btn.dataset.fid);
        renderOtherDocsInModal(claim);
        reload();
      });
    });
  }

  function closeModal() {
    document.getElementById("claim-overlay").classList.add("hidden");
  }

  async function save() {
    const id = document.getElementById("f_id").value;
    const institution = document.getElementById("f_institution").value;
    if (!institution || institution === ADD_NEW) {
      document.getElementById("form-err").textContent = "Please pick an institution.";
      return;
    }
    const fd = new FormData();
    fd.append("claimant", document.getElementById("f_claimant").value);
    fd.append("institution", institution);
    fd.append("date_incurred", document.getElementById("f_date").value);
    fd.append("amount", document.getElementById("f_amount").value || "0");
    fd.append("currency", document.getElementById("f_currency").value.trim() || "SGD");
    fd.append("invoice_received", document.getElementById("f_received").checked ? "true" : "false");
    fd.append("claimed", document.getElementById("f_claimed").checked ? "true" : "false");
    fd.append("rebated", document.getElementById("f_rebated").checked ? "true" : "false");
    fd.append("excluded", document.getElementById("f_excluded").checked ? "true" : "false");
    fd.append("amount_rebated", document.getElementById("f_amount_rebated").value || "0");
    fd.append("notes", document.getElementById("f_notes").value);
    const file = document.getElementById("f_invoice").files[0];
    if (file) fd.append("invoice", file);

    const saveBtn = document.getElementById("modal-save-btn");
    saveBtn.disabled = true;
    try {
      if (id) await api.putForm(`/api/claims/claims/${id}`, fd);
      else await api.postForm(`/api/claims/claims`, fd);
      closeModal();
      await reload();
    } finally {
      saveBtn.disabled = false;
    }
  }

  // ---------- Export HTML (self-contained interactive dashboard snapshot) ----------

  function exportDashboardHtml() {
    // Seed the exported file with the currently-visible row set. The user can
    // narrow further from within the exported HTML, but archived rows and rows
    // outside the on-screen filter are baked out at export time.
    const initFilters = currentFilterValues();
    const { rows } = filterClaims(state.claims, initFilters);

    if (!rows.length) {
      alert("Nothing to export — the current filter has no rows.");
      return;
    }

    // Distinct claimants and statuses from the exported row set so the
    // in-file dropdowns only offer what's actually present.
    const uniq = (arr) => [...new Set(arr.filter(Boolean))].sort();
    const claimants = uniq(rows.map((r) => r.claimant));
    const statuses = uniq(rows.map((r) => r.status));
    const today = new Date().toISOString().slice(0, 10);
    const generatedAt = new Date().toLocaleString();

    // Payload embedded in the exported file. Escape </ and & to prevent any
    // stray description or notes text from breaking out of the <script> tag.
    const payload = {
      rows: rows.map((r) => ({
        id: r.id,
        date_incurred: r.date_incurred,
        claimant: r.claimant || "",
        institution: r.institution || "",
        amount: Number(r.amount || 0),
        currency: r.currency || "",
        amount_rebated: Number(r.amount_rebated || 0),
        shortfall: Number(r.shortfall || 0),
        status: r.status || "",
        invoice_received: !!r.invoice_received,
        claimed: !!r.claimed,
        rebated: !!r.rebated,
        excluded: !!r.excluded,
      })),
      claimants,
      statuses,
      initial: {
        q: initFilters.q,
        fcl: initFilters.fcl,
        fst: initFilters.fst,
        dFrom: initFilters.dFrom,
        dTo: initFilters.dTo,
      },
      generatedAt,
    };
    const dataJson = JSON.stringify(payload)
      .replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");

    const html = buildClaimsSnapshotHtml(dataJson, generatedAt);
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `mediclaim-${today}.html`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  }

  // Self-contained snapshot HTML. Keeps to inline CSS + a small script so it
  // works offline. Runtime uses vanilla JS — no external libs.
  function buildClaimsSnapshotHtml(dataJson, generatedAt) {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Claims Snapshot — ${generatedAt}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Source+Sans+Pro:wght@300;400;600&display=swap" rel="stylesheet">
<style>
  body { font-family: 'Source Sans Pro', sans-serif; color: #3D3229; background: #FAF7F2;
         margin: 0; padding: 2rem; max-width: 1200px; margin-left: auto; margin-right: auto; }
  h1 { font-family: 'Playfair Display', serif; color: #556B2F; font-weight: 600; font-size: 2rem;
       margin: 0 0 0.25rem 0; letter-spacing: -0.5px; }
  .subtitle { color: #6B5D4F; margin-bottom: 1.5rem; }
  .summary { display: flex; gap: 2rem; flex-wrap: wrap; margin: 1rem 0 1.5rem 0;
             padding: 1rem 1.2rem; background: white; border: 1px solid #DED6C4; border-radius: 6px; }
  .stat .n { font-family: 'Playfair Display', serif; font-weight: 700; font-size: 1.6rem; color: #3D3229; }
  .stat .l { color: #6B5D4F; font-size: 0.9rem; }
  .privacy { background: #FFF4E0; border-left: 3px solid #C77B4F; padding: 0.6rem 0.9rem;
             margin: 1rem 0; font-size: 0.9rem; color: #6B5D4F; }
  .filters { display: flex; gap: 0.8rem; flex-wrap: wrap; align-items: center; margin: 1rem 0; }
  .filters label { font-size: 0.85rem; color: #6B5D4F; margin-right: 0.3rem; }
  .filters input[type="date"], .filters input[type="search"], .filters select {
    font-family: 'Source Sans Pro', sans-serif; font-size: 0.9rem;
    padding: 0.35rem 0.55rem; border: 1px solid #C4B8A8; border-radius: 4px; background: white; color: #3D3229;
  }
  .filters input[type="search"] { min-width: 180px; }
  .row-count { margin-left: auto; color: #6B5D4F; font-size: 0.9rem; }
  table { width: 100%; border-collapse: collapse; background: white; font-size: 0.9rem;
          border: 1px solid #DED6C4; border-radius: 6px; overflow: hidden; }
  thead th { background: #EDE7DF; color: #3D3229; text-align: left; padding: 0.5rem 0.6rem;
             font-weight: 600; border-bottom: 1px solid #C4B8A8; white-space: nowrap; }
  thead th.center { text-align: center; }
  thead th.num { text-align: right; }
  tbody td { padding: 0.4rem 0.6rem; border-bottom: 1px solid #EDE7DF; }
  tbody td.center { text-align: center; }
  tbody td.num { text-align: right; font-variant-numeric: tabular-nums; }
  /* Row-status backgrounds — same as the live dashboard. */
  tbody tr.row-await    { background: #E8A8A8; }
  tbody tr.row-ready    { background: #FBF1CF; }
  tbody tr.row-claim    { background: #DFEEDE; }
  tbody tr.row-done     { background: #B8D9BF; }
  tbody tr.row-warn     { background: #C25B54; color: #fff; box-shadow: inset 3px 0 0 #743732; }
  tbody tr.row-excluded { background: #E2E0D9; color: #666; }
  tbody tr:hover { box-shadow: inset 0 0 0 9999px rgba(31,42,36,.04); }
  tbody tr.row-warn:hover { box-shadow: inset 3px 0 0 #743732, inset 0 0 0 9999px rgba(0,0,0,.05); }
  .flag { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #6B8E23; }
  .flag.off { background: transparent; border: 1px solid #C4B8A8; }
  .pill { display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.8rem;
          background: #EDE7DF; color: #3D3229; white-space: nowrap; }
  .pill.status-Awaiting.invoice, .pill.awaiting { background: #F5E6C7; color: #6B5D4F; }
  .pill.ready { background: #E6EAD8; color: #556B2F; }
  .pill.submitted { background: #E4E9EE; color: #3E4B57; }
  .pill.complete { background: #DDE7DD; color: #556B2F; }
  .pill.excluded { background: #E8DED4; color: #6B5D4F; }
  .pill.anomaly { background: #F5D9CE; color: #A0522D; }
  footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #E0D5C4;
           color: #8B7355; font-size: 0.85rem; }
  .empty { padding: 1rem; text-align: center; color: #6B5D4F; background: white;
           border: 1px solid #DED6C4; border-radius: 6px; margin-top: 0.5rem; }
</style>
</head>
<body>
  <h1>Claims Snapshot</h1>
  <div class="subtitle">Family medical invoices &amp; rebate tracking · Generated ${generatedAt}</div>

  <div class="privacy">Contains real personal data — review before sharing.</div>

  <div class="summary" id="summary"></div>

  <div class="filters">
    <label>From <input type="date" id="fx-from"></label>
    <label>To <input type="date" id="fx-to"></label>
    <input type="search" id="fx-q" placeholder="Search institution, notes…">
    <select id="fx-cl"><option value="">All claimants</option></select>
    <select id="fx-st"><option value="">All statuses</option></select>
    <span class="row-count" id="fx-count"></span>
  </div>

  <table id="fx-table">
    <thead>
      <tr>
        <th>Date</th>
        <th class="center" title="Days since incurred (open entries only)">Aged</th>
        <th>Claimant</th>
        <th>Institution</th>
        <th class="num">Amount</th>
        <th class="center" title="Invoice received">Inv</th>
        <th class="center" title="Claim submitted">Clm</th>
        <th class="center" title="Rebate received">Reb</th>
        <th class="center" title="Excluded">Exc</th>
        <th class="num">Rebated</th>
        <th class="num">Shortfall</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
  <div class="empty" id="fx-empty" style="display:none;">No matching entries.</div>

  <footer>Snapshot generated by Claims on ${generatedAt}.</footer>

<script>
  const DATA = ${dataJson};

  const fmtDate = (iso) => {
    if (!iso) return "";
    const [y, m, d] = iso.split("-");
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return \`\${d}-\${months[parseInt(m,10)-1]}-\${y.slice(2)}\`;
  };
  const money = (v) => (v == null || isNaN(v)) ? "" :
    Number(v).toLocaleString("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const sgd = (v) => "$" + money(v);
  const esc = (s) => {
    const d = document.createElement("div"); d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  };
  const daysAged = (r) => {
    if (r.status === "Complete" || r.status === "Excluded") return null;
    if (!r.date_incurred) return null;
    const diff = Date.now() - new Date(r.date_incurred + "T00:00:00").getTime();
    return Math.max(0, Math.floor(diff / (1000 * 60 * 60 * 24)));
  };
  const statusPillClass = (s) => {
    if (s === "Awaiting invoice") return "awaiting";
    if (s === "Ready to claim") return "ready";
    if (s === "Claim submitted") return "submitted";
    if (s === "Complete") return "complete";
    if (s === "Excluded") return "excluded";
    if (s && s.startsWith("Check:")) return "anomaly";
    return "";
  };
  // Mirrors rowClass() in claims.js so exported rows shade the same way as
  // they do in the live dashboard.
  const rowClass = (s) => {
    if (s === "Excluded") return "row-excluded";
    if (s && s.startsWith("Check")) return "row-warn";
    if (s === "Complete") return "row-done";
    if (s === "Claim submitted") return "row-claim";
    if (s === "Ready to claim") return "row-ready";
    return "row-await";
  };

  function fill(id, values, initial) {
    const sel = document.getElementById(id);
    for (const v of values) {
      const o = document.createElement("option");
      o.value = v; o.textContent = v;
      if (v === initial) o.selected = true;
      sel.appendChild(o);
    }
  }
  fill("fx-cl", DATA.claimants, DATA.initial.fcl);
  fill("fx-st", DATA.statuses, DATA.initial.fst);
  document.getElementById("fx-from").value = DATA.initial.dFrom || "";
  document.getElementById("fx-to").value = DATA.initial.dTo || "";
  document.getElementById("fx-q").value = DATA.initial.q || "";

  function currentFilter() {
    return {
      q: document.getElementById("fx-q").value.toLowerCase().trim(),
      fcl: document.getElementById("fx-cl").value,
      fst: document.getElementById("fx-st").value,
      dFrom: document.getElementById("fx-from").value,
      dTo: document.getElementById("fx-to").value,
    };
  }

  function applyFilter(rows, f) {
    return rows.filter((r) => {
      if (f.dFrom && r.date_incurred < f.dFrom) return false;
      if (f.dTo && r.date_incurred > f.dTo) return false;
      if (f.fcl && r.claimant !== f.fcl) return false;
      if (f.fst && r.status !== f.fst) return false;
      if (f.q && !(r.institution.toLowerCase().includes(f.q))) return false;
      return true;
    });
  }

  function render() {
    const filtered = applyFilter(DATA.rows, currentFilter());

    // Summary (three stats, matches on-screen)
    const incurred = filtered.reduce((s, r) => s + (r.amount || 0), 0);
    const rebate = filtered.reduce((s, r) => s + (r.amount_rebated || 0), 0);
    const shortfall = incurred - rebate;
    document.getElementById("summary").innerHTML =
      \`<div class="stat"><div class="n">\${sgd(incurred)}</div><div class="l">Total amount incurred</div></div>
       <div class="stat"><div class="n">\${sgd(rebate)}</div><div class="l">Total rebate</div></div>
       <div class="stat"><div class="n">\${sgd(shortfall)}</div><div class="l">Shortfall</div></div>\`;

    // Table
    const tbody = document.querySelector("#fx-table tbody");
    tbody.innerHTML = filtered.map((r) => {
      const aged = daysAged(r);
      return \`<tr class="\${rowClass(r.status)}">
        <td style="white-space:nowrap">\${esc(fmtDate(r.date_incurred))}</td>
        <td class="center">\${aged ?? ""}</td>
        <td>\${esc(r.claimant)}</td>
        <td>\${esc(r.institution)}</td>
        <td class="num">\${esc(money(r.amount))}</td>
        <td class="center"><span class="flag \${r.invoice_received ? "" : "off"}"></span></td>
        <td class="center"><span class="flag \${r.claimed ? "" : "off"}"></span></td>
        <td class="center"><span class="flag \${r.rebated ? "" : "off"}"></span></td>
        <td class="center"><span class="flag \${r.excluded ? "" : "off"}"></span></td>
        <td class="num">\${r.rebated ? esc(money(r.amount_rebated)) : "—"}</td>
        <td class="num">\${esc(money(r.shortfall))}</td>
        <td><span class="pill \${statusPillClass(r.status)}">\${esc(r.status)}</span></td>
      </tr>\`;
    }).join("");

    document.getElementById("fx-empty").style.display = filtered.length ? "none" : "";
    document.getElementById("fx-count").textContent =
      \`\${filtered.length} of \${DATA.rows.length} rows · \${sgd(incurred)} incurred\`;
  }

  ["fx-from","fx-to","fx-q","fx-cl","fx-st"].forEach((id) => {
    const el = document.getElementById(id);
    el.addEventListener(id === "fx-q" ? "input" : "change", render);
  });
  render();
</script>
</body>
</html>`;
  }

  boot().catch((err) => console.error("Claims boot failed:", err));
})();
