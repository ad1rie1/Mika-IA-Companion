"""L'onglet « Dépôt » de la fiche d'un projet (``git``, ADR 0183, 0281) : le dépôt de l'atelier face à son dépôt
distant — l'écart entre les deux, l'historique de chacun, ce qui n'est pas encore enregistré, les issues et pull
requests ouvertes (GitHub), les envois et récupérations passés. Lu du port de l'atelier et, pour le distant, du port
``repo_host`` ; les aides communes de la fiche viennent de ``inspect.py``."""

from __future__ import annotations

from typing import Any

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import inspect_code, inspect_merge, inspect_reviews, merge
from mika.faculties.projects.actions import can_edit, can_use_remote, pending_of
from mika.faculties.projects.faculty import (
    PROJECTS,
    PULL_CAPABILITY,
    PUSH_CAPABILITY,
    Project,
    ProjectsState,
    by_pulls,
)
from mika.faculties.projects.inspect import CHECKS_FR, PAGE, PULL_FR
from mika.faculties.projects.inspect_common import (
    cut_noted,
    effect_state,
    host_of,
    remote_ref,
    stored_text,
    stored_texts,
    subject_project,
)
from mika.faculties.projects.pulls import pull_url
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Code,
    Column,
    Disclosure,
    Fields,
    InspectContext,
    Note,
    Ref,
    Row,
    Section,
    Stat,
    Stats,
    Table,
    Text,
    Toolbar,
    When,
    plural,
)
from mika.ports.workshop import PULL_OPEN, Hosted
from mika.vocab.episodes import project_target

# ── La fiche : dépôt git ──────────────────────────────────────────────────

#: ce qu'on montre d'un diff (au-delà : coupé, et dit)
DIFF_SHOWN = 40_000
#: combien d'échanges avec le distant (pousser, récupérer) on montre
EXCHANGES_SHOWN = 12
EXCHANGE_FR = {PUSH_CAPABILITY: "pousser", PULL_CAPABILITY: "récupérer"}


@PROJECTS.inspect("git", title="Code", subject="project", order=28,
                  description="Son code, en sous-vues (« vue ») : fichiers (par défaut : l'arborescence à une branche, "
                              "« ref », et un fichier, « chemin »), commits (« sha »), pulls (« pr »), branches "
                              "(« branche »), issues (« issue »), ci (« sha ») ; et « distant » : le dépôt de "
                              "l'atelier face à son dépôt distant — l'écart entre les deux (à pousser, à récupérer), "
                              "l'historique de chacun, ce qui n'est pas encore enregistré, les envois et "
                              "récupérations passés, ses réglages.")
