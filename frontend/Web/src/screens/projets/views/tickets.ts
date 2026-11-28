/**
 * L'onglet Tickets d'une fiche (pur) : la liste et ses filtres, le détail en volets (Description, Plan, Fil,
 * Historique — l'histoire de ses étapes, rejouée par le serveur, et ce qui est arrivé à ses objectifs), le panneau (son
 * parcours en six étapes, `journey` ; ses propriétés ; ce qui est lié, `linked` : son objectif, sa pull request avec son
 * statut, son issue avec son état), et ses
 * formulaires (Nouveau ticket, Modifier). Les gestes du moment sont ceux que le serveur ouvre (`can`) : accepter,
 * écarter, valider ou refuser le plan — en nommant le plan lu —, fermer, rouvrir, noter, répondre.
 */
import type { ActivityPage, Entry, EntryDetail, EntryHistory, EntryPage, Listing, Passage, Sheet, ThreadNote } from "../../../api/projects";
import { h } from "../../../shell/dom";
import { ico, type IconName } from "../../../shell/icons";
import { plural } from "../gestures";
import { markdown } from "../md";
import { authorAvatar, banner, bubble, empty, event, F, filters, form, head, hint, linked, nothing, OUTSIDE, outside, planBlock, props, pullCard, refusal, sc, st, trio, type Trio } from "../parts";
import { sheetRoute } from "../routes";
import { fieldErrorsAt, refusalAt, ticketList } from "../state";
import { moment, when } from "../time";
import { objectiveTone, ticketTone, type Tone } from "../tones";
import { happeningLink, KIND_ICON } from "./activity";
import { waitingBlock, type Ctx, type Got } from "./todo";

/** Ce que l'Historique d'un ticket lit en plus : l'histoire de ses étapes, et le fil d'activité filtré sur lui. */
export interface TicketStory {
  history: Got<EntryHistory>;
  around: Got<ActivityPage>;
}

/** Les champs d'un ticket : ses sortes et ses priorités sont celles que la fiche sert, avec leurs mots. */
export function ticketFields(list: Listing | null, e: EntryDetail | null, errors: Record<string, string>, born = ""): string {
  const kinds = (list?.kinds ?? []).map((k) => [k.code, k.label] as const);
  const priorities = (list?.priorities ?? []).map((k) => [k.code, k.label] as const);
  return `${F.text("title", "Titre", e?.title ?? "", { required: true, hint: "Ce qu'il faut faire, en une ligne", error: errors.title })}
    ${F.two(kinds.length ? F.select("kind", "Sorte", e?.kind ?? list?.kind_default ?? "", kinds, { error: errors.kind }) : "", priorities.length ? F.select("priority", "Priorité", e?.priority ?? list?.priority_default ?? "", priorities, { error: errors.priority }) : "")}
    ${F.long("text", e ? "Description" : "Ce que tu attends", e?.body ?? "", { rows: e ? 12 : 8, mono: !!e, hint: "Le contexte, ce qui te ferait dire « c'est fait »…", help: "En Markdown : des titres (##), des listes (-), du `code`.", error: errors.text })}
    ${born === "proposed" ? hint("Il naîtra proposé : le propriétaire du projet l'accepte ou l'écarte.") : ""}`;
}

/**
 * Le parcours d'un ticket, à la verticale : les six étapes que le serveur sert (`journey`), chacune dans son état —
 * passée, en cours, à venir, sautée. L'étape fine est la précision de l'étape en cours ; un ticket qui ne produit pas de
 * code saute la pull request et la fusion, et le parcours dit pourquoi. Rien n'est déduit ici.
 */
