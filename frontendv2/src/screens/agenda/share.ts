/**
 * Partager un agenda (la fenêtre de la maquette validée) : seul son propriétaire, et seulement avec une personne qui a
 * un compte sur ce serveur — lire, lire et préparer, s'en servir (`POST /api/moi/shares/set`, `kind: "agenda"`). Le
 * partage se fait dans Mika : il ne change rien chez Google ou Microsoft. Un agenda qu'on lui partage, ou celui de Mika,
 * dit pourquoi il ne se partage pas d'ici.
 */
import type { AgendaCalendar } from "../../api/agenda";
import type { Person } from "../../api/shares";
import { setShare, type ShareLevel } from "../../api/shares";
import { h } from "../../shell/dom";
import { closeModal, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { failureText, personAvatar } from "../../shared/kit";
import { cap } from "./dates";
import { colorOf, LEVELS, providerShort } from "./model";

const PROVIDERS: Record<string, string> = { google: "Google", microsoft: "Microsoft", caldav: "le serveur CalDAV" };

export interface ShareHooks {
  /** Relire ses agendas après un partage. */
  changed: () => void;
  /** Ne plus montrer cet agenda dans la vue (un agenda qu'on lui partage). */
  hide: (key: string) => void;
}

export function openShare(cal: AgendaCalendar, people: readonly Person[], hooks: ShareHooks): void {
  if (cal.level !== "proprietaire" || !cal.can.share) {
    const mika = cal.kind === "mika";
    const el = openModal({
      title: `Partager « ${cal.name} »`,
      size: "narrow",
      body: mika
        ? "<p>L'agenda de Mika ne se partage pas : c'est ce qu'elle retient pour toi, et ce qu'elle retient pour chacun reste à chacun.</p>"
        : `<p>Seul son propriétaire${cal.owner_name ? `, ${h(cal.owner_name)},` : ""} peut partager cet agenda. Il te l'a ouvert : ${h(LEVELS[cal.level]?.[0].toLowerCase() ?? cal.level)}.</p>`,
      foot: `<span class="grow"></span>${mika ? "" : '<button class="btn" type="button" data-agmasquer>Ne plus l\'afficher</button>'}<button class="btn primary" type="button" data-close>Compris</button>`,
    });
    el.classList.add("ag-modal");
    el.querySelector("[data-agmasquer]")?.addEventListener("click", () => {
      hooks.hide(cal.key);
      closeModal();
      toast(`« ${cal.name} » ne s'affiche plus dans ton Agenda. ${cal.owner_name || "Son propriétaire"} peut toujours retirer son partage.`, { ico: "eye-off" });
    });
    return;
  }
  let level: ShareLevel = "lire";
  let shares = [...(cal.shares ?? [])];
  const candidates = people.filter((p) => !p.owner);
  const color = colorOf(cal);
  const provider = PROVIDERS[cal.kind];
  const levels = () => Object.entries(LEVELS).map(([k, [l, d]]) => `<li class="${k === level ? "on" : ""}"><b>${h(l)}</b><span>${h(cap(d))}</span></li>`).join("");
  const lines = () => shares.length
    ? shares.map((s) => `<li>${personAvatar(s.name, "sm")}<span class="grow"><b>${h(s.name)}</b></span>
        <select class="sm-select" data-agpniv="${h(s.person)}" aria-label="Ce que ${h(s.name)} peut">${Object.entries(LEVELS).map(([x, [l]]) => `<option value="${x}"${x === s.level ? " selected" : ""}>${h(l)}</option>`).join("")}</select>
        <button class="btn xs ghost danger" type="button" data-agpret="${h(s.person)}">Retirer</button></li>`).join("")
    : '<li class="muted small">Personne pour l\'instant.</li>';
  const el = openModal({
    title: `Partager « ${cal.name} »`,
    body: `<div class="ag-share">
      <div class="ag-share-head"><span class="ag-sw lg" style="--c:var(--ag-${h(color)})"></span><div><b>${h(cal.name)}</b><small>${h(providerShort(cal))} · à toi</small></div></div>
      ${provider ? `<div class="info-line small">${ico("info", "sm")}<span>Ce partage se fait ici, dans Mika : la personne verra « ${h(cal.name)} » dans son Agenda de Mika. Il ne change rien chez ${h(provider)}, et un partage fait chez ${h(provider)} ne se voit pas ici.</span></div>` : ""}
      ${candidates.length
        ? `<div class="ag-share-add"><label class="field grow"><span>Avec qui</span><select data-agqui>${candidates.map((p) => `<option value="${h(p.person)}">${h(p.name)}</option>`).join("")}</select></label>
        <div class="field"><span>Ce que la personne peut</span><div class="seg" data-seg="agniv">${Object.entries(LEVELS).map(([k, [l]]) => `<button type="button" data-v="${k}" aria-pressed="${k === level}">${h(l)}</button>`).join("")}</div></div>
        <button class="btn primary" type="button" data-agpadd>${ico("user-plus", "sm")}Partager</button></div>
        <ul class="ag-niveaux" data-agniveaux>${levels()}</ul>`
        : '<p class="small muted">Personne d\'autre n\'a de compte sur ce serveur : il n\'y a personne avec qui le partager.</p>'}
      <p class="small muted">Seulement avec une personne qui a un compte sur ce serveur : jamais « tout le monde », jamais un lien public. Seul le propriétaire d'un agenda le partage.</p>
      <h4 class="rd-h4">Partages en cours <span class="cnt" data-agpn>${shares.length}</span></h4>
      <ul class="ag-share-list" data-agplist>${lines()}</ul>
      <p class="small muted">Ce que Mika fait de cet agenda avec chacun se règle dans <a href="#outils/droits/${encodeURIComponent(`ag:${cal.key}`)}" data-close>Outils › Droits</a>.</p></div>`,
    foot: '<span class="grow"></span><button class="btn primary" type="button" data-close>Terminé</button>',
  });
  el.classList.add("ag-modal", "ag-share-modal");
  const paint = () => {
    const list = el.querySelector<HTMLElement>("[data-agplist]");
    if (list) list.innerHTML = lines();
    const n = el.querySelector<HTMLElement>("[data-agpn]");
    if (n) n.textContent = String(shares.length);
  };
  const send = async (person: string, lv: ShareLevel | "", said: string) => {
    try {
      await setShare("agenda", cal.key, person, lv);
      toast(said, { ico: lv ? "users" : "x" });
      hooks.changed();
      return true;
    } catch (err) {
      toast(failureText(err), { ico: "alert", duration: 5000 });
      return false;
    }
  };
  el.addEventListener("mika:seg", (e) => {
    const d = (e as CustomEvent<{ name?: string; value?: string }>).detail;
    if (d.name !== "agniv") return;
    level = (d.value ?? "lire") as ShareLevel;
    const box = el.querySelector<HTMLElement>("[data-agniveaux]");
    if (box) box.innerHTML = levels();
  });
  el.querySelector("[data-agpadd]")?.addEventListener("click", () => {
    const who = el.querySelector<HTMLSelectElement>("[data-agqui]")?.value ?? "";
    const p = candidates.find((x) => x.person === who);
    if (!p) return;
    void send(who, level, `${p.name} voit « ${cal.name} » dans son Agenda : ${LEVELS[level][0].toLowerCase()}.`).then((ok) => {
      if (!ok) return;
      shares = [...shares.filter((s) => s.person !== who), { person: who, name: p.name, level: level as "lire" | "preparer" | "servir" }];
      paint();
    });
  });
  el.addEventListener("click", (e) => {
    const b = (e.target as Element).closest<HTMLElement>("[data-agpret]");
    if (!b) return;
    const who = b.dataset.agpret ?? "";
    void send(who, "", "Partage retiré : la personne ne le voit plus.").then((ok) => {
      if (!ok) return;
      shares = shares.filter((s) => s.person !== who);
      paint();
    });
  });
  el.addEventListener("change", (e) => {
    const s = (e.target as Element).closest<HTMLSelectElement>("[data-agpniv]");
    if (!s) return;
    const who = s.dataset.agpniv ?? "";
    const lv = s.value as ShareLevel;
    const name = shares.find((x) => x.person === who)?.name ?? "";
    void send(who, lv, `${name} : ${LEVELS[lv]?.[0].toLowerCase() ?? lv}.`).then((ok) => {
      if (ok) shares = shares.map((x) => (x.person === who ? { ...x, level: lv as "lire" | "preparer" | "servir" } : x));
      else paint();
    });
  });
}
