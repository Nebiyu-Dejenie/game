import { api, escapeHtml, fmtDate, getRole } from "../api.js";
import { confirmChanges, renderError, toast } from "../ui.js";

export const label = "Platform settings";

// Which direction of change weakens a control, per setting -- the confirm
// dialog flags those so the admin reads them twice. The backend enforces
// bounds regardless; this is only about what deserves a second look.
const RISKY_DIRECTION = {
  auto_approve_withdraw_etb: { up: "More money can leave without anyone reviewing it." },
  kyc_required_above_etb: { up: "Larger withdrawals will go out without identity verification." },
  withdraw_chargeback_window_minutes: { down: "Freshly deposited money can be withdrawn sooner." },
  max_withdrawals_per_day: { up: "Players can make more withdrawal requests per day." },
  daily_deposit_cap_etb: { up: "Players can deposit more per day." },
  rg_limit_increase_delay_hours: { down: "Weakens player protection: raised limits apply sooner." },
  rg_self_exclusion_minimum_days: { down: "Weakens player protection: shorter self-exclusions allowed." },
};

function riskNote(key, before, after) {
  const rule = RISKY_DIRECTION[key];
  if (!rule) return null;
  const b = Number(before);
  const a = Number(after);
  if (rule.up && a > b) return rule.up;
  if (rule.down && a < b) return rule.down;
  return null;
}

function unitLabel(setting) {
  return setting.unit === "ETB" ? "ETB" : setting.unit;
}