export function steps(e: Pick<EntryDetail, "journey" | "status" | "status_label" | "open" | "yours" | "hand_label">): string {
  const j = e.journey;
  if (!j) return "";
  const tone = ticketTone(e);
  const ended = j.ended === "dismissed" ? `<p class="p2-ecarte">${ico("x", "sm")}${h(j.ended_label || e.status_label)}</p>` : "";
  return `${ended}<ol class="p2-steps" aria-label="Parcours du ticket">${j.steps
    .map((s, n) => {
      const here = s.state === "current";
      const fine = here && j.fine_label && j.fine_label.toLowerCase() !== s.label.toLowerCase() ? j.fine_label : "";
      const sub = here ? [fine, !j.ended && e.hand_label ? `la main est ${e.hand_label}` : ""].filter(Boolean).join(" · ") : s.state === "skipped" ? s.state_label : "";
      return `<li class="${s.state === "done" ? "fait" : here ? `ici ${tone}` : s.state === "skipped" ? "saute" : ""}"${here ? ' aria-current="step"' : ""} title="${h(s.state_label)}"><i>${s.state === "done" ? ico("check", "xs") : s.state === "skipped" ? ico("minus", "xs") : n + 1}</i><span>${h(s.label)}</span>${sub ? `<em>${h(sub)}</em>` : ""}</li>`;
    })
    .join("")}</ol>${j.skips_label ? hint(j.skips_label) : ""}`;
}

const STEP_ICON: Record<string, IconName> = { unread: "p2-ticket", analysis: "eye", validation: "p2-plan", pull: "p2-pr", merge: "p2-merge", treated: "check" };

function passageTone(p: Passage): Tone {
  return p.status === "treated" ? "done" : p.status === "dismissed" ? "fail" : p.step === "unread" || !p.step ? "wait" : p.step === "validation" ? "you" : "work";
}

/**
 * L'Historique : l'histoire de ses étapes (`…/element/historique` : des faits, rejoués par le serveur) et, mêlé à elle
 * dans le temps, ce qui est arrivé à ses objectifs — leurs exécutions, leurs commits, leur pull request (`…/activite?ticket=`).
 * Les lignes du fil qui redisent un passage (la sorte « ticket », un geste) n'y sont pas : le passage le dit déjà.
 */
export function historyPane(project: number, d: TicketStory, ctx: Ctx): string {
  if (!d.history.value) return waitingBlock(d.history, "Impossible de lire son histoire");
  const cap = (s: string): string => (s ? s[0].toUpperCase() + s.slice(1) : s);
  const rows = d.history.value.items.map((p) => ({ at: p.at, seq: p.seq, tone: passageTone(p) as string,
    html: `${ico(p.status === "dismissed" ? "x" : STEP_ICON[p.step] ?? "check", "xs")}${p.was ? `${h(cap(p.status_label))} — par ${h(p.author)}` : `Ouvert par ${h(p.author)} — ${h(p.status_label)}`}${p.outside ? ` ${st("out", OUTSIDE)}` : ""}`,
    title: p.was ? `${p.was_label} → ${p.status_label}` : "" }));
  for (const x of d.around.value?.items ?? []) {
    if (x.kind === "ticket" || x.kind === "gesture") continue;
    const href = happeningLink(project, x);
    const text = `${h(x.title)}${x.sha ? ` · <code>${h(x.sha.slice(0, 7))}</code>` : ""}`;
    rows.push({ at: x.at, seq: x.seq, tone: x.what === "merged" ? "done" : "", html: `${ico(KIND_ICON[x.kind] ?? "check", "xs")}${href ? `<a href="${href}">${text}</a>` : text}${x.outside ? ` ${st("out", OUTSIDE)}` : ""}`, title: x.kind_label });
  }
  rows.sort((a, b) => a.at - b.at || a.seq - b.seq);
  return `${d.history.value.cut ? hint("Son histoire est trop longue pour être rejouée en entier : ce qui suit est incomplet.") : ""}<ol class="p2-tl histo">${rows
    .map((r) => `<li class="${r.tone}"${r.title ? ` title="${h(r.title)}"` : ""}><time>${h(moment(r.at, ctx.now))}</time><p>${r.html}</p></li>`)
    .join("")}</ol>`;
}

