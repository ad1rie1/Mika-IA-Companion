"""Réglages › Personnage : qui elle est, ses autrices, son tempérament."""

from __future__ import annotations

import zoneinfo
from functools import cache
from typing import TYPE_CHECKING, Any

import yaml

from mika.app import authors as authors_m
from mika.app import persona as persona_file
from mika.app.handmade import authors as drawn_authors
from mika.app.handmade import temperament as temper
from mika.app.settings_sections.common import parameters
from mika.contracts import self_ as self_c
from mika.contracts.self_ import PersonaDoc
from mika.inspector.catalog import Command, SettingsPage, SettingsSection
from mika.inspector.pages.params import effect, influence_rows
from mika.inspector.ui import PREFIX
from mika.kernel import forms
from mika.kernel.inspect import Column, Disclosure, Ref, Row, Table, Text, When
from mika.vocab.episodes import Role
from mika.vocab.temperament import (
    Temperament,
)

if TYPE_CHECKING:
    from mika.app.server import Live


@cache
def timezones() -> tuple[tuple[str, str], ...]:
    """Les fuseaux IANA connus de la machine (Europe/Paris…), triés, et UTC."""
    names = sorted(n for n in zoneinfo.available_timezones() if "/" in n and not n.startswith(("Etc/", "SystemV")))
    return (("UTC", "UTC (temps universel)"), *((n, n.replace("_", " ")) for n in names))


#: les profils que la console propose d'appliquer (ADR 0100) ; « ajusté » : aucun profil exact (on a réglé à la main)
def _dump(doc: PersonaDoc) -> str:
    return yaml.safe_dump(doc.model_dump(mode="json"), allow_unicode=True, sort_keys=False, width=100)


