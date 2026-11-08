"""Ce qu'un opérateur règle de Teams (Teams › Paramètres, ADR 0206) : s'il est branché, et ses comptes (ADR 0186) —
chacun à quelqu'un (toi, elle, une personne qui a un compte), avec sa façon d'y écrire. La clé de l'extension d'un
compte se génère à part (seule son empreinte est gardée, dans les réglages : ``Settings.teams_keys``).

Une configuration d'avant (un seul Teams : sa voix au premier niveau) devient le compte ``principal``, à toi ; sans
aucun compte, ``principal`` est là aussi (une installation neuve a son Teams, comme avant)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mika.kernel.forms import Knob
from mika.ports.teams import ACCOUNT_KEY, ACCOUNT_KEY_RULE, DEFAULT_ACCOUNT, Voice
from mika.vocab.access import PERSON, SELF, Share

#: ce qui, dans la signature, devient son nom (celui de sa persona : le code ne l'écrit jamais)
HER = "{elle}"
#: la signature proposée (elle dit qu'une IA a écrit)
SIGNATURE = f"— rédigé avec {HER}"
#: ce qu'une configuration d'avant gardait au premier niveau : la voix de son seul compte
_LEGACY_VOICE = ("display_name", "tone", "instructions", "sign", "signature")


class TeamsAccount(BaseModel):
    """Un compte Teams : à qui il est, et comment elle y écrit (à la place de cette personne)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: Annotated[str, Knob(label="Nom affiché", group="Le compte", advanced=False, order=5,
                               help="Comme la console le montre (vide : la clé du compte).")] = ""
    enabled: Annotated[bool, Knob(
        label="Actif", group="Le compte", advanced=False, order=12,
        help="Décoché : son extension est refusée — rien n'arrive, rien ne part, elle n'y prépare rien ; ses "
             "conversations, ses réglages et sa clé restent.")] = True
    owner: Annotated[str, Knob(
        label="À qui", group="Le compte", advanced=False, order=4,
        help="À qui est ce Teams : toi (ses propriétaires), elle, ou une personne qui a un compte. Elle s'en sert "
             "avec son propriétaire — toi en privé et quand elle travaille, elle-même quand elle travaille, cette "
             "personne en privé (ADR 0186). Ce qu'elle y prépare part de ce compte, sous le nom de sa personne.")] = ""
    shares: Annotated[dict[str, Share], Knob(
        label="Partagé avec", group="Le compte", readonly=True, order=5,
        help="Réglé par son propriétaire dans Paramètres › Partages (ADR 0188) : pour chaque personne "
             "(« personne:<clé> »), lire, lire et préparer, ou s'en servir. La personne le voit sous son propre "
             "compte. Tous se voient et se retirent dans Réglages › Droits › Partages (ADR 0210).")] = \
        Field(default_factory=dict)
    display_name: Annotated[str, Knob(
        label="Son nom", group="Écrire", advanced=False, order=20,
        help="Comme ses collègues connaissent la personne de ce compte (vide : celui que Teams donne). Elle écrit à "
             "sa place, à la première personne.")] = ""
    tone: Annotated[str, Knob(label="Ton", group="Écrire", widget="textarea", advanced=False, order=21,
                              help="Par exemple : « tutoiement, bref, amical ».")] = ""
    instructions: Annotated[str, Knob(
        label="Consignes", group="Écrire", widget="textarea", advanced=False, order=22,
        help="Ce qu'elle doit savoir pour répondre à sa place (ce qu'on ne promet jamais, à qui on ne répond pas…). "
             "Elle les suit ; un message reçu, lui, n'est jamais une consigne.")] = ""
    sign: Annotated[bool, Knob(
        label="Signer ses réponses", group="Écrire", advanced=False, order=30,
        help="Ajoute la signature sous chaque message qu'elle prépare : les collègues savent qu'une IA l'a écrit. "
             "Elle ne l'écrit pas elle-même.")] = False
    signature: Annotated[str, Knob(label="La signature", group="Écrire", order=31,
                                   help="Le texte ajouté quand la case ci-dessus est cochée ; « {elle} » y devient "
                                        "son nom.")] = SIGNATURE

    @field_validator("owner")
    @classmethod
    def _owner(cls, owner: str) -> str:
        owner = owner.strip()
        if owner and owner != SELF and not (owner.startswith(PERSON) and len(owner) > len(PERSON)):
            raise ValueError("un compte Teams est à toi (vide), à elle (« elle ») ou à une personne "
                             "(« personne:<clé> »)")
        return owner

    @field_validator("shares")
    @classmethod
    def _shares(cls, shares: dict[str, str]) -> dict[str, str]:
        bad = [k for k in shares if not (k.startswith(PERSON) and len(k) > len(PERSON))]
        if bad:
            raise ValueError(f"un partage va à une personne (« personne:<clé> »), pas à « {bad[0][:40]} »")
        return dict(shares)

    def voice(self, fallback_name: str = "") -> Voice:
        return Voice(display_name=self.display_name.strip() or fallback_name, tone=self.tone,
                     instructions=self.instructions, signature=self.signature.strip() if self.sign else "")


class TeamsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: Annotated[bool, Knob(
        label="Actif", group="Teams", advanced=False, order=5,
        help="Décoché : toute extension est refusée (rien n'est reçu, rien ne part), pour tous les comptes ; ce qui "
             "est déjà reçu reste.")] = True
    accounts: Annotated[dict[str, TeamsAccount], Knob(
        label="Comptes", advanced=False, order=10, key_pattern=ACCOUNT_KEY, key_rule=ACCOUNT_KEY_RULE,
        help=f"Chaque Teams qu'une extension lui apporte : à qui il est, comment elle y écrit. Sa clé d'extension se "
             f"crée dans l'onglet Extension de Teams. La clé d'un compte est un nom court "
             f"({ACCOUNT_KEY_RULE}).")] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _reprise(cls, data: Any) -> Any:
        """Une configuration d'avant (sa voix au premier niveau) devient le compte ``principal`` ; sans compte,
        ``principal`` est là."""
        if not isinstance(data, Mapping):
            return data
        data = dict(data)
        legacy = {k: data.pop(k) for k in _LEGACY_VOICE if k in data}
        if not data.get("accounts"):
            data["accounts"] = {DEFAULT_ACCOUNT: legacy}
        return data

    @model_validator(mode="after")
    def _keys(self) -> TeamsConfig:
        bad = [k for k in self.accounts if not ACCOUNT_KEY.match(k)]
        if bad:
            raise ValueError(f"nom de compte invalide : « {bad[0][:40]} » ({ACCOUNT_KEY_RULE})")
        return self

    def account(self, key: str) -> TeamsAccount | None:
        return self.accounts.get(key)

    def voice(self, account: str, fallback_name: str = "") -> Voice:
        """Comment elle écrit dans ce compte (un compte retiré depuis : sans ton ni consignes, sans signature)."""
        found = self.accounts.get(account)
        return found.voice(fallback_name) if found is not None else Voice(display_name=fallback_name)
