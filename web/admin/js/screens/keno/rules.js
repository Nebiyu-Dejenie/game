import { api, escapeHtml, fmtDate } from "../../api.js";
import { confirmChanges, fmtValue, renderError, toast } from "../../ui.js";

// Every field PATCH /keno/configs accepts (services/admin/keno_queries.py
// EDITABLE_CONFIG_FIELDS), grouped for an operator. Bounds shown here are
// the backend's own and only there to guide input; the backend enforces
// them, plus the cross-field rules, whatever this form sends.
const SECTIONS = [
  ["Round timing", [
    { key: "betting_seconds", label: "Betting window", unit: "s", min: 5, max: 600,
      hint: "How long players can place tickets each round." },
    { key: "draw_seconds", label: "Draw length", unit: "s", min: 3, max: 300,
      hint: "Time to reveal all 20 numbers. Under ~16 s is hard to follow on a cheap phone." },
    { key: "result_seconds", label: "Result display", unit: "s", min: 1, max: 300,
      hint: "How long the result stays up before the next round opens." },
  ]],
  ["Picks", [
    { key: "min_picks", label: "Minimum picks", unit: "", min: 1, max: 10 },
    { key: "max_picks", label: "Maximum picks", unit: "", min: 1, max: 10,
      hint: "The current tier can lower this further; it can't raise it." },
  ]],
  ["Per-player limits", [
    { key: "max_tickets_per_user_per_round", label: "Tickets per player per round", unit: "", min: 1, max: 50,
      risky: { up: "Players can put more tickets into one round." } },
    { key: "per_user_round_capacity_share_bps", label: "One player's share of round capacity", unit: "bps", min: 1, max: 10000,
      pct: true, risky: { up: "One player can take a bigger share of a round's exposure." } },
    { key: "max_autoplay_rounds", label: "Autoplay rounds, maximum", unit: "rounds", min: 1, max: 100,
      hint: "The longest multi-race a player can start. Hard ceiling 100.",
      risky: { up: "Players can commit to longer unattended sequences." } },
  ]],
  ["Money and risk", [
    { key: "jackpot_diversion_bps", label: "Jackpot diversion", unit: "bps", min: 0, max: 1000, pct: true,
      hint: "Share of every stake diverted to the jackpot pool." },
    { key: "reserve_withdrawal_floor", label: "Reserve withdrawal floor", unit: "ETB", money: true,
      hint: "The prize reserve can't be withdrawn below this.",
      risky: { down: "Less of the prize reserve is protected from withdrawal." } },
    { key: "daily_payout_circuit_breaker_multiple", label: "Payout circuit breaker", unit: "× expected", decimal: true,
      hint: "Demote the tier when 24-hour payouts exceed this multiple of expected. Between 1 and 50.",
      risky: { up: "The circuit breaker trips later." } },
    { key: "rtp_floor_bps", label: "RTP guardrail floor", unit: "bps", min: 7500, max: 9700, pct: true,
      hint: "Paytables with a lower return can't be saved." },
    { key: "rtp_ceiling_bps", label: "RTP guardrail ceiling", unit: "bps", min: 7500, max: 9700, pct: true,
      hint: "Paytables with a higher return can't be saved.",
      risky: { up: "Paytables paying players more can be activated." } },
  ]],
  ["Access", [
    { key: "beta_restricted", label: "Only allowlisted players can play", bool: true,
      risky: { off: "Opens Keno to every player (when Keno is enabled)." } },
  ]],
];

const FIELDS = SECTIONS.flatMap(([, fields]) => fields);

function display(field, value) {
  if (field.bool) return value ? "Yes" : "No";
  if (field.pct) return `${value} bps (${(Number(value) / 100).toFixed(2)}%)`;
  return fmtValue(value, field.unit);
}

function riskNote(field, before, after) {
  if (!field.risky) return null;
  if (field.bool) return field.risky.off && before && !after ? field.risky.off : null;
  if (field.risky.up && Number(after) > Number(before)) return field.risky.up;
  if (field.risky.down && Number(after) < Number(before)) return field.risky.down;
  return null;
}