function note(n: ThreadNote, ctx: Ctx): string {
  if (n.outside) return outside(`${n.author} · ${when(n.at, ctx.now)}`, n.text);
  if (n.kind === "change") return event("check", `${n.author} : ${n.text}`, n.at, ctx.now);
  const side = n.author_kind === "you" ? "moi" : n.author_kind === "self" ? "elle" : "autre";
  return bubble(side, `${n.author_kind === "you" ? "Toi" : n.author}${n.kind !== "note" ? ` · ${n.kind_label}` : ""}`, n.at, ctx.now, h(n.text), authorAvatar(n.author_kind, n.author, ctx.me, "sm"));
}

/** Les boutons du moment : ceux que `can` ouvre, rien d'autre. */
function gestures(project: number, e: EntryDetail): string {
  const d = `data-p="${project}" data-c="${e.number}"`;
  const b = (verdict: string, label: string, primary: boolean, icon: "check" | "x" | "refresh", ask = ""): string => `<button class="btn${primary ? " primary" : ""}" type="button" data-p2="settle" data-v="${verdict}" ${d}${ask ? ` data-ask="${h(ask)}"` : ""}>${ico(icon, "sm")}${label}</button>`;
  return (e.can.validate ? b("validate", "Valider le plan", true, "check") : "")
    + (e.can.refuse ? b("refuse", "Refuser", false, "x", "Ce qui ne va pas (elle le reprendra avec ça)") : "")
    + (e.can.accept ? b("accept", "Accepter le ticket", true, "check") : "")
    + (e.can.dismiss ? b("dismiss", "Écarter", false, "x", e.can.dismiss_needs_reason ? "Pourquoi" : "Pourquoi (facultatif)") : "")
    + (e.can.close ? b("done", "Fermer", false, "check") : "")
    + (e.can.reopen ? b("reopen", "Rouvrir", false, "refresh") : "");
}

