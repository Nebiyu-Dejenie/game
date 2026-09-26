import { api, escapeHtml, fmtDate, getRole } from "../api.js";
import { renderError, toast } from "../ui.js";

export const label = "Payments";

// services/admin/rbac.py's payments:approve -- visibility only; the backend
// is the real check.
const CAN_RESOLVE = ["finance", "superadmin"];

function minutesSince(iso) {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
}

export async function render(container) {
  container.innerHTML = `
    <h1>Withdrawals awaiting review</h1>
    <div id="withdrawals-list"><p class="loading">Loading…</p></div>
    <h2>Payouts awaiting reconciliation</h2>
    <p class="field-hint">Sent to Chapa, but the outcome isn't known: Chapa accepted the transfer without confirming it,
      or the request may not have reached Chapa at all. These are never resent or refunded automatically. Check each
      one in Chapa's dashboard, then record what happened. The player's funds stay locked until you do.</p>
    <div id="reconciliation-list"><p class="loading">Loading…</p></div>
  `;
  const listEl = container.querySelector("#withdrawals-list");
  const reconEl = container.querySelector("#reconciliation-list");
  const canResolve = CAN_RESOLVE.includes(getRole());

  async function reload() {
    const withdrawals = await api("/withdrawals");
    renderList(withdrawals);
  }

  async function reloadReconciliation() {
    renderReconciliation(await api("/payouts/awaiting-reconciliation"));
  }

  function renderList(withdrawals) {
    if (withdrawals.length === 0) {
      listEl.innerHTML = `<p class="empty">Nothing in review right now.</p>`;
      return;
    }
    listEl.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>Ref</th><th>User</th><th>Amount</th><th>Method</th><th>Destination</th>
            <th>Why in review</th><th>Requested</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${withdrawals.map((w) => `
            <tr data-payment-id="${w.id}">
              <td>${escapeHtml(w.our_ref)}</td>
              <td>${escapeHtml(w.display_name)} (#${w.user_id})</td>
              <td>${w.amount} ETB</td>
              <td>${escapeHtml(w.method_kind || "—")}</td>
              <td>${escapeHtml(w.account_ref || "—")} / ${escapeHtml(w.holder_name || "—")}</td>
              <td>${escapeHtml(w.review_reason || "—")}</td>
              <td>${fmtDate(w.created_at)}</td>
              <td>
                <button class="btn btn-success btn-sm approve-btn">Approve</button>
                <button class="btn btn-danger btn-sm reject-btn">Reject</button>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;

    for (const row of listEl.querySelectorAll("tr[data-payment-id]")) {
      const paymentId = Number(row.dataset.paymentId);
      row.querySelector(".approve-btn").addEventListener("click", () => decide(paymentId, "approve"));
      row.querySelector(".reject-btn").addEventListener("click", () => decide(paymentId, "reject"));
    }
  }

  function renderReconciliation(payouts) {
    if (payouts.length === 0) {
      reconEl.innerHTML = `<p class="empty">No payouts waiting. Every automatic payout has a known outcome.</p>`;
      return;
    }
    reconEl.innerHTML = `
      <table class="data-table" id="reconciliation-table">
        <thead>
          <tr>
            <th>Ref</th><th>User</th><th>Amount</th><th>Chapa ref</th><th>What the worker saw</th>
            <th>Processing for</th>${canResolve ? "<th>Record outcome</th>" : ""}
          </tr>
        </thead>
        <tbody>
          ${payouts.map((p) => `
            <tr data-payment-id="${p.id}" data-amount="${escapeHtml(String(p.amount))}" data-ref="${escapeHtml(p.our_ref)}">
              <td>${escapeHtml(p.our_ref)}</td>
              <td>${escapeHtml(p.display_name)} (#${p.user_id})</td>
              <td>${p.amount} ETB</td>
              <td>${escapeHtml(p.provider_ref || "—")}</td>
              <td>${escapeHtml(p.failure_reason || (p.provider_ref ? "Accepted by Chapa, never confirmed" : "—"))}</td>
              <td>${minutesSince(p.updated_at)} min</td>
              ${canResolve ? `<td>
                <button class="btn btn-success btn-sm paid-btn" ${p.resolvable ? "" : "disabled"}>Mark paid</button>
                <button class="btn btn-danger btn-sm failed-btn" ${p.resolvable ? "" : "disabled"}>Mark failed &amp; refund</button>
                ${p.resolvable ? "" : `<div class="field-hint">Available after 10 minutes</div>`}
              </td>` : ""}
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
    if (!canResolve) return;
    for (const row of reconEl.querySelectorAll("tr[data-payment-id]")) {
      const paymentId = Number(row.dataset.paymentId);
      const { amount, ref } = row.dataset;
      row.querySelector(".paid-btn").addEventListener("click", () => resolve(paymentId, "paid", amount, ref));
      row.querySelector(".failed-btn").addEventListener("click", () => resolve(paymentId, "failed", amount, ref));
    }
  }

  async function resolve(paymentId, outcome, amount, ref) {
    const consequence =
      outcome === "paid"
        ? `Record ${ref} as PAID: ${amount} ETB leaves the player's locked balance for good. Only do this if Chapa shows the transfer completed.`
        : `Record ${ref} as FAILED: ${amount} ETB goes back to the player's balance. Only do this if Chapa shows the transfer failed or has no record of it. If it actually went through, the player is paid twice.`;
    if (!window.confirm(consequence)) return;
    let providerRef = null;
    if (outcome === "paid") {
      providerRef = window.prompt("Chapa's transfer reference (optional):", "");
      if (providerRef === null) return;
    }
    const reason = window.prompt("What did Chapa's dashboard show? (required)");
    if (reason === null) return;
    if (!reason.trim()) {
      toast("A reason is required.", true);
      return;
    }
    try {
      await api(`/payouts/${paymentId}/resolve`, {
        method: "POST",
        body: { outcome, reason, provider_ref: providerRef || null },
      });
      toast(outcome === "paid" ? `${ref} recorded as paid.` : `${ref} recorded as failed; ${amount} ETB returned.`);
      reloadReconciliation();
    } catch (err) {
      toast(err.detail || err.message, true);
    }
  }

  async function decide(paymentId, action) {
    const reason = window.prompt(`Reason to ${action} this withdrawal:`);
    if (reason === null) return;
    if (!reason.trim()) {
      toast("A reason is required.", true);
      return;
    }
    try {
      await api(`/withdrawals/${paymentId}/${action}`, { method: "POST", body: { reason } });
      toast(action === "approve" ? "Withdrawal approved." : "Withdrawal rejected.");
      reload();
    } catch (err) {
      toast(err.detail || err.message, true);
    }
  }

  try {
    await reload();
  } catch (err) {
    renderError(listEl, err);
  }
  try {
    await reloadReconciliation();
  } catch (err) {
    renderError(reconEl, err);
  }
}
