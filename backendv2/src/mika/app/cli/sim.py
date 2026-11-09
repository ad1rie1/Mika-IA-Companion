"""Le simulateur et sa matrice de personnalité : ce qui se vit hors du service (``sim``, ``profil``)."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import tempfile
from pathlib import Path

import yaml

from mika.adapters.llm.config import LLMConfig, build_backend
from mika.app import datadir, embeddings
from mika.app import persona as persona_file
from mika.app.cli.common import _with_settings
from mika.app.composition import for_simulation
from mika.app.paths import PERSONA
from mika.app.settings import Settings
from mika.contracts.self_ import PersonaDoc
from mika.sim.catalog import run_lane
from mika.sim.report import write as write_report
from mika.sim.selftest import run as sim_selftest
from mika.sim.sonde import run_probe
from mika.vocab.temperament import PROFILES, apply_profile, profile_of


def _sim_persona(profile: str) -> PersonaDoc | None:
    """La persona du simulateur sous un profil de personnalité (ADR 0100), ou ``None`` : la sienne telle quelle."""
    if not profile:
        return None
    doc = persona_file.read(PERSONA)
    return doc.model_copy(update={"temperament": apply_profile(doc.temperament, profile)})


async def profile_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """Sa matrice de personnalité hors ligne (ADR 0100) : les profils et le sien ; avec un nom, l'appliquer à sa
    persona (comme la console : la persona rédigée prend le pas sur le fichier), journalisé au prochain démarrage."""
    text = settings.persona_yaml()
    doc = PersonaDoc.model_validate(yaml.safe_load(text) or {}) if text else persona_file.read(PERSONA)
    if not args.nom:
        return {"ok": True, "le_sien": profile_of(doc.temperament) or "ajusté à la main",
                "profils": {key: f"{p.label} — {p.summary}" for key, p in PROFILES.items()}}
    doc = doc.model_copy(update={"temperament": apply_profile(doc.temperament, args.nom)})
    await settings.save_persona(yaml.safe_dump(doc.model_dump(mode="json"), allow_unicode=True, sort_keys=False,
                                               width=100))
    return {"ok": True, "appliqué": args.nom,
            "note": "ses paramètres se rejournalisent et son caractère se réécrit au prochain démarrage ; son "
                    "chronotype et ses précisions sont gardés"}


def _sonde(data: Path, args: argparse.Namespace) -> int:
    """Une semaine de sa vie avec le vrai modèle configuré dans ``data`` (sans y écrire : la semaine vit à part,
    dans ``--out``)."""
    cfg = asyncio.run(_with_settings(data, _llm_of))
    name = args.backend or cfg.routes.get("reply", "")
    spec = cfg.backends.get(name)
    if spec is None:
        print(f"Aucun fournisseur « {name or '(rôle reply)'} » : déclare-le avec « mika llm backend » d'abord.")
        return 2
    if spec.kind == "claude_code":
        print("La sonde ne passe pas par Claude Code : son relais d'outils ne vit que dans le serveur.")
        return 2
    # le vrai modèle de plongements quand il est installé (la mémoire rappelle comme en service), sinon le hachage
    embedder = embeddings.embedder() if importlib.util.find_spec("sentence_transformers") else None
    out = run_probe(for_simulation(_sim_persona(args.profil)), build_backend(name, spec), args.out, embedder=embedder,
                    which=args.semaine)
    print((out / "bilan.txt").read_text(), end="")
    print(f"la semaine : {out / 'fil.txt'}")
    return 0


async def _llm_of(settings: Settings, store: object) -> LLMConfig:
    return settings.llm()


def _run_sim(args: argparse.Namespace) -> int:
    if args.action == "run":
        with tempfile.TemporaryDirectory() as tmp:
            results = run_lane(for_simulation(_sim_persona(args.profil)), Path(tmp))
        path = write_report(results, args.report)
        for r in results:
            print(f"{'✔' if r.ok else '✘'} {r.name} (graine {r.seed}, {r.seconds:.1f} s)")
            for c in r.checks:
                if not c.ok:
                    print(f"    ✘ {c.name} : {c.detail}")
        print(f"rapport : {path}")
        return 0 if all(r.ok for r in results) else 1
    if args.action == "sonde":
        return _sonde(args.data, args)
    out = sim_selftest()
    print(json.dumps(out, ensure_ascii=False))
    return 0 if all(out.values()) else 1


def _run_profil(args: argparse.Namespace) -> int:
    if args.nom:
        datadir.hold(args.data)  # serveur arrêté : sa persona ne change pas sous ses pieds
    out = asyncio.run(_with_settings(args.data, lambda settings, _store: profile_command(settings, args)))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def add_sim(sub) -> None:  # type: ignore[no-untyped-def]
    sm = sub.add_parser("sim", help="le simulateur ; « sonde » : une semaine de sa vie avec le vrai modèle configuré")
    sm.add_argument("action", choices=["selftest", "run", "sonde"])
    sm.add_argument("--lane", default="quick", choices=["quick"])
    sm.add_argument("--report", type=Path, default=Path("sim-reports"))
    sm.add_argument("--out", type=Path, default=Path("sonde"), help="sonde : où écrire la semaine (vidé d'abord)")
    sm.add_argument("--backend", default="", help="sonde : le fournisseur (défaut : celui qui répond, rôle reply)")
    sm.add_argument("--semaine", default="1", choices=["1", "2"],
                    help="sonde : 1 = Adrien, Chloé, Léo ; 2 = Sam (un deuil, un rappel, ses 30 ans), Inès, un salon")
    sm.add_argument("--profil", default="", choices=["", *PROFILES],
                    help="run, sonde : la faire vivre sous ce profil de personnalité (sa persona, autrement)")
    pf = sub.add_parser("profil", help="sa matrice de personnalité (serveur arrêté) : sans nom, les profils et le "
                                       "sien ; avec un nom, l'appliquer à sa persona")
    pf.add_argument("nom", nargs="?", choices=list(PROFILES), help="le profil à appliquer (réfléchie, anxieuse…)")
    sm.set_defaults(run=_run_sim)
    pf.set_defaults(run=_run_profil)