function detail(sheet: Sheet, e: EntryDetail, pane: string | undefined, story: TicketStory, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const list = ticketList(sheet);
  const f = (...x: string[]): string => sheetRoute(id, "tickets", e.number, ...x);
  const key = `ticket:${id}:${e.number}`;
  const waits = sheet.todo.find((w) => w.kind === "ticket" && w.number === e.number);
  const asks = waits?.what === "question";
  const fallback = e.can.validate ? "plan" : asks || e.can.accept ? "fil" : "description";
  const known = ["description", "plan", "fil", "historique", "modifier"].includes(pane ?? "") && !(pane === "modifier" && !e.can.modify);
  const v = known ? (pane as string) : fallback;
  const tone = ticketTone(e);
  const talk = e.thread.filter((n) => n.kind !== "change");
  let body = "";
  let foot = "";
  if (e.veiled) body = nothing("lock", "Ce ticket ne se lit pas d'ici", e.veiled_label);
  else if (v === "modifier") {
    body = form({ name: "ticket", key, data: { p: id, c: e.number }, title: `Modifier le ticket #${e.number}`, sub: "Le titre, la sorte, la priorité et la description. Son étape, son fil et son plan ne changent pas.", cancel: f(),
      error: refusalAt(ctx.ui, key), bodyHtml: ticketFields(list, e, fieldErrorsAt(ctx.ui, key)) });
  } else if (v === "description") {
    body = e.body ? (e.outside ? outside(e.author, e.body) : `<div class="p2-md court">${markdown(e.body)}</div>`) : '<p class="p2-none">Pas de description.</p>';
  } else if (v === "plan") {
    body = e.plan_text
      ? planBlock(`<b>Son plan</b>${st(e.can.validate ? "you" : tone, e.status_label)}${e.plan ? `<span class="p2-kind">n° ${e.plan}</span>` : ""}`, markdown(e.plan_text), !!e.can.validate)
      : nothing("p2-plan", "Pas encore de plan", asks ? "Elle attend ta réponse à sa question avant de l'écrire." : e.can.accept ? "Elle n'y touche pas tant que le ticket n'est pas accepté." : !e.open ? e.status_label : "Elle l'écrira en analysant le ticket.",
          asks ? `<a class="btn" href="${f("fil")}">Lire sa question${ico("chev-right", "sm")}</a>` : "");
  } else if (v === "fil") {
    body = `${e.can.accept && e.outside ? banner("you", "p2-ticket", "Ticket proposé depuis ailleurs : elle n'y touche pas tant que tu ne l'as pas accepté.") : ""}${talk.length ? `<div class="p2-thread">${talk.map((n) => note(n, ctx)).join("")}</div>` : '<p class="p2-none">Personne n\'a encore rien écrit dans ce fil.</p>'}`;
    foot = e.can.note
      ? `<div class="p2-note"><textarea rows="2" data-p2-champ data-keep="note-${id}-${e.number}" placeholder="${asks ? "Ta réponse à sa question…" : "Écrire une note dans le fil…"}"></textarea>
          <button class="btn primary" type="button" data-p2="note" data-p="${id}" data-c="${e.number}">${ico("send", "sm")}${asks ? "Répondre" : "Ajouter la note"}</button></div>`
      : "";
  } else body = historyPane(id, story, ctx);
  const l = e.linked;
  const o = l?.objective ?? null;
  const review = (sheet.objectives ?? []).find((x) => x.id === o?.id)?.review ?? null;
  const issueTone = e.issue_state === "closed" ? "done" : "wait";
  const lied = (o ? linked(sheetRoute(id, "objectifs", `o${o.id}`), "p2-target", objectiveTone(o.status), o.text, `objectif n° ${o.id}`, st(objectiveTone(o.status), o.status_label)) : "")
    + (l?.pull ? pullCard(id, l.pull, l.checks, review, ctx.now) : e.pull ? linked(sheetRoute(id, "code", "pulls", e.pull), "p2-pr", "", `Pull request n° ${e.pull}`, "la sienne") : "")
    + (e.issue ? linked(sheetRoute(id, "code", "issues", e.issue), "p2-issue", issueTone, `Issue n° ${e.issue}`, "chez l'hôte du dépôt", e.issue_state_label ? st(issueTone, e.issue_state_label) : "") : "");
  return {
    scroll: `tic-${id}-${e.number}-${v}`, link: (k) => f(k === fallback ? "" : k), active: v, foot,
    panes: v === "modifier" ? [["modifier", "Modifier"]] : [["description", "Description"], ["plan", "Plan", e.plan_text ? null : 0], ["fil", "Fil", talk.length], ["historique", "Historique", story.history.value ? story.history.value.items.length : null]],
    head: head({ num: `#${e.number}`, title: e.title || e.veiled_label || "Ticket",
      metaHtml: `${st(tone, e.status_label)}<span class="p2-kind">${h(e.kind_label)}</span><span class="p2-by">${authorAvatar(e.author_kind, e.author, ctx.me)}ouvert par ${h(e.author)}</span><span>${h(when(e.at, ctx.now))}</span>${e.outside ? st("out", OUTSIDE) : ""}`,
      rightHtml: `${gestures(id, e)}${e.can.modify ? `<a class="btn${v === "modifier" ? " on" : ""}" href="${f(v === "modifier" ? "" : "modifier")}">${ico("pen", "sm")}Modifier</a>` : ""}` }),
    body: (v === "modifier" ? "" : refusal(refusalAt(ctx.ui, key))) + body,
    side: sc("Son parcours", steps(e))
      + sc("En bref", props([["La main", `<span class="p2-by">${e.hand === "self" ? authorAvatar("self", "Mika", ctx.me) : e.yours ? authorAvatar("you", "", ctx.me) : ""}${h(e.hand_label)}</span>`],
        ["Priorité", `<span class="p2-prio ${e.priority === "high" || e.priority === "urgent" ? "haute" : ""}">${ico("flag", "xs")}${h(e.priority_label)}</span>`], ["Sorte", h(e.kind_label)],
        ["Ouvert par", `<span class="p2-by">${authorAvatar(e.author_kind, e.author, ctx.me)}${h(e.author)}</span>`], ["Mis à jour", h(moment(e.updated_at || e.at, ctx.now))]]))
      + sc("Ce qui est lié", lied || '<p class="p2-none">Ni objectif, ni pull request, ni issue pour l\'instant.</p>'),
  };
}