async def _git_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = subject_project(s, ctx)
    if isinstance(p, Note):
        return [p]
    if ctx.param(inspect_code.VIEW) != inspect_code.REMOTE:  # Code, en sous-vues (ADR 0297)
        return await inspect_code.code_view(p, s, frame, ctx)
    port = ctx.ports.get("workshop")
    hosted = await _hosted(p, ctx)
    there = port is not None and port.exists(p.id)
    head = await port.head(p.id) if there else ""
    gap = await _gap(p, ctx, hosted, head) if there else None
    distant = _distant(p, hosted, gap)
    exchanges = _exchanges(p, frame, ctx)
    if not there:
        return [Note("Pas encore de dépôt : il s'ouvre à la première exécution qui écrit (ou au premier dépôt de "
                     "fichier, ou en récupérant le dépôt distant).", "muted"),
                _remote_section(p, s, frame, ctx, hosted, gap), *_work_branches(p, ctx), *distant, *exchanges]
    blocks: list[Block] = []
    sha = ctx.param("commit")
    if sha:
        shown = await port.show(p.id, sha)
        blocks.append(Section(f"L'enregistrement {sha[:12]}", (
            Code(cut_noted(shown, DIFF_SHOWN), title="Message et changements", lang="diff") if shown
            else Note(f"Aucun enregistrement « {sha[:12]} » dans ce dépôt.", "warn"),
            Fields((("fermer", Ref("subject", f"project/{p.id}", "revenir à l'historique",
                                      (("onglet", "git"), ("vue", "distant")))),)))))
    count = await port.count(p.id)
    pager = ctx.pager("page_commits", size=PAGE, total=count)
    commits = await port.commits(p.id, pager.size, offset=pager.offset)
    latest = commits[:1] if pager.offset == 0 else await port.commits(p.id, 1)
    diff = await port.diff(p.id)
    changed = len(await port.pending(p.id))
    branch = await port.branch(p.id)
    runs = {e.data.commit: e for e in ctx.events([c.RUN_REPORTED], 1000, where=("project", p.id)) if e.data.commit}
    ahead = gap[0] if gap is not None else -1
    rows = []
    for i, k in enumerate(commits, start=pager.offset):
        # un compte rendu d'avant l'ADR 0277 portait l'abrégé : il garde son lien
        run = runs.get(k.sha) or next((e for sha, e in runs.items() if k.sha.startswith(sha)), None)
        rows.append(Row((
            Ref("subject", f"project/{p.id}", k.sha[:7], (("onglet", "git"), ("vue", "commits"), ("sha", k.sha))),
            Text(k.title, clamp=120),
            When(k.at) if k.at else "—", k.author or "—", k.files,
            Text(f"+{k.insertions} −{k.deletions}", "mono"),
            Ref("episode", run.correlation, "exécution") if run is not None else
            ("amorce" if k.title == "atelier ouvert" else "—"),
            Badge("à pousser", "warn") if i < ahead else Text("sur le distant", "muted") if ahead >= 0 else "—"),
            href=Ref("subject", f"project/{p.id}", "", (("onglet", "git"), ("vue", "commits"), ("sha", k.sha)))))
    blocks += [
        Stats((Stat("Enregistrements", count, branch), Stat("Le dernier", When(latest[0].at) if latest and latest[0].at
                                                            else "—", latest[0].sha[:7] if latest else ""),
               Stat("Non enregistré", plural(changed, "fichier", "fichiers") if changed else "rien", "",
                    "warn" if changed else ""),
               Stat("Dépôt distant", host_of(p.remote) or "aucun", p.branch if p.remote else "",
                    "" if p.remote else "muted"),
               *([Stat("Avec le distant", *_gap_words(gap, count))] if p.remote else []))),
        Disclosure(f"Ce qui n'est pas encore enregistré ({plural(changed, 'fichier', 'fichiers')})", (
            Code(cut_noted(diff, DIFF_SHOWN), title="Changements depuis le dernier enregistrement", lang="diff"),),
            open=bool(changed)) if diff.strip() or changed else
        Note("Tout est enregistré : rien de changé depuis le dernier commit.", "muted"),
        Table((Column("commit", "fit"), Column("message"), Column("quand", "fit"), Column("auteur", "fit"),
               Column("fichiers", "num"), Column("lignes", "fit"), Column("exécution", "fit"),
               Column("distant", "fit")), tuple(rows),
              title="Historique", pager=pager, empty="aucun enregistrement encore",
              caption="Un commit s'ouvre en diff coloré. Chaque exécution qui change quelque chose laisse un commit, "
                      "qu'on retrouve dans son compte rendu."),
        _remote_section(p, s, frame, ctx, hosted, gap),
        *_work_branches(p, ctx),
        *distant,
        *exchanges,
    ]
    return blocks


#: ses branches de travail (ADR 0274, 0281) : la fiche dessinée retrouve leur table par ce titre
BRANCHES_TITLE = "Branches de travail"


