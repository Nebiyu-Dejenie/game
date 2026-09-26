import { api, escapeHtml, fmtDate } from "../../api.js";
import { confirmChanges, fmtValue, renderError, toast } from "../../ui.js";

// Latest version per tier_number -- keno_risk_tiers.version is scoped per
// tier_number, not shared across the ladder (see docs/keno/02-data-model.md).
function latestPerTier(tiers) {
  const best = new Map();
  for (const tier of tiers) {
    const current = best.get(tier.tier_number);
    if (!current || tier.version > current.version) best.set(tier.tier_number, tier);
  }
  return [...best.values()].sort((a, b) => a.tier_number - b.tier_number);
}

export async function render(container, { role }) {
  let tiers;
  let allowlist;
  try {
    [tiers, allowlist] = await Promise.all([api("/keno/tiers"), api("/keno/beta-allowlist")]);
  } catch (err) {
    renderError(container, err);
    return;
  }
  const superadmin = role === "superadmin";
  const ladder = latestPerTier(tiers);
  const current = tiers.find((t) => t.is_current);

  // The engine pins a specific tier *version* (keno_tier_state.current_tier_id),
  // so editing the current tier creates a newer version it won't use until
  // someone adopts it -- that case gets its own label, not "Make current".
  function tierAction(t) {
    if (current && current.id === t.id) return "";
    const adopting = current && current.tier_number === t.tier_number;
    return `<button class="btn btn-secondary" data-set-tier="${t.id}" data-tier-number="${t.tier_number}">
      ${adopting ? `Adopt latest version (v${t.version})` : "Make current"}</button>`;
  }

  container.innerHTML = `
    <h2>Risk tier ladder</h2>
    <p class="field-hint">Promotion needs the reserve above a tier's minimum for 7 consecutive days; demotion is
      immediate. A tier change only ever affects the next round.</p>
    ${current && ladder.some((t) => t.tier_number === current.tier_number && t.id !== current.id)
      ? `<p class="warning-text">Tier ${current.tier_number} has a newer version
          (v${escapeHtml(String(ladder.find((t) => t.tier_number === current.tier_number).version))}) that is not in use --
          rounds still run on v${escapeHtml(String(current.version))} until it is adopted.</p>` : ""}
    <table class="data-table">
      <thead><tr><th>Tier</th><th>Min reserve</th><th>Max picks</th><th>Top multiplier</th><th>Stakes</th>
        <th>Max win/ticket</th><th>Round exposure cap</th><th>Profile</th><th></th></tr></thead>
      <tbody>${ladder.map((t) => `<tr>
        <td>${t.tier_number}${current && current.tier_number === t.tier_number ? ` <span class="badge badge-active">current</span>` : ""}</td>
        <td>${escapeHtml(t.min_reserve)}</td><td>${t.max_pick_count}</td><td>${escapeHtml(t.max_top_multiplier)}×</td>
        <td>${t.stake_options.map((st) => `${escapeHtml(st)}${t.default_stake !== null && Number(st) === Number(t.default_stake) ? "★" : ""}`).join(", ")}
          ${(t.disabled_stake_options || []).length ? `<br><span class="pill pill-off">off: ${t.disabled_stake_options.map(escapeHtml).join(", ")}</span>` : ""}</td>
        <td>${escapeHtml(t.max_win_per_ticket)}</td>
        <td>${(Number(t.max_round_exposure_pct) * 100).toFixed(1)}% of reserve</td><td>${escapeHtml(t.paytable_profile)}</td>
        <td>${superadmin ? `<button class="btn btn-secondary btn-sm" data-edit-tier="${t.id}">Edit stakes &amp; limits</button> ${tierAction(t)}` : ""}</td>
      </tr>`).join("")}
      </tbody>
    </table>
    <p class="field-hint">★ = the stake the Mini App preselects. Stakes marked “off” are kept for re-enabling but
      refused for tickets.</p>
    <div id="tier-editor"></div>

    <h2>Beta allowlist</h2>
    <p class="field-hint">While the active config has <em>beta allowlist enforced</em>, only these players can see or
      play Keno, even with Keno enabled.</p>
    ${allowlist.length ? `<table class="data-table">
      <thead><tr><th>User ID</th><th>Reason</th><th>Added by admin</th><th>Added</th><th></th></tr></thead>
      <tbody>${allowlist.map((row) => `<tr>
        <td>${row.user_id}</td><td>${escapeHtml(row.reason)}</td><td>${row.added_by_admin_id}</td><td>${fmtDate(row.created_at)}</td>
        <td>${superadmin ? `<button class="btn btn-danger" data-remove-user="${row.user_id}">Remove</button>` : ""}</td>
      </tr>`).join("")}</tbody></table>` : `<p class="empty">Nobody is on the allowlist.</p>`}
    ${superadmin ? `
      <form id="allowlist-form" class="detail-panel inline-form">
        <label>User ID <input type="number" name="user_id" required min="1" /></label>
        <label>Reason <input type="text" name="reason" required minlength="10" /></label>
        <button type="submit" class="btn">Add to allowlist</button>
      </form>` : ""}
  `;
  if (!superadmin) return;

  async function act(fn, success) {
    try {
      await fn();
      toast(success);
      await render(container, { role });
    } catch (err) {
      toast(err.detail || err.message, true);
    }
  }

  for (const btn of container.querySelectorAll("[data-edit-tier]")) {
    btn.addEventListener("click", () => {
      const tier = ladder.find((t) => t.id === Number(btn.dataset.editTier));
      const isCurrentNumber = current && current.tier_number === tier.tier_number;
      openTierEditor(container.querySelector("#tier-editor"), tier, {
        isCurrentNumber,
        onSaved: () => render(container, { role }),
      });
    });
  }

  for (const btn of container.querySelectorAll("[data-set-tier]")) {
    btn.addEventListener("click", () => {
      const reason = prompt(`Reason for overriding the current tier to tier ${btn.dataset.tierNumber}:`);
      if (!reason) return;
      act(() => api("/keno/tiers/set-current", { method: "POST", body: { tier_id: Number(btn.dataset.setTier), reason } }),
        `Tier ${btn.dataset.tierNumber} is now current`);
    });
  }
  for (const btn of container.querySelectorAll("[data-remove-user]")) {
    btn.addEventListener("click", () => {
      const reason = prompt(`Reason for removing user ${btn.dataset.removeUser} from the allowlist:`);
      if (!reason) return;
      const params = new URLSearchParams({ reason });
      act(() => api(`/keno/beta-allowlist/${btn.dataset.removeUser}?${params}`, { method: "DELETE" }), "Removed");
    });
  }
  container.querySelector("#allowlist-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const body = { user_id: Number(e.target.user_id.value), reason: e.target.reason.value.trim() };
    act(() => api("/keno/beta-allowlist", { method: "POST", body }), `User ${body.user_id} added`);
  });
}