export async function render(container) {
  const canEdit = getRole() === "superadmin";
  let data;
  let history;
  try {
    [data, history] = await Promise.all([api("/settings"), api("/config-history?scope=platform&limit=20")]);
  } catch (err) {
    renderError(container, err);
    return;
  }
  const byKey = new Map();
  for (const category of data.categories) for (const s of category.settings) byKey.set(s.key, s);

  container.innerHTML = `
    <h1>Platform settings</h1>
    <p class="field-hint">Limits every deposit, withdrawal and responsible-gaming check reads on each request.
      A change applies to the next request. Money values are exact to the cent.
      ${canEdit ? "" : "<strong>Read-only:</strong> only a superadmin can change these."}</p>
    <form id="settings-form" novalidate>
      ${data.categories.map((category) => `
        <section class="settings-category" aria-labelledby="cat-${escapeHtml(category.key)}">
          <h2 id="cat-${escapeHtml(category.key)}">${escapeHtml(category.label)}</h2>
          ${category.settings.map((s) => `
            <div class="setting-row" data-key="${escapeHtml(s.key)}">
              <div>
                <label class="setting-label" for="setting-${escapeHtml(s.key)}">${escapeHtml(s.label)}</label>
                <div class="setting-desc">${escapeHtml(s.description)}</div>
                <div class="setting-meta">
                  ${s.overridden
                    ? `Changed by <strong>${escapeHtml(s.updated_by)}</strong> ${escapeHtml(fmtDate(s.updated_at))} · default ${escapeHtml(s.default)} ${escapeHtml(unitLabel(s))}`
                    : `Using the default`}
                  · allowed ${escapeHtml(s.minimum)}–${escapeHtml(s.maximum)} ${escapeHtml(unitLabel(s))}
                </div>
              </div>
              <div class="setting-control">
                <div class="input-with-unit">
                  <input id="setting-${escapeHtml(s.key)}" name="${escapeHtml(s.key)}"
                    type="text" inputmode="${s.kind === "money" ? "decimal" : "numeric"}"
                    value="${escapeHtml(s.value)}" ${canEdit ? "" : "disabled"} autocomplete="off" />
                  <span class="unit">${escapeHtml(unitLabel(s))}</span>
                </div>
                <span class="setting-effective" aria-live="polite"></span>
                ${canEdit && s.overridden ? `<button type="button" class="btn btn-secondary btn-sm" data-reset="${escapeHtml(s.key)}">Reset to default (${escapeHtml(s.default)})</button>` : ""}
              </div>
            </div>
          `).join("")}
        </section>
      `).join("")}
      ${canEdit ? `
        <div class="sticky-actions">
          <span id="settings-dirty" class="field-hint" aria-live="polite">No unsaved changes</span>
          <button type="button" class="btn btn-secondary" id="settings-discard" disabled>Discard</button>
          <button type="submit" class="btn" id="settings-review" disabled>Review and save…</button>
        </div>` : ""}
    </form>

    <h2>Recent changes</h2>
    <div id="settings-history"></div>
  `;

  renderHistory(container.querySelector("#settings-history"), history, byKey);
  if (!canEdit) return;

  const form = container.querySelector("#settings-form");
  const dirtyEl = container.querySelector("#settings-dirty");
  const reviewBtn = container.querySelector("#settings-review");
  const discardBtn = container.querySelector("#settings-discard");

  function pendingChanges() {
    const changes = {};
    for (const [key, s] of byKey) {
      const raw = form.elements[key].value.trim();
      if (raw !== String(s.value)) changes[key] = s.kind === "int" && /^\d+$/.test(raw) ? Number(raw) : raw;
    }
    return changes;
  }

  function refreshDirty() {
    const changes = pendingChanges();
    const count = Object.keys(changes).length;
    for (const row of form.querySelectorAll(".setting-row")) {
      row.classList.toggle("changed", row.dataset.key in changes);
    }
    dirtyEl.textContent = count ? `${count} unsaved change${count === 1 ? "" : "s"}` : "No unsaved changes";
    reviewBtn.disabled = count === 0;
    discardBtn.disabled = count === 0;
  }

  form.addEventListener("input", refreshDirty);
  discardBtn.addEventListener("click", () => render(container));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const changes = pendingChanges();
    if (!Object.keys(changes).length) return;
    const diff = Object.entries(changes).map(([key, after]) => {
      const s = byKey.get(key);
      const note = riskNote(key, s.value, after);
      return { label: s.label, before: `${s.value} ${unitLabel(s)}`, after: `${after} ${unitLabel(s)}`, danger: !!note, note };
    });
    const reason = await confirmChanges({
      title: "Change platform settings",
      intro: "These apply to the next deposit, withdrawal or limit change, for every player.",
      changes: diff,
    });
    if (!reason) return;
    try {
      await api("/settings", { method: "PATCH", body: { changes, reason } });
      toast("Settings saved");
      await render(container);
    } catch (err) {
      toast(err.detail || err.message, true);
    }
  });

  for (const btn of container.querySelectorAll("[data-reset]")) {
    btn.addEventListener("click", async () => {
      const s = byKey.get(btn.dataset.reset);
      const note = riskNote(s.key, s.value, s.default);
      const reason = await confirmChanges({
        title: `Reset “${s.label}”`,
        changes: [{ label: s.label, before: `${s.value} ${unitLabel(s)}`, after: `${s.default} ${unitLabel(s)} (default)`, danger: !!note, note }],
        confirmLabel: "Reset to default",
      });
      if (!reason) return;
      try {
        await api(`/settings/${encodeURIComponent(s.key)}/reset`, { method: "POST", body: { reason } });
        toast(`${s.label} reset to its default`);
        await render(container);
      } catch (err) {
        toast(err.detail || err.message, true);
      }
    });
  }
}

function renderHistory(el, history, byKey) {
  if (!history.length) {
    el.innerHTML = `<p class="empty">No setting has been changed from its default yet.</p>`;
    return;
  }
  el.innerHTML = `
    <table class="data-table">
      <thead><tr><th>When</th><th>Who</th><th>Change</th><th>Reason</th></tr></thead>
      <tbody>${history.map((h) => `
        <tr>
          <td>${escapeHtml(fmtDate(h.created_at))}</td>
          <td>${escapeHtml(h.admin_username)}</td>
          <td>${Object.keys(h.after || {}).map((key) => `
            ${escapeHtml(byKey.get(key)?.label || key)}: <span class="diff-before">${escapeHtml(h.before?.[key] ?? "—")}</span>
            → <strong>${escapeHtml(h.after[key])}</strong>${h.action.endsWith(".reset") ? " (default)" : ""}`).join("<br>")}</td>
          <td>${escapeHtml(h.reason || "")}</td>
        </tr>`).join("")}
      </tbody>
    </table>
  `;
}
