import { api, escapeHtml, fmtDate } from "../api.js";
import { renderError } from "../ui.js";

export const label = "Change history";

// Mirrors services/admin/platform_settings_queries.py CONFIG_TARGET_TYPES.
const SCOPES = [
  ["", "All configuration"],
  ["platform", "Platform settings"],
  ["keno", "Keno rules, tiers & paytables"],
  ["bingo", "Bingo rooms"],
  ["payments", "Payment rails & destinations"],
  ["promotions", "Bonus rules"],
  ["content", "Announcement & bot commands"],
];

const ACTION_LABELS = {
  "platform_settings.update": "Setting changed",
  "platform_settings.reset": "Setting reset to default",
  "keno.config.update": "Keno rules changed",
  "keno.config.create": "Keno config created",
  "keno.kill_switch": "Keno kill switch",
  "keno.tier.update": "Keno tier edited",
  "keno.tier.create": "Keno tier created",
  "keno.tier.set_current": "Keno tier switched",
  "keno.paytable.create": "Keno paytable created",
};

// Only fields that differ are worth a line; a full-row "after" (a create)
// is shown as its key fields rather than dumped whole.
function diffLines(before, after) {
  if (!after || typeof after !== "object") return "";
  const keys = Object.keys(after).filter((k) => !before || JSON.stringify(before[k]) !== JSON.stringify(after[k]));
  const shown = keys.slice(0, 12);
  const lines = shown.map((key) => {
    const b = before && key in before ? JSON.stringify(before[key]) : null;
    return `<code>${escapeHtml(key)}</code>: ${b !== null ? `<span class="diff-before">${escapeHtml(b)}</span> → ` : ""}<strong>${escapeHtml(JSON.stringify(after[key]))}</strong>`;
  });
  if (keys.length > shown.length) lines.push(`…and ${keys.length - shown.length} more`);
  return lines.join("<br>");
}

export async function render(container) {
  container.innerHTML = `
    <h1>Configuration change history</h1>
    <p class="field-hint">Every configuration change: who made it, what it was before and after, and the reason
      they gave. Player and payment actions are in the audit log.</p>
    <form id="history-filter" class="inline-form">
      <label>Show <select name="scope">${SCOPES.map(([value, text]) => `<option value="${value}">${escapeHtml(text)}</option>`).join("")}</select></label>
      <label>Target contains <input type="text" name="target_id" placeholder="e.g. min_deposit_etb" /></label>
      <button type="submit" class="btn">Filter</button>
    </form>
    <div id="history-results"><p class="loading">Loading…</p></div>
  `;
  const form = container.querySelector("#history-filter");
  const results = container.querySelector("#history-results");

  async function load() {
    const params = new URLSearchParams({ limit: "200" });
    if (form.scope.value) params.set("scope", form.scope.value);
    if (form.target_id.value.trim()) params.set("target_id", form.target_id.value.trim());
    results.innerHTML = `<p class="loading">Loading…</p>`;
    let rows;
    try {
      rows = await api(`/config-history?${params}`);
    } catch (err) {
      renderError(results, err);
      return;
    }
    if (!rows.length) {
      results.innerHTML = `<p class="empty">No configuration changes match.</p>`;
      return;
    }
    results.innerHTML = `
      <table class="data-table">
        <thead><tr><th>When</th><th>Who</th><th>What</th><th>Target</th><th>Change</th><th>Reason</th></tr></thead>
        <tbody>${rows.map((r) => `
          <tr>
            <td>${escapeHtml(fmtDate(r.created_at))}</td>
            <td>${escapeHtml(r.admin_username)}</td>
            <td>${escapeHtml(ACTION_LABELS[r.action] || r.action)}</td>
            <td>${escapeHtml(r.target_type)}${r.target_id ? ` #${escapeHtml(r.target_id)}` : ""}</td>
            <td>${diffLines(r.before, r.after)}</td>
            <td>${escapeHtml(r.reason || "")}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    `;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    load();
  });
  await load();
}
