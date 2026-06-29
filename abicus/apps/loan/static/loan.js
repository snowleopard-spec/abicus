(() => {
  const state = {
    config: null,
    snapshot: null,
    schedule: null,
    asOf: null,
    tabulator: null,
    lastCollapsed: false,
  };

  // ---------- formatting ----------

  function fmtMoney(value, ccy) {
    if (value == null) return "—";
    const num = Number(value);
    if (Number.isNaN(num)) return "—";
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: ccy || "SGD",
      maximumFractionDigits: 2, minimumFractionDigits: 2,
    }).format(num);
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso + "T00:00:00");
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
  }
  function fmtPct(v) {
    if (v == null) return "—";
    return (Number(v) * 100).toFixed(2) + "%";
  }
  function todayIso() {
    return new Date().toISOString().slice(0, 10);
  }

  // ---------- boot ----------

  async function boot() {
    state.asOf = todayIso();
    document.getElementById("as-of-picker").value = state.asOf;
    await refreshAll();
    wireAsOf();
    wireEdit();
    wireLastToggle();
  }

  async function refreshAll() {
    state.config = await api.get("/api/loan/config");
    state.snapshot = await api.get(`/api/loan/state?as_of=${state.asOf}`);
    state.schedule = await api.get("/api/loan/schedule");
    renderTiles();
    renderLast();
    renderSchedule();
  }

  async function refreshSnapshot() {
    state.snapshot = await api.get(`/api/loan/state?as_of=${state.asOf}`);
    renderTiles();
    renderLast();
  }

  function wireAsOf() {
    document.getElementById("as-of-picker").addEventListener("change", (e) => {
      state.asOf = e.target.value || todayIso();
      refreshSnapshot();
    });
  }

  function wireLastToggle() {
    document.getElementById("toggle-last").addEventListener("click", () => {
      state.lastCollapsed = !state.lastCollapsed;
      document.getElementById("last-table").classList.toggle("is-collapsed", state.lastCollapsed);
      document.getElementById("toggle-last").textContent = state.lastCollapsed ? "Show" : "Hide";
    });
  }

  // ---------- render ----------

  function renderTiles() {
    const s = state.snapshot;
    const ccy = s.currency;
    document.getElementById("tile-principal").textContent = fmtMoney(s.principal, ccy);
    document.getElementById("tile-principal-sub").textContent =
      s.paid_off ? "Loan fully repaid" : `+ ${fmtMoney(s.accrued_interest, ccy)} accrued`;
    document.getElementById("tile-accrued").textContent = fmtMoney(s.accrued_interest, ccy);
    document.getElementById("tile-accrued-sub").textContent =
      s.paid_off ? "" : `over ${s.days_since_last_payment} day(s) at Actual/365`;
    if (s.paid_off) {
      document.getElementById("tile-next").textContent = "—";
      document.getElementById("tile-next-sub").textContent = "Fully repaid";
    } else {
      document.getElementById("tile-next").textContent = fmtMoney(s.next_payment_amount, ccy);
      document.getElementById("tile-next-sub").textContent = `due ${fmtDate(s.next_payment_date)}`;
    }
    document.getElementById("tile-days").textContent = String(s.days_since_last_payment);
    document.getElementById("tile-days-sub").textContent =
      s.last_payment ? `last paid ${fmtDate(s.last_payment.date)}` : "";
  }

  function renderLast() {
    const lp = state.snapshot.last_payment;
    if (!lp) {
      document.getElementById("last-table").innerHTML =
        `<tr><td colspan="2" class="muted">No payments made yet.</td></tr>`;
      return;
    }
    const ccy = state.snapshot.currency;
    const rows = [
      ["Date", fmtDate(lp.date)],
      ["Payment", fmtMoney(lp.amount, ccy)],
      ["Interest portion", fmtMoney(lp.interest, ccy)],
      ["Principal portion", fmtMoney(lp.principal_paid, ccy)],
      ["Closing principal", fmtMoney(lp.closing_principal, ccy)],
    ];
    document.getElementById("last-table").innerHTML =
      rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  }

  function renderSchedule() {
    const sch = state.schedule;
    const ccy = sch.currency;
    const today = todayIso();
    document.getElementById("schedule-summary").textContent =
      `${sch.rows.length} payments · total ${fmtMoney(sch.summary.total_paid, ccy)} ` +
      `(${fmtMoney(sch.summary.total_interest, ccy)} interest) · payoff ${fmtDate(sch.summary.payoff_date)}`;
    if (state.tabulator) state.tabulator.destroy();
    state.tabulator = new Tabulator("#schedule-table", {
      data: sch.rows.map(r => ({ ...r, _future: r.payment_date > today })),
      layout: "fitColumns",
      height: 480,
      pagination: true,
      paginationSize: 24,
      initialSort: [{ column: "payment_date", dir: "asc" }],
      rowFormatter: (row) => {
        if (row.getData()._future) row.getElement().classList.add("row-future");
      },
      columns: [
        { title: "Date", field: "payment_date", width: 120,
          formatter: (cell) => fmtDate(cell.getValue()) },
        { title: "Payment", field: "amount", hozAlign: "right",
          formatter: (cell) => fmtMoney(cell.getValue(), ccy) },
        { title: "Interest", field: "interest", hozAlign: "right",
          formatter: (cell) => fmtMoney(cell.getValue(), ccy) },
        { title: "Principal", field: "principal_paid", hozAlign: "right",
          formatter: (cell) => fmtMoney(cell.getValue(), ccy) },
        { title: "Closing principal", field: "closing_principal", hozAlign: "right",
          formatter: (cell) => fmtMoney(cell.getValue(), ccy) },
      ],
    });
  }

  // ---------- edit modal ----------

  function wireEdit() {
    document.getElementById("edit-loan-btn").addEventListener("click", openEditModal);
  }

  function openEditModal() {
    const tpl = document.getElementById("modal-edit-template");
    const root = document.body.appendChild(document.createElement("div"));
    root.appendChild(tpl.content.cloneNode(true));
    const close = () => root.remove();
    root.querySelectorAll('[data-role="close"], [data-role="cancel"]').forEach(b => b.addEventListener("click", close));

    const form = root.querySelector('[data-role="form"]');
    const c = state.config;
    form.querySelector('[name="origin_date"]').value = c.origin_date;
    form.querySelector('[name="maturity_date"]').value = c.maturity_date;
    form.querySelector('[name="origin_principal"]').value = c.origin_principal;
    form.querySelector('[name="monthly_payment"]').value = c.monthly_payment;
    form.querySelector('[name="annual_rate"]').value = c.annual_rate;
    form.querySelector('[name="original_tenor_months"]').value = c.original_tenor_months;
    form.querySelector('[name="payment_day_of_month"]').value = c.payment_day_of_month;
    form.querySelector('[name="currency"]').value = c.currency;

    root.querySelector('[data-role="save"]').addEventListener("click", async () => {
      const body = {
        origin_date: form.querySelector('[name="origin_date"]').value,
        maturity_date: form.querySelector('[name="maturity_date"]').value,
        origin_principal: form.querySelector('[name="origin_principal"]').value.trim(),
        monthly_payment: form.querySelector('[name="monthly_payment"]').value.trim(),
        annual_rate: form.querySelector('[name="annual_rate"]').value.trim(),
        original_tenor_months: Number(form.querySelector('[name="original_tenor_months"]').value),
        payment_day_of_month: Number(form.querySelector('[name="payment_day_of_month"]').value),
        currency: form.querySelector('[name="currency"]').value.trim(),
      };
      try {
        await api.putJson("/api/loan/config", body);
        toast("Loan saved", "ok");
        close();
        await refreshAll();
      } catch (e) {}
    });
  }

  boot().catch(err => console.error("Loan boot failed:", err));
})();
