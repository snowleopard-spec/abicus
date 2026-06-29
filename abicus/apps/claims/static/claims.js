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

  function render() {
    const q = document.getElementById("filter-search").value.toLowerCase().trim();
    const fcl = document.getElementById("filter-claimant").value;
    const fst = document.getElementById("filter-status").value;
    const fop = document.getElementById("filter-open").value;
    const dFrom = document.getElementById("filter-from").value;
    const dTo = document.getElementById("filter-to").value;

    const inWindow = state.claims.filter((r) => {
      if (dFrom && r.date_incurred < dFrom) return false;
      if (dTo && r.date_incurred > dTo) return false;
      return true;
    });

    let rows = inWindow.filter((r) => {
      if (fcl && r.claimant !== fcl) return false;
      if (fst && r.status !== fst) return false;
      if (fop === "open" && r.status === "Complete") return false;
      if (q && !(r.institution.toLowerCase().includes(q) || (r.notes || "").toLowerCase().includes(q))) return false;
      return true;
    });

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
      const otherN = (r.other_files || []).length;
      const otherIcon = `<span class="other-docs-icon ${otherN ? "has" : ""}"
                              data-action="other-docs" data-id="${r.id}"
                              title="Attached documents${otherN ? ` (${otherN})` : ""}">📎${otherN ? ` ${otherN}` : ""}</span>`;
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
            ${otherIcon}
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

    document.getElementById("export-png-btn").addEventListener("click", exportAwaitingPng);

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
      case "other-docs": openOtherDocsModal(claim); break;
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

  function openOtherDocsModal(claim) {
    // Reuse the edit modal but restricted to the other-docs section.
    openEdit(claim);
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

  // ---------- Export PNG (Awaiting invoice rows) ----------

  function exportAwaitingPng() {
    const dFrom = document.getElementById("filter-from").value;
    const dTo = document.getElementById("filter-to").value;
    const rows = state.claims
      .filter((r) => r.status === "Awaiting invoice"
        && (!dFrom || r.date_incurred >= dFrom)
        && (!dTo || r.date_incurred <= dTo))
      .sort((a, b) => (a.date_incurred < b.date_incurred ? -1 : 1));

    if (!rows.length) { alert("No \"Awaiting invoice\" entries in the selected date range."); return; }

    const cols = [
      { h: "Date",        get: (r) => fmtDate(r.date_incurred),                       align: "left" },
      { h: "Claimant",    get: (r) => r.claimant || "",                               align: "left" },
      { h: "Institution", get: (r) => r.institution || "",                            align: "left" },
      { h: "Amount",      get: (r) => money(r.amount) + " " + (r.currency || ""),     align: "right" },
    ];

    const dpr = window.devicePixelRatio || 1;
    const padX = 14, rowH = 32, headerH = 38;
    const bodyFont = '14px "Iowan Old Style", Georgia, "Times New Roman", serif';
    const headFont = '700 12px "Iowan Old Style", Georgia, "Times New Roman", serif';

    const meas = document.createElement("canvas").getContext("2d");
    const colW = cols.map((c) => {
      meas.font = headFont;
      let w = meas.measureText(c.h.toUpperCase()).width;
      meas.font = bodyFont;
      for (const r of rows) w = Math.max(w, meas.measureText(String(c.get(r))).width);
      return Math.ceil(w + padX * 2);
    });

    const margin = 12;
    const tableW = colW.reduce((a, b) => a + b, 0);
    const tableH = headerH + rows.length * rowH;
    const W = tableW + margin * 2;
    const H = tableH + margin * 2;

    const cvs = document.createElement("canvas");
    cvs.width = W * dpr; cvs.height = H * dpr;
    const ctx = cvs.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.textBaseline = "middle";

    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, W, H);
    ctx.translate(margin, margin);
    ctx.fillStyle = "#fbfaf6"; ctx.fillRect(0, 0, tableW, tableH);

    // header band
    ctx.fillStyle = "#e6e1d3"; ctx.fillRect(0, 0, tableW, headerH);
    ctx.fillStyle = "#1f2a24"; ctx.font = headFont;
    let x = 0;
    cols.forEach((c, i) => {
      ctx.textAlign = c.align;
      const tx = c.align === "right" ? x + colW[i] - padX : x + padX;
      ctx.fillText(c.h.toUpperCase(), tx, headerH / 2);
      x += colW[i];
    });

    // rows
    ctx.font = bodyFont;
    rows.forEach((r, ri) => {
      const y = headerH + ri * rowH;
      ctx.fillStyle = "#e8a8a8"; ctx.fillRect(0, y, tableW, rowH);
      ctx.fillStyle = "#1f2a24";
      let cx = 0;
      cols.forEach((c, i) => {
        ctx.textAlign = c.align;
        const tx = c.align === "right" ? cx + colW[i] - padX : cx + padX;
        ctx.fillText(String(c.get(r)), tx, y + rowH / 2);
        cx += colW[i];
      });
      ctx.strokeStyle = "#ddd9cf"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, y + rowH + 0.5); ctx.lineTo(tableW, y + rowH + 0.5); ctx.stroke();
    });

    ctx.strokeStyle = "#ddd9cf"; ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, tableW - 1, tableH - 1);

    const today = new Date().toISOString().slice(0, 10);
    cvs.toBlob((blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `mediclaim-awaiting-${today}.png`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    });
  }

  boot().catch((err) => console.error("Claims boot failed:", err));
})();