// --- stake & limit editor ----------------------------------------------------
//
// Edits the latest version of one tier. Saving writes a new tier version
// (PATCH /keno/tiers/{id}); with "use from the next round" ticked and this
// tier being the one in play, it also becomes current in the same
// transaction. The backend validates everything again: stakes positive,
// exact cents, unique, at most 12; default among the enabled ones; max win
// at least the largest stake; paytables present and under the top cap.

const LIMIT_FIELDS = [
  { key: "min_reserve", label: "Minimum reserve for this tier", unit: "ETB", money: true },
  { key: "max_pick_count", label: "Maximum picks", unit: "", int: true },
  { key: "max_top_multiplier", label: "Top multiplier cap", unit: "×", money: true },
  { key: "max_win_per_ticket", label: "Maximum win per ticket", unit: "ETB", money: true },
  { key: "max_round_exposure_pct", label: "Round exposure cap (fraction of reserve, 0–1)", unit: "", money: true },
];

function sameAmount(a, b) {
  return Number(a) === Number(b);
}

function openTierEditor(panel, tier, { isCurrentNumber, onSaved }) {
  // Working copy: enabled stakes in display order, disabled ones kept aside.
  const state = {
    enabled: tier.stake_options.map(String),
    disabled: (tier.disabled_stake_options || []).map(String),
    defaultStake: tier.default_stake !== null ? String(tier.default_stake) : null,
  };

  function draw() {
    const all = [
      ...state.enabled.map((amount, index) => ({ amount, enabled: true, index })),
      ...state.disabled.map((amount) => ({ amount, enabled: false })),
    ];
    panel.innerHTML = `
      <form class="detail-panel keno-form" id="tier-edit-form" novalidate>
        <h2>Tier ${tier.tier_number} — stakes and limits <span class="field-hint">(editing v${tier.version})</span></h2>
        <div class="form-section-title">Stakes players can choose</div>
        <p class="field-hint">Order here is the order of the chips in the Mini App. Turn a stake off to stop new tickets
          at that amount without losing it from the list.</p>
        <ul class="stake-list" aria-label="Stakes">
          ${all.map((item) => `
            <li class="stake-item ${item.enabled ? "" : "disabled"}">
              <span class="stake-amount">${escapeHtml(item.amount)} ETB</span>
              ${item.enabled
                ? `<label style="flex-direction:row;align-items:center;gap:0.3rem">
                     <input type="radio" name="default_stake" value="${escapeHtml(item.amount)}"
                       ${state.defaultStake !== null && sameAmount(state.defaultStake, item.amount) ? "checked" : ""} /> default</label>`
                : `<span class="pill pill-off">off</span>`}
              <span class="spacer"></span>
              ${item.enabled ? `
                <button type="button" class="icon-btn" data-move="${item.index}" data-dir="-1" aria-label="Move ${escapeHtml(item.amount)} up" ${item.index === 0 ? "disabled" : ""}>↑</button>
                <button type="button" class="icon-btn" data-move="${item.index}" data-dir="1" aria-label="Move ${escapeHtml(item.amount)} down" ${item.index === state.enabled.length - 1 ? "disabled" : ""}>↓</button>` : ""}
              <button type="button" class="btn btn-secondary btn-sm" data-toggle="${escapeHtml(item.amount)}">${item.enabled ? "Turn off" : "Turn on"}</button>
              <button type="button" class="btn btn-danger btn-sm" data-remove="${escapeHtml(item.amount)}" aria-label="Remove ${escapeHtml(item.amount)}">Remove</button>
            </li>`).join("")}
        </ul>
        <div class="inline-form">
          <label>Add a stake (ETB) <input type="text" inputmode="decimal" id="new-stake" placeholder="e.g. 25.00" /></label>
          <button type="button" class="btn btn-secondary" id="add-stake">Add</button>
          <button type="button" class="btn btn-secondary" id="clear-default">No default</button>
        </div>
        <p class="derived-value" id="stake-summary"></p>

        <div class="form-section-title">Limits</div>
        <div class="detail-grid">
          ${LIMIT_FIELDS.map((f) => `
            <label>${escapeHtml(f.label)}${f.unit ? ` (${escapeHtml(f.unit)})` : ""}
              <input name="${f.key}" type="text" inputmode="${f.int ? "numeric" : "decimal"}" value="${escapeHtml(tier[f.key])}" autocomplete="off" />
            </label>`).join("")}
          <label>Paytable profile
            <select name="paytable_profile">
              ${["low_variance", "standard"].map((p) => `<option value="${p}" ${tier.paytable_profile === p ? "selected" : ""}>${p}</option>`).join("")}
            </select>
          </label>
        </div>
        ${isCurrentNumber ? `
          <label style="flex-direction:row;align-items:center;gap:0.5rem;margin-top:0.75rem">
            <input type="checkbox" name="adopt" checked /> Use this from the next round (this tier is in play)
          </label>` : `<p class="field-hint">This tier isn't in play, so the change applies whenever it next becomes current.</p>`}
        <div class="action-row">
          <button type="button" class="btn btn-secondary" id="tier-edit-cancel">Cancel</button>
          <button type="submit" class="btn">Review and save…</button>
        </div>
      </form>`;

    const summary = panel.querySelector("#stake-summary");
    const amounts = state.enabled.map(Number);
    summary.textContent = amounts.length
      ? `Players can stake ${Math.min(...amounts)}–${Math.max(...amounts)} ETB (${amounts.length} option${amounts.length === 1 ? "" : "s"}).`
      : "No stake is enabled: players couldn't bet at all. Turn at least one on.";

    for (const btn of panel.querySelectorAll("[data-move]")) {
      btn.addEventListener("click", () => {
        const i = Number(btn.dataset.move);
        const j = i + Number(btn.dataset.dir);
        [state.enabled[i], state.enabled[j]] = [state.enabled[j], state.enabled[i]];
        draw();
      });
    }
    for (const btn of panel.querySelectorAll("[data-toggle]")) {
      btn.addEventListener("click", () => {
        const amount = btn.dataset.toggle;
        if (state.enabled.includes(amount)) {
          state.enabled = state.enabled.filter((a) => a !== amount);
          state.disabled.push(amount);
          if (state.defaultStake !== null && sameAmount(state.defaultStake, amount)) state.defaultStake = null;
        } else {
          state.disabled = state.disabled.filter((a) => a !== amount);
          state.enabled.push(amount);
        }
        draw();
      });
    }
    for (const btn of panel.querySelectorAll("[data-remove]")) {
      btn.addEventListener("click", () => {
        const amount = btn.dataset.remove;
        state.enabled = state.enabled.filter((a) => a !== amount);
        state.disabled = state.disabled.filter((a) => a !== amount);
        if (state.defaultStake !== null && sameAmount(state.defaultStake, amount)) state.defaultStake = null;
        draw();
      });
    }
    for (const radio of panel.querySelectorAll('input[name="default_stake"]')) {
      radio.addEventListener("change", () => { state.defaultStake = radio.value; });
    }
    panel.querySelector("#clear-default").addEventListener("click", () => { state.defaultStake = null; draw(); });
    panel.querySelector("#add-stake").addEventListener("click", () => {
      const raw = panel.querySelector("#new-stake").value.trim();
      if (!/^\d+(\.\d{1,2})?$/.test(raw) || Number(raw) <= 0) {
        toast("Enter a stake like 25 or 25.50 (more than zero, at most two decimals).", true);
        return;
      }
      const amount = Number(raw).toFixed(2);
      if ([...state.enabled, ...state.disabled].some((a) => sameAmount(a, amount))) {
        toast(`${amount} ETB is already on the list.`, true);
        return;
      }
      state.enabled.push(amount);
      draw();
    });
    panel.querySelector("#tier-edit-cancel").addEventListener("click", () => { panel.innerHTML = ""; });
    panel.querySelector("#tier-edit-form").addEventListener("submit", (event) => {
      event.preventDefault();
      save(event.target);
    });
  }

  async function save(form) {
    const changes = {};
    const labels = [];
    const listChanged = (a, b) => a.length !== b.length || a.some((v, i) => !sameAmount(v, b[i]));
    if (listChanged(state.enabled, tier.stake_options)) {
      changes.stake_options = state.enabled;
      labels.push({ label: "Stakes offered (in order)", before: fmtValue(tier.stake_options), after: fmtValue(state.enabled) });
    }
    if (listChanged(state.disabled, tier.disabled_stake_options || [])) {
      changes.disabled_stake_options = state.disabled;
      labels.push({ label: "Stakes turned off", before: fmtValue(tier.disabled_stake_options || []), after: fmtValue(state.disabled) });
    }
    const beforeDefault = tier.default_stake === null ? null : String(tier.default_stake);
    if ((beforeDefault === null) !== (state.defaultStake === null)
        || (beforeDefault !== null && !sameAmount(beforeDefault, state.defaultStake))) {
      changes.default_stake = state.defaultStake;
      labels.push({ label: "Default stake", before: fmtValue(beforeDefault), after: fmtValue(state.defaultStake) });
    }
    for (const f of LIMIT_FIELDS) {
      const raw = form.elements[f.key].value.trim();
      if (!sameAmount(raw, tier[f.key]) || raw === "") {
        changes[f.key] = f.int && /^\d+$/.test(raw) ? Number(raw) : raw;
        const riskier = (f.key === "max_win_per_ticket" || f.key === "max_top_multiplier" || f.key === "max_round_exposure_pct")
          && Number(raw) > Number(tier[f.key]);
        labels.push({ label: f.label, before: fmtValue(tier[f.key], f.unit), after: fmtValue(raw, f.unit),
          danger: riskier, note: riskier ? "Raises how much a single ticket or round can pay out." : undefined });
      }
    }
    if (form.elements.paytable_profile.value !== tier.paytable_profile) {
      changes.paytable_profile = form.elements.paytable_profile.value;
      labels.push({ label: "Paytable profile", before: tier.paytable_profile, after: changes.paytable_profile });
    }
    if (!Object.keys(changes).length) {
      toast("Nothing changed.");
      return;
    }
    const adopt = Boolean(form.elements.adopt?.checked);
    const reason = await confirmChanges({
      title: `Save tier ${tier.tier_number}`,
      intro: adopt
        ? "Saved as a new tier version and used from the next round. A round in progress keeps its stakes."
        : "Saved as a new tier version.",
      changes: labels,
    });
    if (!reason) return;
    try {
      const saved = await api(`/keno/tiers/${tier.id}`, { method: "PATCH", body: { changes, reason, adopt } });
      const warnings = saved.warnings || [];
      toast(`Tier ${tier.tier_number} saved as v${saved.version}${saved.adopted ? " and in use from the next round" : ""}`
        + (warnings.length ? `. Note: ${warnings.join(" ")}` : ""));
      onSaved();
    } catch (err) {
      toast(err.detail || err.message, true);
    }
  }

  draw();
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}
