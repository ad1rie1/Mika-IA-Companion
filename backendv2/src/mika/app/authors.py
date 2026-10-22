"""Ses autrices et leurs flux (ADR 0124) : qui récrit ce qui part, et où.

Une autrice est une façon d'écrire (``vocab.flows.Author``) : son nom, ses codes, un exemple de la forme. Un flux (le
chat, chaque boîte mail, Teams, le téléphone) en a au plus une ; sans elle, ce qui part est le premier jet. Toutes
écrivent par le même modèle, celui du rôle ``polish`` (« rendre naturel ») : sans lui, aucune n'écrit.

Une installation qui n'a rien réglé a quatre autrices livrées (``defaults``, leurs mots dans ``persona/voix.yaml``),
chacune d'office sur son flux : « Message » au chat, « Mail pro » à chaque boîte, « Pro Teams » à Teams, « SMS perso »
au téléphone. Une fois le réglage enregistré, il fait foi (un flux laissé vide part en premier jet) ; mais un champ
laissé vide d'une autrice livrée reprend son texte par défaut (``filled``) — l'exemple de « Message », le fil de
référence de sa persona s'il y en a un. La page (Réglages › Autrices, ``app/handmade/authors.py``) les liste, et dit en
tête où chacune écrit.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mika.adapters.mail.config import MailConfig
from mika.kernel.forms import Knob
from mika.vocab import flows
from mika.vocab.flows import Author
from mika.vocab.phrasebook import phrase

#: leurs bornes : des codes se lisent d'un coup d'œil, un exemple tient en un fil ou un courriel
CODES_MAX, EXAMPLE_MAX, NAME_MAX = 2000, 4000, 60
#: les autrices livrées (clé → le nom de leurs mots sous ``expression.author.defaults``)
SHIPPED = {"message": "message", "mail-pro": "mail", "teams-pro": "teams", "sms-perso": "phone"}
#: ce qu'une autrice livrée peut reprendre de son défaut, champ vide
_FILLED = ("name", "codes", "example")


class AuthorSpec(BaseModel):
    """Une autrice telle qu'on la règle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Knob(label="Son nom", help="Comme le tableau la montre : « Mail pro », « Pro Teams »… "
                                                    "(vide : sa clé).", advanced=False, order=10)] = ""
    codes: Annotated[str, Knob(
        label="Ses codes d'écriture", widget="textarea", advanced=False, order=20,
        help="Comment elle écrit dans ce flux : tu ou vous, les formules d'appel et de politesse, la longueur, la mise "
             "en forme, les émojis, ce qu'elle s'interdit. Écrits comme une consigne ; dits au modèle tels quels. "
             "Vide : le cadre du flux seul.")] = ""
    example: Annotated[str, Knob(
        label="Un exemple de la forme", widget="textarea", advanced=False, order=30,
        help="Facultatif : un vrai message de la forme voulue (un fil de SMS, un courriel). Le modèle en prend la "
             "forme, jamais les sujets, les noms ni les formules. Au chat, à défaut, le fil de référence de sa "
             "persona.")] = ""

    @model_validator(mode="after")
    def _bounded(self) -> AuthorSpec:
        for what, text, most in (("son nom", self.name, NAME_MAX), ("ses codes", self.codes, CODES_MAX),
                                 ("son exemple", self.example, EXAMPLE_MAX)):
            if len(text) > most:
                raise ValueError(f"{what} : {len(text)} caractères, {most} au plus")
        return self


class Authors(BaseModel):
    """Ses autrices et le flux de chacune."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authors: Annotated[dict[str, AuthorSpec], Knob(
        label="Ses autrices", advanced=False, order=10,
        help="Chacune est une façon d'écrire. Le même modèle les sert toutes (le rôle « rendre naturel » de Modèles "
             "de texte).")] = Field(default_factory=dict)
    flows: Annotated[dict[str, str], Knob(
        label="Qui écrit où", choices_from="authors", advanced=False, order=20,
        help="Pour chaque flux, l'autrice qui récrit ce qui y part. Vide : ce que le modèle a écrit part tel quel.")] \
        = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _orphans(cls, data: Any) -> Any:
        """Une autrice retirée libère ses flux : ce qui y part redevient le premier jet."""
        if not isinstance(data, Mapping) or not isinstance(data.get("flows"), Mapping):
            return data
        known = data.get("authors") or {}
        return {**data, "flows": {f: k for f, k in data["flows"].items() if k in known}}

    @model_validator(mode="after")
    def _known(self) -> Authors:
        odd = sorted(flow for flow in self.flows if flows.form_of(flow) not in flows.FORMS)
        if odd:
            raise ValueError(f"flux inconnu : « {odd[0]} »")
        return self

    def author_for(self, flow: str) -> Author | None:
        """L'autrice d'un flux, telle que le noyau la lit, ou ``None``."""
        key = self.flows.get(flow, "")
        spec = self.authors.get(key)
        if spec is None:
            return None
        return Author(key, spec.name.strip() or key, spec.codes.strip(), spec.example.strip())


def shipped(key: str, reference: str = "") -> AuthorSpec:
    """Une autrice livrée telle que ``voix.yaml`` l'écrit ; « Message » prend pour exemple le fil de référence de sa
    persona (``reference``), s'il y en a un."""
    words = SHIPPED[key]
    example = reference.strip() if key == "message" and reference.strip() else \
        phrase(f"expression.author.defaults.{words}.example")
    return AuthorSpec(name=phrase(f"expression.author.defaults.{words}.name"),
                      codes=phrase(f"expression.author.defaults.{words}.codes"), example=example)


def defaults(boxes: Iterable[str] = (), reference: str = "") -> Authors:
    """Les autrices d'une installation qui n'en a pas réglé, chacune d'office sur son flux : « Message » au chat,
    « Mail pro » à chaque boîte (``boxes``), « Pro Teams » à Teams, « SMS perso » au téléphone."""
    return Authors(authors={key: shipped(key, reference) for key in SHIPPED},
                   flows={flows.CHAT: "message", **{flows.mail(box): "mail-pro" for box in boxes},
                          flows.TEAMS: "teams-pro", flows.PHONE: "sms-perso"})


def filled(cfg: Authors, reference: str = "") -> Authors:
    """Au cas où ils sont vides : un champ vide d'une autrice livrée reprend son texte par défaut (une autrice qu'on a
    créée garde ses champs tels quels)."""
    authors = {}
    for key, spec in cfg.authors.items():
        if key in SHIPPED:
            base = shipped(key, reference)
            spec = spec.model_copy(update={f: getattr(base, f) for f in _FILLED if not getattr(spec, f).strip()})
        authors[key] = spec
    return cfg.model_copy(update={"authors": authors})


def flow_list(mail: MailConfig) -> list[tuple[str, str]]:
    """Les flux, dans l'ordre de la page : le chat, chaque boîte mail, Teams, le téléphone (clé, libellé)."""
    out = [(flows.CHAT, "Chat")]
    out += [(flows.mail(key), f"Courrier · {box.label or key}") for key, box in mail.accounts.items()]
    out += [(flows.TEAMS, "Teams"), (flows.PHONE, "Téléphone (WhatsApp, SMS)")]
    return out