def _work_branches(p: Project, ctx: InspectContext) -> list[Block]:
    """Ses branches de travail, une par objectif qui en a une : la branche, où en est sa pull request (et sa page
    chez l'hôte), les vérifications de son commit, le verdict de sa relecture. Rien sur un projet au flux direct
    dont aucun objectif n'a de branche."""
    worked = [o for o in p.objectives if o.branch or o.pull_state or o.pull_proposal]
    if not worked and not by_pulls(p):
        return []
    texts = stored_texts(ctx, (o.text_ref for o in worked))
    rows = []
    for o in sorted(worked, key=lambda o: (o.status not in (c.OPEN, c.BLOCKED), -o.id)):
        if o.pull_proposal:
            pull: Any = Badge("proposée : elle attend ton accord", "warn")
        elif o.pull_state:
            state = "ouverte, des changements sont demandés" if o.pull_state == PULL_OPEN and o.pull_changes \
                else PULL_FR.get(o.pull_state, o.pull_state)
            if o.pull_state == PULL_OPEN and o.pull_conflicts:
                state += ", en conflit avec la base"
            words = f"n° {o.pull} {state}" if o.pull else state
            url = pull_url(p, o)
            pull = Ref.url(url, words) if url else words
        else:
            pull = "pas encore" if o.unsent else "—"
        # la fusion, ton geste (ADR 0288) : offerte sur la ligne d'une pull request prête, au commit qu'elle a laissé ;
        # une fusion demandée ou refusée s'y dit
        fuse: tuple[Any, ...] = ()
        if o.pull_state == PULL_OPEN and not merge.blocked(p, o) and o.commit:
            fuse = (ActionSlot(inspect_merge.ACTION, (("objective", str(o.id)), ("head", o.commit)),
                               title=f"Fusionner la pull request n° {o.pull} (commit {o.commit[:12]})",
                               presentation="button"),)
        elif o.pull_state == PULL_OPEN and (merge.merging(o) or o.merge_refused):
            fuse = (Note(inspect_merge.BLOCK_WORDS[merge.ASKED] if merge.merging(o) else
                         inspect_merge.REFUSED_WORDS.get(o.merge_refused, ""), "warn"),)
        rows.append(Row((
            Ref("subject", f"project/{p.id}", f"n° {o.id} · {stored_text(texts, o.text_ref)}"[:90], (("onglet", "objectifs"),)),
            Text(o.branch or "—", "mono"), pull,
            CHECKS_FR.get(o.checks, "—") if o.pull_state == PULL_OPEN else "—",
            Text(inspect_reviews.review_words(p, o) or "—", clamp=140)),
            tone="" if o.status in (c.OPEN, c.BLOCKED) else "muted", detail=fuse))
    return [Table((Column("objectif"), Column("branche", "fit"), Column("pull request"), Column("vérifications"),
                   Column("relecture")), tuple(rows), title=BRANCHES_TITLE,
                  empty="aucune branche de travail encore : chaque objectif ouvre la sienne à sa première exécution",
                  caption="Sur un projet qui passe par des pull requests, chaque objectif travaille sur sa branche ; "
                          "sa pull request se propose quand il est fait, et sa fusion reste à toi : chez l'hôte, ou ici, sur "
                          "sa ligne, quand elle est prête. Elle ne fusionne jamais.")]


async def _hosted(p: Project, ctx: InspectContext) -> Hosted | None:
    """Ce que l'hôte du dépôt distant en dit (GitHub), ou rien : pas de dépôt distant, ou un hôte qu'on ne lit pas.
    Une lecture d'avant le dernier envoi (ou la dernière récupération) se refait ; « relire » (``frais``, son jeton :
    ``inspect_code.fresh_from``) aussi, une fois — recharger la page ne la refait plus."""
    host = ctx.ports.get("repo_host")
    if not p.remote or host is None or not host.handles(p.remote):
        return None
    again = inspect_code.read_again(host, inspect_code.fresh_from(ctx), ("read", p.remote, p.branch))
    return await host.read(p.remote, p.branch, fresh=again, since=p.remote_at)


async def _gap(p: Project, ctx: InspectContext, hosted: Hosted | None, head: str) -> tuple[int, int] | None:
    """L'écart entre l'atelier et le distant, (à pousser, à récupérer) ; ``None`` s'il ne se sait pas (l'hôte n'a
    pas répondu, ou les deux histoires ont divergé). L'atelier compte lui-même quand il connaît la tête du distant ;
    sinon, l'hôte compare (s'il connaît le dernier commit de l'atelier)."""
    if hosted is None or hosted.error or not head:
        return None
    port = ctx.ports["workshop"]
    if not hosted.head:  # la branche n'existe pas encore là-bas : tout l'atelier est à pousser
        return await port.count(p.id), 0
    known = await port.compare(p.id, hosted.head)
    if known is not None:
        return known
    return await ctx.ports["repo_host"].compare(p.remote, head, hosted.head)


