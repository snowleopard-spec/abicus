(() => {
  const state = {
    claims: [],
    archivedClaims: [],
    showArchived: false,
    claimants: [],
    institutions: [],
    filters: {
      from: null,
      to: null,
      claimant: "",
      status: "",
      search: "",
    },
  };

  const fmtCcy = (amount, ccy = "SGD") =>
    new Intl.NumberFormat("en-SG", {
      style: "currency", currency: ccy || "SGD", maximumFractionDigits: 0,
    }).format(amount || 0);

  const fmtDate = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso + "T00:00:00");
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
  };

  const daysSince = (iso) => {
    if (!iso) return null;
    const then = new Date(iso + "T00:00:00").getTime();
    if (Number.isNaN(then)) return null;
    return Math.max(0, Math.floor((Date.now() - then) / 86400000));
  };

  const statusClass = (s) => {
    switch (s) {
      case "Awaiting invoice": return "row-await";
      case "Ready to claim":   return "row-ready";
      case "Claim submitted":  return "row-claim";
      case "Complete":         return "row-done";
      case "Excluded":         return "row-excluded";
      case "Check: rebated but not claimed": return "row-warn";
      default: return "";
    }
  };
  const statusTag = (s) => {
    const map = {
      "Awaiting invoice": "tag-danger",
      "Ready to claim":   "tag-warning",
      "Claim submitted":  "tag-accent",
      "Complete":         "tag-success",
      "Excluded":         "tag",
      "Check: rebated but not claimed": "tag-danger",
    };
    return `<span class="tag ${map[s] || ""}">${s}</span>`;
  };

  // ---------- data load ----------

  async function loadAll() {
    const [config, institutions, active, archived] = await Promise.all([
      api.get("/api/claims/config"),
      api.get("/api/claims/institutions"),
      api.get("/api/claims/claims"),
      api.get("/api/claims/claims/archived"),
    ]);
    state.claimants = config.claimants || [];
    state.institutions = institutions || [];
    state.claims = active || [];
    state.archivedClaims = archived || [];
    populateClaimantFilter();
    render();
  }

  async function reloadClaims() {
    const [active, archived] = await Promise.all([
      api.get("/api/claims/claims"),
      api.get("/api/claims/claims/archived"),
    ]);
    state.claims = active || [];
    state.archivedClaims = archived || [];
    render();
  }

  function populateClaimantFilter() {
    const sel = document.getElementById("filter-claimant");
    sel.innerHTML = '<option value="">All</option>' +
      state.claimants.map(c => `<option value="${c}">${c}</option>`).join("");
  }

  // ---------- filtering ----------

  function filtered() {
    const src = state.showArchived ? state.archivedClaims : state.claims;
    const { from, to, claimant, status, search } = state.filters;
    const q = (search || "").trim().toLowerCase();
    return src.filter(c => {
      if (from && c.date_incurred < from) return false;
      if (to && c.date_incurred > to) return false;
      if (claimant && c.claimant !== claimant) return false;
      if (status === "open") {
        if (c.status === "Complete" || c.status === "Excluded") return false;
      } else if (status && c.status !== status) return false;
      if (q) {
        const hay = `${c.institution || ""} ${c.notes || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  // ---------- render ----------

  function render() {
    const rows = filtered();
    renderTiles(rows);
    renderTable(rows);
    document.getElementById("toggle-archive-btn").textContent =
      state.showArchived ? "Show active" : "Show archived";
  }

  function renderTiles(rows) {
    const ccy = (rows[0] && rows[0].currency) || "SGD";
    const incurred = rows.reduce((s, c) => s + (c.excluded ? 0 : Number(c.amount || 0)), 0);
    const rebated = rows.reduce((s, c) => s + (c.excluded ? 0 : Number(c.amount_rebated || 0)), 0);
    const outstanding = rows.reduce((s, c) => s + (Number(c.outstanding || 0)), 0);
    document.getElementById("tile-incurred").textContent = fmtCcy(incurred, ccy);
    document.getElementById("tile-rebated").textContent = fmtCcy(rebated, ccy);
    document.getElementById("tile-outstanding").textContent = fmtCcy(outstanding, ccy);
    document.getElementById("tile-count").textContent = String(rows.length);
    const excluded = rows.filter(c => c.excluded).length;
    document.getElementById("tile-count-sub").textContent =
      `${rows.length - excluded} active, ${excluded} excluded`;
    document.getElementById("tile-incurred-sub").textContent =
      state.showArchived ? "Archived" : "Active";
    document.getElementById("tile-rebated-sub").textContent =
      rebated > 0 ? `${Math.round((rebated / Math.max(incurred,1)) * 100)}% recovered` : "";
    document.getElementById("tile-outstanding-sub").textContent =
      `${rows.filter(c => c.outstanding > 0).length} open`;
  }

  function dotHtml(claimId, field, on) {
    return `<button class="toggle-dot ${on ? "on" : ""}" data-toggle="${field}" data-id="${claimId}" title="${field}">${on ? "●" : ""}</button>`;
  }

  function renderTable(rows) {
    const tbody = document.getElementById("claims-tbody");
    const empty = document.getElementById("empty-state");
    if (rows.length === 0) {
      tbody.innerHTML = "";
      empty.classList.remove("hidden");
      return;
    }
    empty.classList.add("hidden");
    tbody.innerHTML = rows.map(c => {
      const aged = (c.status === "Complete" || c.status === "Excluded") ? "" : (() => {
        const d = daysSince(c.date_incurred);
        return d === null ? "" : `<span class="aged-cell">${d}d</span>`;
      })();
      const invoiceCell = c.invoice_file
        ? `<a href="/api/claims/claims/${c.id}/invoice" target="_blank" rel="noopener">View ↗</a>`
        : `<button class="btn btn-ghost btn-sm" data-action="upload-invoice" data-id="${c.id}">+ Add</button>`;
      const otherCount = (c.other_files || []).length;
      const otherCell = `<button class="btn btn-ghost btn-sm" data-action="other-docs" data-id="${c.id}">${otherCount ? `${otherCount} doc${otherCount > 1 ? "s" : ""}` : "+ Add"}</button>`;
      const actions = state.showArchived
        ? `<button class="btn btn-ghost btn-sm" data-action="restore" data-id="${c.id}">Restore</button>
           <button class="btn btn-sm btn-danger" data-action="delete" data-id="${c.id}">Delete</button>`
        : `<button class="btn btn-ghost btn-sm" data-action="edit" data-id="${c.id}">Edit</button>
           <button class="btn btn-ghost btn-sm" data-action="archive" data-id="${c.id}">Archive</button>`;
      const rebatedCell = c.rebated
        ? fmtCcy(c.amount_rebated, c.currency)
        : `<span class="muted-dash">—</span>`;
      return `
        <tr class="${statusClass(c.status)}">
          <td>${fmtDate(c.date_incurred)}</td>
          <td>${aged}</td>
          <td>${c.claimant}</td>
          <td>${c.institution}</td>
          <td class="right amount">${fmtCcy(c.amount, c.currency)}</td>
          <td class="center">${dotHtml(c.id, "invoice_received", c.invoice_received)}</td>
          <td class="center">${dotHtml(c.id, "claimed", c.claimed)}</td>
          <td class="center">${dotHtml(c.id, "rebated", c.rebated)}</td>
          <td class="center">${dotHtml(c.id, "excluded", c.excluded)}</td>
          <td class="right amount">${rebatedCell}</td>
          <td class="right amount">${fmtCcy(c.outstanding, c.currency)}</td>
          <td>${statusTag(c.status)}</td>
          <td class="invoice">${invoiceCell}</td>
          <td>${otherCell}</td>
          <td class="right"><div class="row-actions">${actions}</div></td>
        </tr>
      `;
    }).join("");
  }

  // ---------- modal helpers ----------

  function mountTemplate(templateId) {
    const tpl = document.getElementById(templateId);
    const fragment = tpl.content.cloneNode(true);
    const root = document.body.appendChild(document.createElement("div"));
    root.appendChild(fragment);
    const close = () => root.remove();
    root.querySelectorAll('[data-role="close"], [data-role="cancel"]').forEach(b => b.addEventListener("click", close));
    return { root, close };
  }

  function fillClaimantSelect(sel) {
    sel.innerHTML = state.claimants.map(c => `<option value="${c}">${c}</option>`).join("");
  }
  function fillInstitutionSelect(sel) {
    sel.innerHTML = state.institutions.map(i => `<option value="${i}">${i}</option>`).join("") +
      `<option value="__add__">+ Add new institution…</option>`;
  }

  function openClaimModal(claim) {
    const { root, close } = mountTemplate("modal-claim-template");
    const form = root.querySelector('[data-role="form"]');
    const title = root.querySelector('[data-role="title"]');
    const claimantSel = root.querySelector('[data-role="claimant"]');
    const institutionSel = root.querySelector('[data-role="institution"]');
    const rebatedCb = root.querySelector('[data-role="rebated-cb"]');
    const rebatedAmtField = root.querySelector('[data-role="rebated-amount-field"]');

    fillClaimantSelect(claimantSel);
    fillInstitutionSelect(institutionSel);

    title.textContent = claim ? `Edit claim #${claim.id}` : "New claim";

    if (claim) {
      claimantSel.value = claim.claimant;
      institutionSel.value = claim.institution;
      form.querySelector('[name="date_incurred"]').value = claim.date_incurred || "";
      form.querySelector('[name="amount"]').value = claim.amount || 0;
      form.querySelector('[name="currency"]').value = claim.currency || "SGD";
      form.querySelector('[name="invoice_received"]').checked = !!claim.invoice_received;
      form.querySelector('[name="claimed"]').checked = !!claim.claimed;
      form.querySelector('[name="rebated"]').checked = !!claim.rebated;
      form.querySelector('[name="excluded"]').checked = !!claim.excluded;
      form.querySelector('[name="amount_rebated"]').value = claim.amount_rebated || 0;
      form.querySelector('[name="notes"]').value = claim.notes || "";
      if (claim.rebated) rebatedAmtField.classList.remove("hidden");
    } else {
      form.querySelector('[name="date_incurred"]').value = new Date().toISOString().slice(0, 10);
    }

    rebatedCb.addEventListener("change", (e) => {
      rebatedAmtField.classList.toggle("hidden", !e.target.checked);
    });

    institutionSel.addEventListener("change", async (e) => {
      if (e.target.value === "__add__") {
        const newName = await promptInstitution();
        if (newName) {
          state.institutions = await api.postJson("/api/claims/institutions", { name: newName });
          fillInstitutionSelect(institutionSel);
          institutionSel.value = newName;
        } else {
          institutionSel.value = claim ? claim.institution : (state.institutions[0] || "");
        }
      }
    });

    root.querySelector('[data-role="save"]').addEventListener("click", async () => {
      const fd = new FormData(form);
      ["invoice_received", "claimed", "rebated", "excluded"].forEach(k => {
        fd.set(k, form.querySelector(`[name="${k}"]`).checked ? "true" : "false");
      });
      if (!form.querySelector('[name="rebated"]').checked) {
        fd.set("amount_rebated", "0");
      }
      try {
        if (claim) {
          await api.putForm(`/api/claims/claims/${claim.id}`, fd);
          toast("Claim updated", "ok");
        } else {
          await api.postForm("/api/claims/claims", fd);
          toast("Claim created", "ok");
        }
        close();
        await reloadClaims();
      } catch (e) {
        // toast already shown by api wrapper
      }
    });
  }

  function promptInstitution() {
    return new Promise((resolve) => {
      const { root, close } = mountTemplate("modal-add-institution-template");
      const input = root.querySelector('[data-role="name"]');
      input.focus();
      root.querySelector('[data-role="save"]').addEventListener("click", () => {
        const v = input.value.trim();
        close();
        resolve(v || null);
      });
      root.querySelector('[data-role="close"]').addEventListener("click", () => {
        close();
        resolve(null);
      });
    });
  }

  function openOtherDocsModal(claim) {
    const { root, close } = mountTemplate("modal-other-docs-template");
    const list = root.querySelector('[data-role="list"]');
    const fileInput = root.querySelector('[data-role="file"]');
    const renderList = () => {
      list.innerHTML = (claim.other_files || []).map(f => `
        <li>
          <a href="/api/claims/claims/${claim.id}/files/${f.id}" target="_blank" rel="noopener">${f.original_name}</a>
          <span class="actions">
            <button class="btn btn-sm btn-danger" data-fid="${f.id}">Delete</button>
          </span>
        </li>
      `).join("") || `<li class="muted">No documents attached yet.</li>`;
      list.querySelectorAll("button[data-fid]").forEach(b => {
        b.addEventListener("click", async () => {
          if (!confirm("Delete this document?")) return;
          await api.del(`/api/claims/claims/${claim.id}/files/${b.dataset.fid}`);
          toast("Document deleted", "ok");
          await reloadClaims();
          claim.other_files = (state.claims.concat(state.archivedClaims)
            .find(c => c.id === claim.id) || claim).other_files;
          renderList();
        });
      });
    };
    renderList();
    root.querySelector('[data-role="upload"]').addEventListener("click", async () => {
      if (!fileInput.files || fileInput.files.length === 0) {
        toast("Choose a file first", "warn");
        return;
      }
      const fd = new FormData();
      fd.append("file", fileInput.files[0]);
      const rec = await api.postForm(`/api/claims/claims/${claim.id}/files`, fd);
      claim.other_files = (claim.other_files || []).concat([rec]);
      fileInput.value = "";
      toast("Document uploaded", "ok");
      renderList();
      reloadClaims();
    });
  }

  function uploadInvoiceFor(claimId) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pdf,.png,.jpg,.jpeg,.heic,.webp";
    input.addEventListener("change", async () => {
      if (!input.files || input.files.length === 0) return;
      const fd = new FormData();
      fd.append("file", input.files[0]);
      await api.postForm(`/api/claims/claims/${claimId}/invoice`, fd);
      toast("Invoice uploaded", "ok");
      reloadClaims();
    });
    input.click();
  }

  // ---------- table interaction ----------

  document.getElementById("claims-tbody").addEventListener("click", async (e) => {
    const toggleBtn = e.target.closest(".toggle-dot");
    if (toggleBtn) {
      const fd = new FormData();
      fd.set("field", toggleBtn.dataset.toggle);
      await api.postForm(`/api/claims/claims/${toggleBtn.dataset.id}/toggle`, fd);
      reloadClaims();
      return;
    }
    const actionBtn = e.target.closest("button[data-action]");
    if (!actionBtn) return;
    const id = Number(actionBtn.dataset.id);
    const claim = state.claims.concat(state.archivedClaims).find(c => c.id === id);
    switch (actionBtn.dataset.action) {
      case "edit":         openClaimModal(claim); break;
      case "archive":
        if (!confirm("Archive this claim?")) return;
        await api.del(`/api/claims/claims/${id}`);
        toast("Archived", "ok"); reloadClaims(); break;
      case "restore":
        await api.postJson(`/api/claims/claims/${id}/restore`, {});
        toast("Restored", "ok"); reloadClaims(); break;
      case "delete":
        if (!confirm("Permanently delete this claim and all its files?")) return;
        await api.del(`/api/claims/claims/${id}/permanent`);
        toast("Deleted", "ok"); reloadClaims(); break;
      case "upload-invoice":
        uploadInvoiceFor(id); break;
      case "other-docs":
        openOtherDocsModal(claim); break;
    }
  });

  // ---------- filter handlers ----------

  ["filter-from","filter-to","filter-claimant","filter-status","filter-search"].forEach(id => {
    document.getElementById(id).addEventListener("input", (e) => {
      const map = {
        "filter-from": "from", "filter-to": "to",
        "filter-claimant": "claimant", "filter-status": "status", "filter-search": "search",
      };
      state.filters[map[id]] = e.target.value || (id === "filter-from" || id === "filter-to" ? null : "");
      render();
    });
  });

  document.getElementById("toggle-archive-btn").addEventListener("click", () => {
    state.showArchived = !state.showArchived;
    render();
  });

  document.getElementById("new-claim-btn").addEventListener("click", () => openClaimModal(null));

  // ---------- defaults & boot ----------

  const today = new Date();
  const yearStart = new Date(today.getFullYear(), 0, 1);
  document.getElementById("filter-from").value = yearStart.toISOString().slice(0, 10);
  document.getElementById("filter-to").value = today.toISOString().slice(0, 10);
  state.filters.from = document.getElementById("filter-from").value;
  state.filters.to = document.getElementById("filter-to").value;
  state.filters.status = "open";
  document.getElementById("filter-status").value = "open";

  loadAll().catch(err => console.error("Claims boot failed:", err));
})();