export async function render(container, { role }) {
  let config;
  let history;
  try {
    config = await api("/keno/configs/active");
    // Change history needs settings:view, which support (who can read
    // Keno) doesn't have -- the rules still render without it.
    history = await api("/config-history?scope=keno&limit=15").catch(() => null);
  } catch (err) {
    renderError(container, err);
    return;
  }
  const canEdit = role === "superadmin";

  container.innerHTML = `
    <p class="field-hint">Active config: version ${escapeHtml(config.version)}, since ${escapeHtml(fmtDate(config.effective_from))}.
      Saving creates a new version that takes effect from the <strong>next round</strong>; a round in progress keeps
      the rules it started with. Keno on/off is the kill switch on the Overview tab.
      ${canEdit ? "" : "<strong>Read-only:</strong> only a superadmin can change Keno rules."}</p>
    <form id="keno-rules-form" class="keno-form" novalidate>
      ${SECTIONS.map(([title, fields]) => `
        <div class="form-section-title">${escapeHtml(title)}</div>
        <div class="detail-panel detail-grid">
          ${fields.map((f) => f.bool ? `
            <label style="flex-direction:row;align-items:center;gap:0.5rem">
              <input type="checkbox" name="${f.key}" ${config[f.key] ? "checked" : ""} ${canEdit ? "" : "disabled"} />
              ${escapeHtml(f.label)}
            </label>` : `
            <label>${escapeHtml(f.label)}${f.unit ? ` (${escapeHtml(f.unit)})` : ""}
              <input name="${f.key}" type="text" inputmode="${f.money || f.decimal ? "decimal" : "numeric"}"
                value="${escapeHtml(config[f.key])}" ${canEdit ? "" : "disabled"} autocomplete="off" />
              ${f.hint ? `<span class="field-hint">${escapeHtml(f.hint)}</span>` : ""}
              ${f.pct ? `<span class="derived-value" data-pct-for="${f.key}"></span>` : ""}
            </label>`).join("")}
          ${title === "Round timing" ? `<div class="derived-value" id="keno-cycle" aria-live="polite"></div>` : ""}
        </div>`).join("")}
      ${canEdit ? `
        <div class="sticky-actions">
          <span id="keno-rules-dirty" class="field-hint" aria-live="polite">No unsaved changes</span>
          <button type="button" class="btn btn-secondary" id="keno-rules-discard" disabled>Discard</button>
          <button type="submit" class="btn" id="keno-rules-review" disabled>Review and save…</button>
        </div>` : ""}
    </form>

    <h2>Recent Keno configuration changes</h2>
    <div id="keno-rules-history"></div>
  `;

  const form = container.querySelector("#keno-rules-form");

  function readValue(field) {
    const input = form.elements[field.key];
    if (field.bool) return input.checked;
    const raw = input.value.trim();
    if (field.money || field.decimal) return raw;
    return /^-?\d+$/.test(raw) ? Number(raw) : raw;
  }

  function sameValue(field, a, b) {
    if (field.money || field.decimal) return Number(a) === Number(b) && String(a).trim() !== "";
    return a === b;
  }

  function pending() {
    const changes = {};
    for (const field of FIELDS) {
      const value = readValue(field);
      if (!sameValue(field, value, config[field.key])) changes[field.key] = value;
    }
    return changes;
  }

  function refreshDerived() {
    const b = Number(form.elements.betting_seconds.value) || 0;
    const d = Number(form.elements.draw_seconds.value) || 0;
    const r = Number(form.elements.result_seconds.value) || 0;
    const perBall = d > 0 ? (d / 20).toFixed(2) : "—";
    container.querySelector("#keno-cycle").textContent =
      `One round = ${b + d + r} s (betting ${b} + draw ${d} + result ${r}); ${perBall} s per drawn number.`;
    for (const el of container.querySelectorAll("[data-pct-for]")) {
      const v = Number(form.elements[el.dataset.pctFor].value);
      el.textContent = Number.isFinite(v) ? `= ${(v / 100).toFixed(2)}%` : "";
    }
    if (!canEdit) return;
    const count = Object.keys(pending()).length;
    container.querySelector("#keno-rules-dirty").textContent =
      count ? `${count} unsaved change${count === 1 ? "" : "s"}` : "No unsaved changes";
    container.querySelector("#keno-rules-review").disabled = count === 0;
    container.querySelector("#keno-rules-discard").disabled = count === 0;
  }

  form.addEventListener("input", refreshDerived);
  form.addEventListener("change", refreshDerived);
  refreshDerived();
  renderHistory(container.querySelector("#keno-rules-history"), history);
  if (!canEdit) return;

  container.querySelector("#keno-rules-discard").addEventListener("click", () => render(container, { role }));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const changes = pending();
    if (!Object.keys(changes).length) return;
    const diff = Object.entries(changes).map(([key, after]) => {
      const field = FIELDS.find((f) => f.key === key);
      const note = riskNote(field, config[key], after);
      return { label: field.label, before: display(field, config[key]), after: display(field, after), danger: !!note, note };
    });
    const timing = ["betting_seconds", "draw_seconds", "result_seconds"].some((k) => k in changes);
    const reason = await confirmChanges({
      title: "Change Keno rules",
      intro: `Takes effect from the next round.${timing ? " The round length is recalculated from the three phases." : ""}`,
      changes: diff,
    });
    if (!reason) return;
    try {
      const saved = await api("/keno/configs", { method: "PATCH", body: { changes, reason } });
      toast(`Keno rules saved as version ${saved.version}`);
      await render(container, { role });
    } catch (err) {
      toast(err.detail || err.message, true);
    }
  });
}

function renderHistory(el, rows) {
  if (rows === null) {
    el.innerHTML = `<p class="empty">Your role can't view configuration history.</p>`;
    return;
  }
  if (!rows.length) {
    el.innerHTML = `<p class="empty">No Keno configuration changes recorded yet.</p>`;
    return;
  }
  el.innerHTML = `
    <table class="data-table">
      <thead><tr><th>When</th><th>Who</th><th>What</th><th>Reason</th></tr></thead>
      <tbody>${rows.map((r) => `
        <tr>
          <td>${escapeHtml(fmtDate(r.created_at))}</td>
          <td>${escapeHtml(r.admin_username)}</td>
          <td>${escapeHtml(r.action)}${r.after && r.before
            ? ": " + Object.keys(r.after).filter((k) => k in r.before).map((k) =>
                `${escapeHtml(k)} ${escapeHtml(JSON.stringify(r.before[k]))} → ${escapeHtml(JSON.stringify(r.after[k]))}`).join(", ")
            : ""}</td>
          <td>${escapeHtml(r.reason || "")}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}