def _gap_words(gap: tuple[int, int] | None, count: int) -> tuple[str, str, str]:
    """L'écart en mots : (ce qu'on en dit, sa précision, son ton)."""
    if gap is None:
        return "—", "écart inconnu", "muted"
    ahead, behind = gap
    if not ahead and not behind:
        return "à jour", "rien à pousser ni à récupérer", "ok"
    said = " · ".join(x for x in (f"{ahead} à pousser" if ahead else "", f"{behind} à récupérer" if behind else "")
                      if x)
    if ahead and behind:
        return said, "les deux histoires ont divergé", "danger"
    if behind and count <= 1:
        return said, "l'atelier est vierge : il prendra toute l'histoire", "info"
    return said, "", "warn"


def _remote_section(p: Project, s: ProjectsState, frame: Frame, ctx: InspectContext, hosted: Hosted | None,
                    gap: tuple[int, int] | None) -> Section:
    key = str(p.id)
    pairs: list[tuple[str, Any]] = [
        ("adresse", remote_ref(p)), ("branche", p.branch if p.remote else "—"),
        ("envoi automatique", "après chaque exécution qui enregistre quelque chose" if p.auto_push else "non"),
        ("ce qui part", "avec ton accord" if p.approval else "sans accord (réglé ainsi)"),
        ("dernier échange", Text(p.remote_line, tone="ok" if p.remote_ok else "danger", clamp=300)
         if p.remote_line else "aucun encore"),
        ("quand", When(p.remote_at) if p.remote_at else "—")]
    if hosted is not None and not hosted.error:
        tip = next((k for k in hosted.commits if k.sha == hosted.head), None)
        said, why, tone = _gap_words(gap, 2)
        pairs += [
            ("au bout de la branche", Ref.url(f"{hosted.url}/commit/{hosted.head}",
                                              f"{hosted.head[:7]} — {tip.title if tip else ''}".rstrip(" —"))
             if hosted.head else Text(f"la branche « {p.branch} » n'existe pas encore : le premier envoi la crée",
                                      "muted")),
            ("avec l'atelier", Text(f"{said} — {why}" if why else said, tone=tone)),
            ("issues ouvertes", Ref.url(f"{hosted.url}/issues", _more(hosted.open_issues, hosted.more_issues))),
            ("pull requests ouvertes", Ref.url(f"{hosted.url}/pulls", _more(hosted.open_pulls, hosted.more_pulls))),
            ("visibilité", "privé" if hosted.private else "public"),
            ("lu", When(hosted.read_at) if hosted.read_at else "—")]
    if hosted is not None:
        pairs.append(("relire", Ref("subject", f"project/{p.id}", f"relire {hosted.host} maintenant",
                                    (("onglet", "git"), ("vue", "distant"), ("frais", str(ctx.now))))))
    items: list[Any] = [Fields(tuple(pairs), columns=2)]
    if hosted is not None and hosted.error:
        items.append(Note(f"{hosted.error[:1].upper()}{hosted.error[1:]}.", "warn"))
    if can_use_remote(s, frame, key, ctx.ports):
        items.append(Toolbar((ActionSlot("projects.pousser", title="Pousser maintenant", presentation="button"),
                              ActionSlot("projects.recuperer", title="Récupérer", presentation="button")),
                             title="Maintenant"))
    if can_edit(s, frame, key):
        items.append(Disclosure("Régler le dépôt distant", (
            ActionSlot("projects.depot_distant", title="Enregistrer le dépôt distant", compact=True),),
            open=not p.remote))
    items.append(Note("Le jeton qui permet de pousser (GitHub ou un autre hôte https) se règle dans Connexions › "
                      "Dépôts Git : il n'apparaît jamais dans le journal ni dans ce qu'elle lit.", "muted"))
    return Section("Son dépôt distant", tuple(items),
                   description="Pousser envoie ce qui est enregistré ; récupérer avance l'atelier en ligne droite (un "
                               "atelier vierge prend toute l'histoire du dépôt distant).")