def sections(live: Live) -> tuple[SettingsSection, ...]:
    settings = live.settings
    params = parameters(live)

    # ── personnalité ──
    async def save_persona(doc: PersonaDoc) -> list[str]:
        if not doc.name.strip():
            return ["Son nom ne peut pas être vide : c'est ainsi qu'elle se présente."]
        previous = settings.persona_yaml()
        await settings.save_persona(_dump(doc))
        problems = await live.reconfigure()
        if problems:
            await settings.save_persona(previous)
            await live.reconfigure()
        return problems

    async def save_temperament(t: Temperament) -> list[str]:
        return await save_persona(live.persona().model_copy(update={"temperament": t}))

    # ── ses autrices (ADR 0124) ──
    def author_flows() -> list[tuple[str, str]]:
        return authors_m.flow_list(settings.email())

    def polish_served() -> str:
        return live.gateway.serving(str(Role.POLISH)) if live.gateway.configured else ""

    async def save_authors(cfg: authors_m.Authors) -> list[str]:
        await settings.save_authors(cfg)
        return []

    def author_facts() -> list[tuple[str, Any]]:
        cfg, flow_rows, served = settings.authors(), author_flows(), polish_served()
        writing = sum(1 for flow, _label in flow_rows if cfg.author_for(flow) is not None)
        rest = " (les autres partent en premier jet)" if writing < len(flow_rows) else ""
        return [("Flux qui ont une autrice", f"{writing} sur {len(flow_rows)}{rest}"),
                ("Leur modèle", Ref("local", f"{PREFIX}/reglages/roles", f"« {served} », rôle « rendre naturel »")
                 if served else "aucun")]

    def character_state() -> dict[str, Any]:
        """Son caractère écrit (ADR 0139), et ce qui retient l'appel qui l'écrirait : aucun modèle, ou le quota."""
        if not live.gateway.configured or not live.gateway.serving(str(Role.CHARACTER)):
            held = "aucun modèle ne sert ce rôle (Intelligence › Qui sert quoi)"
        else:
            held = live.gateway.held(str(Role.CHARACTER), 2)
        return temper.character_state(live.kernel, held)

    def temperament_effect(ui: Any, t: Temperament) -> list[Any]:
        """« Voir l'effet » d'un tempérament : chaque faculté rederivée, surcharges et réglages gardés."""
        return effect(ui, params.preview_temperament(t))

    async def back_to_file(by: str) -> tuple[str, str]:
        if settings.persona_yaml() is None:
            return "info", "La persona vient déjà du fichier."
        try:
            persona_file.read(live.persona_file)
        except persona_file.PersonaInvalid as exc:  # revenir à un fichier illisible, c'est revenir à rien
            raise ValueError(f"Le fichier ne se lit pas : {exc.problem}. La persona de la console reste en "
                             "place.") from None
        previous = settings.persona_yaml()
        await settings.save_persona(None)
        problems = await live.reconfigure()
        if problems:
            await settings.save_persona(previous)
            await live.reconfigure()
            raise ValueError("; ".join(problems))
        return "ok", "Retour au fichier : la persona du fichier fait foi (une révision est journalisée)."

    def persona_facts() -> list[tuple[str, str]]:
        if settings.persona_yaml():
            return [("Source", "la console")]
        live.persona()  # relue : le problème du fichier, s'il en a un, est à jour
        if live.persona_problem:
            return [("Source", "sa dernière persona gardée au journal : le fichier ne se lit pas"),
                    ("Le fichier", live.persona_problem)]
        return [("Source", f"le fichier {live.persona_file.name}")]

    def revisions() -> list[Any]:
        """Les révisions de sa persona, de la plus récente, et ce que chacune a changé."""
        kernel = live.kernel
        stored = kernel.mind.store.latest([self_c.PERSONA_REVISED.name], 200)
        events = [kernel.mind.decode(e) for e in stored]
        labels = {f.path: f.label for f in forms.describe(self_c.PersonaDoc)}
        rows = []
        for i, e in enumerate(events):
            doc = e.data.persona.model_dump(mode="json")
            before = events[i + 1].data.persona.model_dump(mode="json") if i + 1 < len(events) else None
            if before is None:
                changed = ["première version"]
            else:
                changed = [labels.get(k, k) for k in doc if doc[k] != before.get(k)] or ["rien (rejournalisée)"]
            rows.append(Row((When(e.at), Text(", ".join(changed), clamp=200), Text(str(e.origin.value), "muted")),
                            href=None))
        return [Table((Column("quand", "fit"), "ce qui a changé", Column("origine", "fit")), tuple(rows),
                      title=f"Révisions de sa persona ({len(rows)})", empty="Aucune révision journalisée.",
                      caption="Chaque enregistrement du personnage (ou du tempérament) journalise une révision "
                              "complète : l'ancienne se rejoue telle quelle.")]
    def drives() -> list[Any]:
        rows = influence_rows(params, nothing="rien (non branché)", clamp=500)
        # replié sous la table de mixage : l'aide du curseur touché le dit déjà à côté (ADR 0176)
        return [Disclosure("Ce que pilote chaque curseur", (Table((Column("curseur", "fit"),
                                                                  "ce qu'il pilote (à 0 → à 1)"), rows),))]

    return (
        SettingsSection("personnage", "Personnage", "personnage", PersonaDoc, live.persona, save_persona,
                        description="Qui elle est. Chaque enregistrement journalise une révision de sa persona.",
                        exclude=("temperament",), yaml=True, facts=persona_facts,
                        choices={"timezone": timezones},
                        commands=(Command("fichier", "Revenir au fichier", back_to_file, danger=True,
                                          confirm="La persona rédigée ici sera oubliée ; le fichier fera foi."),),
                        pages=(
                            SettingsPage("identite", "Identité",
                                         ("name", "nature", "description", "language", "timezone"), order=10,
                                         description="Son nom, ce qu'elle est (une IA qui le sait, ou une personne "
                                                     "incarnée), qui elle est en une phrase, sa langue et l'heure "
                                                     "qu'elle vit (ses nuits, ses salutations en dépendent)."),
                            # ADR 0138 : un seul texte la décrit ; ce qu'elle ressent se règle dans son tempérament
                            SettingsPage("portrait", "Portrait", ("portrait", "facts", "interests"), order=20,
                                         facts=False, description="Qui elle est, en prose — le seul texte qui la "
                                                                  "décrit, qu'elle lit partout —, ce qui est vrai "
                                                                  "d'elle, et ce qui la passionne. Ce qu'elle "
                                                                  "ressent, montre et fait de ses émotions se règle "
                                                                  "dans son tempérament, pas ici."),
                            SettingsPage("parole", "Sa parole", ("samples", "greetings", "reference_thread"),
                                         order=30, facts=False,
                                         description="Comment elle écrit : des échanges qui montrent sa voix en "
                                                     "chat, ses petits mots de bonjour, et un vrai fil de SMS pour "
                                                     "la forme — des exemples, jamais recopiés."),
                            SettingsPage("document", "Import / export", order=50, form=False, yaml=True,
                                         commands=True, extra=revisions, description=(
                                             "Le personnage entier en YAML (pour le garder ou le coller d'un "
                                             "coup), le retour au fichier, et l'historique de ses révisions.")),
                        )),
        SettingsSection("autrices", "Autrices", "personnage", authors_m.Authors, settings.authors, save_authors,
                        order=120,
                        # en tête, le seul bandeau : aucun modèle ne les fait écrire
                        head=lambda query: drawn_authors.head(served=polish_served()),
                        facts=author_facts,
                        # « Où elles écrivent » est le formulaire même : une ligne par flux, sa liste dans la colonne
                        # « Autrice » (une seule table, un seul Enregistrer)
                        describe={"authors": lambda key, entry: drawn_authors.describe(
                            key, entry, settings.authors(), dict(author_flows())),
                                  "flows": lambda key, value: drawn_authors.flow(key,
                                                                                 teams_on=settings.teams().enabled)},
                        keys={"flows": author_flows},
                        description="Qui récrit ce qui part, et où : une autrice par flux — le chat, chaque boîte "
                                    "mail, Teams, le téléphone —, chacune avec ses codes d'écriture. Le sens reste "
                                    "celui du premier jet, la forme change."),
        SettingsSection("temperament", "Tempérament", "personnage", Temperament,
                        lambda: live.persona().temperament, save_temperament, order=110,
                        head=lambda query: temper.head(live.persona().temperament, query, character_state()),
                        probe=character_state,
                        prefill=lambda query: temper.prefill(live.persona().temperament, query),
                        description="Sa matrice de personnalité : des curseurs rangés en familles, une humeur de "
                                    "fond, deux choix. L'entrée principale de son caractère ; chaque faculté en dérive "
                                    "ses paramètres (Paramètres avancés), et ce qui s'écarte du milieu se dit au "
                                    "modèle.",
                        blocks=drives, preview=temperament_effect, aside=True,
                        pages=(SettingsPage("temperament", "Tempérament", blocks=True, description=(
                            "Des curseurs (0,5 = comme la plupart des gens ; la console s'arrête à 0,1 et 0,9), "
                            "une humeur de fond, sa réaction quand on la blesse et sa défense quand on la touche. "
                            "Chaque faculté en dérive ses paramètres ; la table dessous dit ce que pilote chaque "
                            "curseur, mesuré en le poussant à ses deux bouts. Son caractère, le modèle l'écrit "
                            "d'après ces curseurs, à chaque enregistrement (en haut de la page). Un profil les pose "
                            "tous d'un coup : choisis-le en haut, le formulaire s'ouvre sur ses valeurs, rien n'est "
                            "enregistré avant « Enregistrer ».")),)),
    )