export function ticketsView(sheet: Sheet, rest: string[], page: Got<EntryPage>, element: Got<EntryDetail>, story: TicketStory, ctx: Ctx): string {
  const id = sheet.project.id;
  const list = ticketList(sheet);
  const all = page.value?.items ?? [];
  const shown = ctx.ui.tickets === "yours" ? all.filter((t) => t.yours) : all;
  const wanted = rest[0] && /^\d+$/.test(rest[0]) ? rest[0] : undefined;
  const picked = wanted ?? (ctx.mobile ? undefined : shown[0] ? String(shown[0].number) : undefined);
  const row = (x: Entry): string => `<a class="li p2-row${x.yours ? " atoi" : ""}" href="${sheetRoute(id, "tickets", x.number)}" aria-selected="${String(x.number) === picked}"><span class="p2-tnum">#${x.number}</span>
      <span class="li-main"><span class="li-title">${h(x.title || x.veiled_label)}</span><span class="p2-row-sub">${st(ticketTone(x), x.status_label)}${x.priority === "high" || x.priority === "urgent" ? `<span class="p2-prio haute" title="Priorité ${h(x.priority_label)}">${ico("flag", "xs")}${h(x.priority_label)}</span>` : ""}${x.outside ? st("out", "ailleurs", OUTSIDE) : ""}<time>${h(when(x.updated_at || x.at, ctx.now))}</time></span></span></a>`;
  const listHtml = `<div class="p2-tools"><label class="search grow">${ico("search", "sm")}<input type="search" placeholder="Chercher…" data-p2-saisie="tickets" value="${h(ctx.ui.ticketQuery)}"></label>
        ${sheet.rights.ticket ? `<button class="btn primary" type="button" data-p2="ticketNew" data-p="${id}">${ico("plus", "sm")}<span>Nouveau ticket</span></button>` : ""}</div>
      ${filters("ticketFilter", [["yours", "À toi", ctx.ui.tickets === "all" ? null : all.filter((t) => t.yours).length], ["open", "Ouverts", list?.living ?? null], ["all", "Tous", list?.total ?? null]], ctx.ui.tickets)}
      <div class="pane-scroll" data-scroll="tic-liste">${!page.value ? waitingBlock(page) : shown.length ? shown.map(row).join("") + (page.value.total > all.length ? hint(`${plural(page.value.total - all.length, "autre ticket", "autres tickets")} : précise ta recherche.`) : "")
        : empty("p2-ticket", list?.total ? "Aucun ticket ici" : "Pas encore de ticket", list?.total ? "Change de filtre, ou efface la recherche." : "Un ticket est une demande précise : un défaut, une évolution, une question.")}</div>`;
  const none = empty("p2-ticket", "Choisis un ticket", "Sa description, son plan, son fil et son historique s'ouvrent ici.");
  const e = picked && element.value && String(element.value.number) === picked ? element.value : null;
  return trio({
    list: listHtml, open: !!wanted, back: [sheetRoute(id, "tickets"), "Tickets"], infos: ctx.ui.infos,
    ...(e ? detail(sheet, e, rest[1], story, ctx) : { empty: picked ? waitingBlock(element, "Impossible de lire ce ticket") : none }),
  });
}
