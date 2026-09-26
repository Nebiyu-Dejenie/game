import { escapeHtml } from "./api.js";

let toastTimer = null;

export function toast(message, isError = false) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("toast-error", isError);
  el.classList.add("visible");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("visible"), 3500);
}

// The one shape every screen's own fetch-error catch renders: the real
// API error detail (e.g. "role 'support' lacks 'risk:view'"), not a
// generic message -- that's deliberate (see risk.js's own comment), so
// this only consolidates the repeated markup, not the underlying
// per-screen try/catch each screen still owns.
export function renderError(container, err) {
  container.innerHTML = `<p class="error-banner">${escapeHtml(err.detail || err.message)}</p>`;
}

// Mirrors services/admin/app.py's _require_reason: the backend refuses a
// shorter reason, so the dialog says so before the round trip.
export const MIN_REASON_LENGTH = 10;

// The one confirmation step for configuration changes: shows exactly what
// will change (before → after, with a note on anything risky), and
// collects the written reason the backend requires. Resolves to the
// trimmed reason, or null if the admin cancels (Esc, Cancel, backdrop).
//
// changes: [{ label, before, after, danger?: bool, note?: string }]
export function confirmChanges({ title, intro = "", changes = [], confirmLabel = "Save changes", danger = false }) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "confirm-dialog";
    dialog.setAttribute("aria-labelledby", "confirm-dialog-title");
    const risky = danger || changes.some((c) => c.danger);
    dialog.innerHTML = `
      <form method="dialog" novalidate>
        <h2 id="confirm-dialog-title">${escapeHtml(title)}</h2>
        ${intro ? `<p class="field-hint">${escapeHtml(intro)}</p>` : ""}
        ${changes.length ? `<ul class="diff-list">${changes.map((c) => `
          <li class="${c.danger ? "diff-danger" : ""}">
            <span>${escapeHtml(c.label)}</span>
            <span class="diff-values">
              <span class="diff-before">${escapeHtml(c.before ?? "—")}</span> →
              <span class="diff-after">${escapeHtml(c.after ?? "—")}</span>
            </span>
            ${c.note ? `<span class="diff-note">${escapeHtml(c.note)}</span>` : ""}
          </li>`).join("")}</ul>` : ""}
        <label>Reason (recorded in the audit log)
          <textarea name="reason" rows="2" required minlength="${MIN_REASON_LENGTH}"
            placeholder="Why is this changing? e.g. finance asked to raise the withdrawal minimum"></textarea>
        </label>
        <span class="char-count" aria-live="polite"></span>
        <div class="action-row">
          <button type="button" class="btn btn-secondary" data-cancel>Cancel</button>
          <button type="submit" class="btn ${risky ? "btn-danger" : ""}" data-confirm disabled>${escapeHtml(confirmLabel)}</button>
        </div>
      </form>
    `;
    document.body.appendChild(dialog);
    const reasonEl = dialog.querySelector("textarea");
    const confirmBtn = dialog.querySelector("[data-confirm]");
    const countEl = dialog.querySelector(".char-count");
    let result = null;

    function update() {
      const length = reasonEl.value.trim().length;
      confirmBtn.disabled = length < MIN_REASON_LENGTH;
      countEl.textContent = length < MIN_REASON_LENGTH
        ? `${MIN_REASON_LENGTH - length} more character${MIN_REASON_LENGTH - length === 1 ? "" : "s"} needed`
        : "";
    }
    reasonEl.addEventListener("input", update);
    dialog.querySelector("[data-cancel]").addEventListener("click", () => dialog.close());
    dialog.querySelector("form").addEventListener("submit", (event) => {
      const reason = reasonEl.value.trim();
      if (reason.length < MIN_REASON_LENGTH) {
        event.preventDefault();
        return;
      }
      result = reason;
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close(); // backdrop click
    });
    dialog.addEventListener("close", () => {
      dialog.remove();
      resolve(result);
    });
    update();
    dialog.showModal();
    reasonEl.focus();
  });
}

// Formats a value for a before/after diff the way an operator reads it.
export function fmtValue(value, unit = "") {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
  return unit ? `${value} ${unit}` : String(value);
}
