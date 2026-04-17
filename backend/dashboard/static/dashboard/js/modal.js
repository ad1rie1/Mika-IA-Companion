/* Simple modal helper — appended to window.Dash.
 *
 * Usage:
 *   const m = Dash.openModal({
 *     title: "…", body: "<html>", footer: [{label:"OK", primary:true, onClick: () => {…}}]
 *   });
 *   m.close();
 *
 * Escape closes. Click on backdrop closes. Body is plain HTML string
 * inserted into .modal-body — wire listeners after open() via m.root.
 */
(function () {
  function openModal({ title, body = "", footer = [] }) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h2>${Dash.escapeHTML(title || "")}</h2>
          <button class="modal-close" aria-label="Fermer">×</button>
        </div>
        <div class="modal-body"></div>
        <div class="modal-footer"></div>
      </div>`;
    const modal = backdrop.querySelector(".modal");
    const bodyEl = backdrop.querySelector(".modal-body");
    const footerEl = backdrop.querySelector(".modal-footer");
    bodyEl.innerHTML = body;

    const api = {
      root: modal,
      body: bodyEl,
      close() {
        backdrop.remove();
        document.removeEventListener("keydown", onKey);
      },
    };

    footer.forEach(btn => {
      const el = document.createElement("button");
      el.className = "btn " + (btn.primary ? "primary" : btn.danger ? "danger" : btn.ghost ? "ghost" : "");
      el.textContent = btn.label;
      el.onclick = () => btn.onClick && btn.onClick(api);
      footerEl.appendChild(el);
    });

    function onKey(e) { if (e.key === "Escape") api.close(); }
    document.addEventListener("keydown", onKey);
    backdrop.onclick = e => { if (e.target === backdrop) api.close(); };
    backdrop.querySelector(".modal-close").onclick = () => api.close();

    document.body.appendChild(backdrop);
    return api;
  }

  async function confirm(message, { danger = false } = {}) {
    return new Promise(resolve => {
      openModal({
        title: "Confirmation",
        body: `<div class="narr">${Dash.escapeHTML(message)}</div>`,
        footer: [
          { label: "Annuler", ghost: true, onClick: m => { m.close(); resolve(false); } },
          { label: "Confirmer", primary: !danger, danger, onClick: m => { m.close(); resolve(true); } },
        ],
      });
    });
  }

  Dash.openModal = openModal;
  Dash.confirm = confirm;
})();
