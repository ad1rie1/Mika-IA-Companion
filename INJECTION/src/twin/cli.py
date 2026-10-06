"""``jumeau`` — la ligne de commande d'INJECTION.

    jumeau etat                     ce que contient le corpus, où en sont les étapes
    jumeau formats [chemin]         quel lecteur prendrait quel fichier (sans rien écrire)
    jumeau ingerer [chemin]         lire brut/ dans travail/corpus.db
    jumeau dater [--claude]         resserrer les dates par l'ordre (et par recoupement avec Claude Code), revue
    jumeau personnes                regrouper les participants en personnes, la reconnaître ; revue personnes.yaml
    jumeau planifier                séances, paliers (A B R C D) et budget de lecture ; curseurs dans plan.yaml
    jumeau lire [--essai]           annoter les séances A, B et C avec Claude Code (reprenable, quota surveillé)
    jumeau synthetiser [--etape X]  mois, chapitres, persona (sortie/persona/), profils, journaux, rêves
    jumeau avancer [--jusqu-a D]    l'avance rapide dans le vrai noyau (moteur gelé, borne mémoire, reprenable)

Les étapes suivantes (personnes, planifier, lire, synthetiser, avancer, oublier) arrivent
avec leurs lots ; voir README.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from twin.corpus import Corpus
from twin.dating import date_corpus, describe
from twin.engine import jobs
from twin.forget import forget_person
from twin.ingest import ingest, walk
from twin.passes.annotate import AnnotatePass
from twin.passes.date import DatePass
from twin.passes.synth import ChapterPass, DreamPass, JournalPass, MonthPass, PersonaPass, ProfilePass
from twin.paths import default_root
from twin.people import resolve_people
from twin.planning import load_knobs, plan
from twin.readers import ReadContext, all_readers, pick
from twin.sessions import build_sessions
from twin.timing import Origin, Temps


def _corpus(root: Path) -> Corpus:
    return Corpus(root / "travail" / "corpus.db")


def cmd_etat(args: argparse.Namespace) -> int:
    root: Path = args.racine
    db = root / "travail" / "corpus.db"
    if not db.is_file():
        print("Corpus vide : déposer les exports dans brut/ puis `jumeau ingerer`.")
        return 0
    corpus = _corpus(root)
    s = corpus.stats()
    tz = ZoneInfo(args.fuseau)
    print(f"Corpus : {db}")
    print(f"  {s['messages']:>10,} messages · {s['documents']:,} documents · {s['conversations']:,} conversations · "
          f"{s['participants']:,} participants ({s['moi']} reconnus comme elle)".replace(",", " "))
    print(f"  {int(s['text_bytes']) / 1e6:>10.1f} Mo de texte")  # type: ignore[call-overload]
    lo, hi = s["span"]  # type: ignore[misc]
    if lo is not None:
        print(f"  du {describe(Temps.exact(lo, Origin.SOURCE), tz)} au {describe(Temps.exact(hi, Origin.SOURCE), tz)}")
    print("  par lecteur :")
    for reader, (n, m, d) in sorted(s["sources"].items()):  # type: ignore[attr-defined]
        print(f"    {reader:<10} {n:>6} fichiers  {m or 0:>10} messages  {d or 0:>7} documents")
    print("  par canal :", ", ".join(f"{k} {v}" for k, v in sorted(s["channels"].items())))  # type: ignore[attr-defined]
    print("  précision des dates :", ", ".join(f"{k} {v}" for k, v in sorted(s["precision"].items())))  # type: ignore[attr-defined]
    if s["conflicts"]:
        print(f"  {s['conflicts']} conflits de dates à revoir (travail/dates.yaml)")
    unknown = root / "travail" / "inconnus.txt"
    if unknown.is_file() and unknown.read_text(encoding="utf-8").strip():
        n = len(unknown.read_text(encoding="utf-8").splitlines())
        print(f"  {n} fichiers sans lecteur (travail/inconnus.txt → /jumeau-nouveau-format)")
    corpus.close()
    return 0


def cmd_formats(args: argparse.Namespace) -> int:
    src = Path(args.chemin or args.racine / "brut")
    readers = all_readers()
    counts: dict[str, int] = {}
    for path in walk(src):
        reader, score = pick(path, readers)
        name = reader.name if reader else "—"
        counts[name] = counts.get(name, 0) + 1
        if args.detail or reader is None:
            print(f"{name:>9} {score:>3}  {path.relative_to(src)}")
    print("\n" + "  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    return 0


def cmd_ingerer(args: argparse.Namespace) -> int:
    root: Path = args.racine
    src = Path(args.chemin or root / "brut")
    if not src.is_dir():
        print(f"Pas de dossier {src}", file=sys.stderr)
        return 2
    corpus = _corpus(root)
    ctx = ReadContext(tz=ZoneInfo(args.fuseau), root=src, country_code=args.indicatif)
    only = set(args.seulement.split(",")) if args.seulement else None
    report = ingest(corpus, src, ctx, only=only, progress=None if args.silence else print)
    unknown = root / "travail" / "inconnus.txt"
    unknown.write_text("\n".join(report.unknown) + ("\n" if report.unknown else ""), encoding="utf-8")
    print(f"\nLus : {report.read or 'rien de neuf'} · inchangés : {report.skipped_unchanged} · "
          f"médias ignorés : {report.skipped_media}")
    print(f"+{report.messages} messages, +{report.documents} documents, {report.duplicates} doublons écartés")
    if report.unknown:
        print(f"{len(report.unknown)} fichiers sans lecteur → travail/inconnus.txt")
    for rel in report.locked:
        print(f"laissé tel quel (déjà lu par Claude Code ; le fichier ou son lecteur a changé depuis) : {rel}",
              file=sys.stderr)
    for rel, err in report.failed:
        print(f"ÉCHEC {rel} : {err}", file=sys.stderr)
    if report.warnings and not args.silence:
        print(f"{len(report.warnings)} avertissements (les 20 premiers) :")
        for w in report.warnings[:20]:
            print(f"  · {w}")
    corpus.close()
    return 1 if report.failed else 0


def cmd_dater(args: argparse.Namespace) -> int:
    root: Path = args.racine
    corpus = _corpus(root)
    review = root / "travail" / "dates.yaml"
    if args.claude:
        p = DatePass(root, ZoneInfo(args.fuseau), model=args.modele)
        _retry(corpus, p, args)
        print(f"Datation par recoupement : {jobs.enqueue(corpus, p)} lots nouveaux · {jobs.counts(corpus, p)}")
        rep = asyncio.run(jobs.run(corpus, p, workers=args.ouvriers, limit=args.max_lots, progress=print))
        print(f"{rep.done} lots datés · {rep.failed} en échec")
    r = date_corpus(corpus, review, ZoneInfo(args.fuseau))
    print(f"{r.sequences} suites ordonnées · {r.narrowed} plages resserrées · {r.interpolated} dates interpolées · "
          f"{r.manual} corrections manuelles appliquées · {r.conflicts} conflits")
    print(f"À revoir dans {review} : {r.to_review or 'rien'}")
    corpus.close()
    return 0


def cmd_oublier(args: argparse.Namespace) -> int:
    root: Path = args.racine
    corpus = _corpus(root)
    try:
        r = forget_person(corpus, args.personne)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        corpus.close()
        return 2
    print(f"{r.name} ({r.handle}) oubliée : {r.participants} comptes, {r.conversations} tête-à-tête, "
          f"{r.messages} messages, {r.annotation_items} éléments d'annotation retirés ; {r.sessions_reread} séances "
          f"à relire sans elle (`jumeau lire`), {r.syntheses} synthèses à refaire (`jumeau synthetiser`).")
    print("L'oubli est gardé : une source relue ne la fera pas revenir.")
    if r.documents_naming:
        print(f"Ses textes à elle qui la nomment encore ({len(r.documents_naming)}, à relire à la main) :")
        for key in r.documents_naming[:30]:
            print(f"  · {key}")
    if (root / "sortie" / "vie" / "mind.db").is_file():
        print("Une vie est déjà vécue dans sortie/vie : l'oublier là aussi, serveur arrêté :\n"
              f"  backendv2/.venv/bin/python -m mika --data {root / 'sortie' / 'vie'} forget {r.handle}")
    corpus.close()
    return 0


def cmd_personnes(args: argparse.Namespace) -> int:
    root: Path = args.racine
    corpus = _corpus(root)
    review = root / "travail" / "personnes.yaml"
    r = resolve_people(corpus, review, ZoneInfo(args.fuseau))
    print(f"{r.persons} personnes · {r.me_participants} comptes à elle · {r.manual_applied} décisions manuelles "
          f"appliquées · {r.merged_auto} rapprochements automatiques · {r.ignored} ignorées (envois de masse)")
    if r.me_by_channel:
        print("Elle, canal par canal :")
        for channel, why in sorted(r.me_by_channel.items()):
            print(f"  {channel:<10} {why}")
    missing = [c for (c,) in corpus.db.execute(
        "SELECT DISTINCT channel FROM participants WHERE channel NOT IN (SELECT channel FROM participants "
        "WHERE person = (SELECT id FROM persons WHERE is_me = 1))")]
    if missing:
        print(f"Pas reconnue dans : {', '.join(sorted(missing))} → la placer à la main dans {review}")
    print(f"{r.to_check} personnes à vérifier dans {review}")
    corpus.close()
    return 0


TIER_WORDS = {"A": "rejouées, lues à fond", "B": "rejouées, lecture légère", "R": "rejouées sans lecture",
              "C": "savoir d'archive (lues, non rejouées)", "D": "ignorées"}


def cmd_planifier(args: argparse.Namespace) -> int:
    root: Path = args.racine
    corpus = _corpus(root)
    if not args.garder_seances:
        s = build_sessions(corpus)
        print(f"{s.sessions} séances de conversation ({s.messages} messages) · {s.documents} documents")
    p = plan(corpus, root / "travail" / "plan.yaml")
    print(f"{'palier':<8}{'séances':>10}{'messages':>12}{'jetons lus':>14}")
    for tier in "ABRCD":
        t = p.tiers.get(tier)
        if t:
            print(f"  {tier:<6}{t.sessions:>10}{t.messages:>12}{t.tokens:>14}   {TIER_WORDS[tier]}")
    print(f"\nLecture : {p.read_tokens:,} jetons d'entrée en {p.batches:,} appels Sonnet, "
          f"≈ {p.read_hours:.0f} h au rythme réglé".replace(",", " "))
    print(f"Avance rapide : {p.replayed_messages:,} messages vécus, ≈ {p.replay_hours:.1f} h de calcul".replace(",", " "))
    print(f"Curseurs : {root / 'travail' / 'plan.yaml'}")
    corpus.close()
    return 0


def cmd_lire(args: argparse.Namespace) -> int:
    root: Path = args.racine
    corpus = _corpus(root)
    knobs = load_knobs(root / "travail" / "plan.yaml")
    p = AnnotatePass(ZoneInfo(args.fuseau), int(knobs["lecture"]["jetons_par_lot"]), model=args.modele)
    _retry(corpus, p, args)
    added = jobs.enqueue(corpus, p)
    state = jobs.counts(corpus, p)
    print(f"Lots : {added} nouveaux · {state}")
    if args.essai:
        row = corpus.db.execute("SELECT payload FROM jobs WHERE pass = ? AND version = ? AND status = 'todo' "
                                "ORDER BY id LIMIT 1", (p.name, p.version)).fetchone()
        if row is not None:
            spec = p.build(corpus, json.loads(row["payload"]))
            print(f"Premier lot : {len(spec.prompt):,} caractères de séances, consigne de {len(spec.system):,} "
                  f"caractères — rien n'a été envoyé (--essai).".replace(",", " "))
        corpus.close()
        return 0
    report = asyncio.run(jobs.run(corpus, p, workers=args.ouvriers, limit=args.max_lots,
                                  quota_ceiling=args.quota, progress=print))
    print(f"\n{report.done} lots lus · {report.retried} à refaire · {report.split} coupés en deux · "
          f"{report.failed} en échec · "
          f"{report.input_tokens:,} jetons lus, {report.output_tokens:,} écrits".replace(",", " "))
    for e in report.errors[:5]:
        print(f"  échec : {e[:200]}", file=sys.stderr)
    corpus.close()
    return 1 if report.failed else 0


def _retry(corpus: Corpus, p: jobs.Pass, args: argparse.Namespace) -> None:
    if getattr(args, "reprendre_echecs", False):
        print(f"{jobs.retry_failed(corpus, p)} lots en échec remis en file ({p.name})")


SYNTH_STEPS = ("mois", "chapitres", "persona", "profils", "journaux", "reves")


def cmd_synthetiser(args: argparse.Namespace) -> int:
    root: Path = args.racine
    corpus = _corpus(root)
    tz = ZoneInfo(args.fuseau)
    passes = {"mois": MonthPass(tz, args.modele), "chapitres": ChapterPass(args.modele),
              "persona": PersonaPass(root, tz, args.modele), "profils": ProfilePass(tz, args.modele),
              "journaux": JournalPass(tz, args.modele), "reves": DreamPass(tz, args.modele)}
    steps = SYNTH_STEPS if args.etape == "tout" else (args.etape,)
    failed = 0
    for step in steps:
        p = passes[step]
        _retry(corpus, p, args)
        added = jobs.enqueue(corpus, p)
        print(f"— {step} : {added} lots nouveaux · {jobs.counts(corpus, p)}")
        if args.essai:
            continue
        rep = asyncio.run(jobs.run(corpus, p, workers=args.ouvriers, limit=args.max_lots, progress=print))
        print(f"  {rep.done} faits · {rep.failed} en échec")
        failed += rep.failed
        if rep.failed and step in ("mois", "chapitres"):
            print("  les étapes suivantes dépendent de celle-ci : arrêt", file=sys.stderr)
            break
    personas = sorted((root / "sortie" / "persona").glob("*.yaml")) if (root / "sortie" / "persona").is_dir() else []
    if personas:
        print("Personas : " + ", ".join(p.name for p in personas))
    corpus.close()
    return 1 if failed else 0


def cmd_avancer(args: argparse.Namespace) -> int:
    from twin.render import her_name  # noqa: PLC0415
    from twin.replay.run import launch, persona_docs  # noqa: PLC0415
    from twin.replay.script import build_script  # noqa: PLC0415

    root: Path = args.racine
    life = root / "sortie" / "vie"
    corpus = _corpus(root)
    if args.de_zero:
        if life.exists():
            shutil.move(str(life), str(life.with_name(f"vie-{datetime.now().astimezone():%Y%m%d-%H%M%S}")))
            print("L'ancienne vie est mise de côté (sortie/vie-<date>/).")
        for table in ("replay_state", "replay_seq"):
            corpus.db.execute(f"DROP TABLE IF EXISTS {table}")
        corpus.db.commit()
    resuming = (life / "mind.db").is_file()
    if args.preparer or not corpus.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'replay_steps'").fetchone():
        if resuming:
            print("Une vie est en cours : le script ne se refait pas sous elle (--de-zero pour repartir).",
                  file=sys.stderr)
            return 2
        name = her_name(corpus)
        rep = build_script(corpus, her_names=(name, name.split()[0]), personas=persona_docs(root, corpus))
        print(f"Script : {rep.steps} pas, {rep.chapters} chapitres de persona.")
        if rep.undated_sessions or rep.knowledge_without_date:
            print(f"Écartés faute de date : {rep.undated_sessions} séances, {rep.knowledge_without_date} lectures de "
                  "savoir d'archive (voir travail/dates.yaml)")
        if args.preparer:
            return 0
    corpus.close()
    print("Reprise de l'avance là où elle s'était arrêtée." if resuming else "Départ de l'avance rapide.")
    return launch(root, args.fuseau, args.jusqu_a, mem=args.memoire)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jumeau", description="INJECTION — le jumeau numérique")
    p.add_argument("--racine", type=Path, default=default_root(), help="le dossier INJECTION/")
    p.add_argument("--fuseau", default="Europe/Paris", help="fuseau de la personne (heures locales des exports)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("etat", help="ce que contient le corpus").set_defaults(fn=cmd_etat)
    f = sub.add_parser("formats", help="quel lecteur prendrait quel fichier")
    f.add_argument("chemin", nargs="?")
    f.add_argument("--detail", action="store_true", help="un fichier par ligne")
    f.set_defaults(fn=cmd_formats)
    i = sub.add_parser("ingerer", help="lire brut/ dans le corpus")
    i.add_argument("chemin", nargs="?")
    i.add_argument("--indicatif", default="+33", help="indicatif des numéros nationaux")
    i.add_argument("--seulement", help="lecteurs à utiliser, séparés par des virgules")
    i.add_argument("--silence", action="store_true")
    i.set_defaults(fn=cmd_ingerer)
    d = sub.add_parser("dater", help="resserrer et interpoler les dates, écrire la revue")
    d.add_argument("--claude", action="store_true", help="d'abord dater par recoupement avec Claude Code (MCP)")
    d.add_argument("--ouvriers", type=int, default=2)
    d.add_argument("--max-lots", type=int, default=None)
    d.add_argument("--modele", default="sonnet")
    d.add_argument("--reprendre-echecs", action="store_true", help="remettre en file les lots en échec")
    d.set_defaults(fn=cmd_dater)
    ob = sub.add_parser("oublier", help="retirer quelqu'un du corpus et de ce qui en a été tiré (gardé)")
    ob.add_argument("personne", help="p12, ext_julie-martin ou son nom")
    ob.set_defaults(fn=cmd_oublier)
    sub.add_parser("personnes", help="regrouper les participants en personnes, la reconnaître").set_defaults(
        fn=cmd_personnes)
    pl = sub.add_parser("planifier", help="séances, paliers et budget")
    pl.add_argument("--garder-seances", action="store_true", help="ne pas recouper les séances")
    pl.set_defaults(fn=cmd_planifier)
    lr = sub.add_parser("lire", help="annoter les séances A, B et C avec Claude Code (Sonnet)")
    lr.add_argument("--ouvriers", type=int, default=3, help="appels en parallèle (mémoire : 3 au plus conseillé)")
    lr.add_argument("--max-lots", type=int, default=None, help="s'arrêter après tant de lots")
    lr.add_argument("--modele", default="sonnet")
    lr.add_argument("--quota", type=float, default=0.8, help="pause au-delà de cette part de l'abonnement")
    lr.add_argument("--essai", action="store_true", help="préparer les lots sans rien envoyer")
    lr.add_argument("--reprendre-echecs", action="store_true", help="remettre en file les lots en échec")
    lr.set_defaults(fn=cmd_lire)
    sy = sub.add_parser("synthetiser", help="mois, chapitres, persona, profils, journaux, rêves")
    sy.add_argument("--etape", choices=("tout", *SYNTH_STEPS), default="tout")
    sy.add_argument("--ouvriers", type=int, default=3)
    sy.add_argument("--max-lots", type=int, default=None)
    sy.add_argument("--modele", default="sonnet")
    sy.add_argument("--essai", action="store_true", help="compter les lots sans rien envoyer")
    sy.add_argument("--reprendre-echecs", action="store_true", help="remettre en file les lots en échec")
    sy.set_defaults(fn=cmd_synthetiser)
    av = sub.add_parser("avancer", help="l'avance rapide dans le vrai noyau (reprenable)")
    av.add_argument("--preparer", action="store_true", help="écrire le script seulement")
    av.add_argument("--jusqu-a", dest="jusqu_a", help="s'arrêter à cette date (AAAA-MM-JJ) ; on reprendra")
    av.add_argument("--de-zero", action="store_true", help="mettre la vie en cours de côté et repartir")
    av.add_argument("--memoire", default="3G", help="plafond mémoire du processus (borne.sh)")
    av.set_defaults(fn=cmd_avancer)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