def _more(n: int, more: bool) -> str:
    return f"{n}+" if more else str(n)


def _distant(p: Project, hosted: Hosted | None, gap: tuple[int, int] | None) -> list[Block]:
    """Ce que l'hôte montre du dépôt distant : ses derniers commits, ses issues et pull requests ouvertes (rien s'il
    n'a pas répondu : la section du dépôt distant le dit)."""
    if hosted is None or hosted.error:
        return []
    behind = gap[1] if gap is not None else -1
    commits = tuple(Row((
        Ref.url(f"{hosted.url}/commit/{k.sha}", k.sha[:7]), Text(k.title, clamp=120), When(k.at) if k.at else "—",
        k.author or "—",
        Badge("à récupérer", "info") if i < behind else Text("dans l'atelier", "muted") if behind >= 0 else "—"))
        for i, k in enumerate(hosted.commits))
    issues = tuple(Row((
        Ref.url(t.url, f"#{t.number}"), Text(t.title, clamp=160), Text(", ".join(t.labels) or "—", "muted"),
        t.author or "—", t.comments, When(t.at) if t.at else "—")) for t in hosted.issues)
    pulls = tuple(Row((
        Ref.url(t.url, f"#{t.number}"), Text(t.title, clamp=160), Text(f"{t.head} → {t.base}", "mono"),
        Badge("brouillon", "muted") if t.draft else Badge("prête", "ok"), t.author or "—",
        When(t.at) if t.at else "—")) for t in hosted.pulls)
    where = f"{hosted.host} · {hosted.name}"
    return [
        Table((Column("commit", "fit"), Column("message"), Column("quand", "fit"), Column("auteur", "fit"),
               Column("atelier", "fit")), commits, title="Sur le distant",
              empty=f"la branche « {p.branch} » n'existe pas encore sur le distant",
              caption=f"Les derniers commits de « {p.branch} » sur {where} ; chacun s'ouvre chez l'hôte."),
        Table((Column("n°", "fit"), Column("titre"), Column("étiquettes", "fit"), Column("auteur", "fit"),
               Column("commentaires", "num"), Column("mise à jour", "fit")), issues, title="Issues ouvertes",
              empty="aucune issue ouverte",
              caption=f"Les plus récemment touchées d'abord, sur {where} ; chacune s'ouvre chez l'hôte."),
        Table((Column("n°", "fit"), Column("titre"), Column("branches", "fit"), Column("état", "fit"),
               Column("auteur", "fit"), Column("mise à jour", "fit")), pulls, title="Pull requests ouvertes",
              empty="aucune pull request ouverte",
              caption=f"Les plus récemment touchées d'abord, sur {where} ; chacune s'ouvre chez l'hôte."),
    ]


def _exchanges(p: Project, frame: Frame, ctx: InspectContext) -> list[Block]:
    """Ses envois et récupérations, les plus récents d'abord : quand, lequel, s'il fallait ton accord, ce qu'il en
    est (et ce que git a répondu, en détail)."""
    asked = [e for e in ctx.events([rt.EFFECT_PROPOSED], 200, where=("context", project_target(p.id)))
             if e.data.capability in EXCHANGE_FR][:EXCHANGES_SHOWN]
    if not asked and not p.remote:
        return []
    pending = {v.proposal for v in pending_of(frame, p.id)}
    rows = []
    for e in asked:
        outcomes = () if e.seq in pending else ctx.events([rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED], 4,
                                                           where=("proposal", e.seq))
        state, detail = effect_state(e, e.seq in pending, outcomes)
        rows.append(Row((When(e.at), EXCHANGE_FR[e.data.capability], "requis" if e.data.approval else "non requis",
                         state), tone="warn" if e.seq in pending else "",
                        detail=(Code(cut_noted(detail, 4000), title="ce que git a répondu"),) if detail else ()))
    return [Table((Column("quand", "fit"), Column("quoi", "fit"), Column("accord", "fit"), Column("état", "fit")),
                  tuple(rows), title="Échanges avec le distant", empty="aucun envoi ni récupération encore",
                  caption="Les plus récents d'abord ; une demande qui attend ton accord se décide dans « À valider ».")]
