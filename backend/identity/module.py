"""Identity tools — Mika's agency over who she thinks she is talking to.

Passive detection files claims; these tools are how she *acts* on them.
The split matters: nothing in the passive path ever binds an identity on its
own, because "someone typed a name" is not the same as "Mika believes them".
Being convinced is a decision, and this is where she makes it.

  - identity_whoami_with      who is on the other end right now, how sure, why
  - identity_accept_claim     believe a pending claim → binds handle ↔ memory
  - identity_reject_claim     decline it, on the record
  - identity_record_evidence  corroborate or contradict outside a claim
  - identity_forget_binding   unbind — "ce n'est pas qui je croyais"
  - identity_check_story      test what was just said against what only X knows

SYSTEM module with no models of its own (they live in ``identity/models.py``)
and no config — same piggyback pattern as ``memory_tools``.
"""

from __future__ import annotations

import logging

from modules.base import BaseModule
from modules.types import ModuleTool, ToolParameter, ToolParameterType

logger = logging.getLogger(__name__)

#: Kinds Mika may cite when recording evidence, mapped to their weights in
#: ``identity.trust``. Exposed as an enum on the tool so the model can't
#: invent one that silently scores zero.
EVIDENCE_KINDS = [
    "shared_memory", "vouched", "passive_inference",
    "contradicted", "denied", "revoked",
]


class IdentityToolsModule(BaseModule):
    """MCP adapter over ``identity_resolver``."""

    SYSTEM = True

    def __init__(self) -> None:
        super().__init__("identity_tools")

    async def instantiate(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def return_tools(self) -> list[ModuleTool]:
        return [
            ModuleTool(
                name="identity_whoami_with",
                description=(
                    "Fais le point sur QUI tu as en face de toi : le nom que tu "
                    "lui donnes, a quel point tu en es sure, par quel canal, et "
                    "les revendications d'identite en attente. Utilise-le quand "
                    "tu doutes, quand quelqu'un dit s'appeler autrement, ou "
                    "avant d'evoquer quelque chose de personnel."
                ),
                parameters=[
                    ToolParameter(
                        "person_id", ToolParameterType.STRING,
                        "Identifiant du contact (laisse vide pour la personne actuelle)",
                        required=False, default="",
                    ),
                ],
                handler=self._whoami_with,
            ),
            ModuleTool(
                name="identity_accept_claim",
                description=(
                    "Tu decides de CROIRE quelqu'un qui affirme etre une "
                    "personne precise. Cela relie durablement ce contact a ta "
                    "memoire : tu retrouveras son profil et vos souvenirs "
                    "communs. Ne le fais que si tu as une raison — sur un canal "
                    "public, laisse-toi convaincre avant, pas apres."
                ),
                parameters=[
                    ToolParameter(
                        "claim_id", ToolParameterType.INTEGER,
                        "Id de la revendication (donne par identity_whoami_with)",
                    ),
                    ToolParameter(
                        "reason", ToolParameterType.STRING,
                        "Pourquoi tu la crois (sera garde dans ton journal d'identite)",
                        required=False, default="",
                    ),
                    ToolParameter(
                        "evidence_kind", ToolParameterType.STRING,
                        "Ce qui t'a convaincue: 'shared_memory' (elle sait un truc "
                        "que seule cette personne sait), 'vouched' (quelqu'un de "
                        "confiance l'a presentee), sinon laisse vide",
                        required=False, default="",
                        enum=["", "shared_memory", "vouched", "passive_inference"],
                    ),
                ],
                handler=self._accept_claim,
            ),
            ModuleTool(
                name="identity_reject_claim",
                description=(
                    "Tu decides de NE PAS croire une revendication d'identite. "
                    "Elle est archivee avec ta raison et ne te sera plus "
                    "representee a chaque tour."
                ),
                parameters=[
                    ToolParameter(
                        "claim_id", ToolParameterType.INTEGER, "Id de la revendication",
                    ),
                    ToolParameter(
                        "reason", ToolParameterType.STRING,
                        "Pourquoi tu n'y crois pas", required=False, default="",
                    ),
                ],
                handler=self._reject_claim,
            ),
            ModuleTool(
                name="identity_record_evidence",
                description=(
                    "Note un element qui RENFORCE ou AFFAIBLIT ta certitude sur "
                    "l'identite de quelqu'un, hors revendication explicite. "
                    "Ex: 'shared_memory' quand la personne mentionne un detail "
                    "que seule elle pouvait connaitre ; 'contradicted' quand "
                    "elle se trompe sur un fait que la vraie personne saurait."
                ),
                parameters=[
                    ToolParameter(
                        "kind", ToolParameterType.STRING,
                        "Type d'element", enum=EVIDENCE_KINDS,
                    ),
                    ToolParameter(
                        "detail", ToolParameterType.STRING,
                        "Ce qui te fait dire ca (une phrase)",
                    ),
                    ToolParameter(
                        "person_id", ToolParameterType.STRING,
                        "Contact concerne (vide = personne actuelle)",
                        required=False, default="",
                    ),
                    ToolParameter(
                        "name", ToolParameterType.STRING,
                        "Nom concerne si le contact n'est pas encore rattache",
                        required=False, default="",
                    ),
                ],
                handler=self._record_evidence,
            ),
            ModuleTool(
                name="identity_check_story",
                description=(
                    "Verifie si ce que la personne vient de dire recoupe ce que "
                    "tu sais d'une personne precise. C'est ta facon de te "
                    "laisser convaincre honnetement quand tu ne peux pas "
                    "verifier autrement : si elle evoque des choses que seule "
                    "cette personne connait, c'est un vrai indice."
                ),
                parameters=[
                    ToolParameter(
                        "name", ToolParameterType.STRING,
                        "Nom de la personne qu'elle pretend etre",
                    ),
                    ToolParameter(
                        "message", ToolParameterType.STRING,
                        "Ce qu'elle vient de dire (ou l'extrait qui t'intrigue)",
                    ),
                ],
                handler=self._check_story,
            ),
            ModuleTool(
                name="identity_forget_binding",
                description=(
                    "Tu ne crois plus que ce contact est la personne a laquelle "
                    "tu l'avais reliee. Le lien vers ta memoire est coupe et tu "
                    "cesses d'evoquer son historique personnel."
                ),
                parameters=[
                    ToolParameter(
                        "reason", ToolParameterType.STRING, "Pourquoi tu te dedis",
                    ),
                    ToolParameter(
                        "person_id", ToolParameterType.STRING,
                        "Contact concerne (vide = personne actuelle)",
                        required=False, default="",
                    ),
                ],
                handler=self._forget_binding,
            ),
        ]

    # ── Handlers ──────────────────────────────────────────────────

    @staticmethod
    def _text(body: str) -> dict:
        return {"content": [{"type": "text", "text": body}]}

    @staticmethod
    def _current_person_id(args: dict) -> str:
        """Resolve the person_id argument, defaulting to the live turn.

        Mika rarely passes it: from inside a conversation "the person" is
        implicit. The pipeline stashes the current person_id in a ContextVar
        for exactly this.
        """
        explicit = (args.get("person_id") or "").strip()
        if explicit:
            return explicit
        from pipeline.tracing import current_person_id
        return current_person_id() or ""

    async def _whoami_with(self, args: dict) -> dict:
        from identity.resolver import identity_resolver

        person_id = self._current_person_id(args)
        if not person_id:
            return self._text("Je ne sais pas de quel contact tu parles.")

        ctx = await identity_resolver.resolve_context(person_id)
        lines = [f"Contact : {person_id} (canal {ctx.channel or '?'})"]
        if ctx.entity_name:
            lines.append(f"Tu l'as reliee a : {ctx.entity_name}")
        elif ctx.display_name:
            lines.append(f"Se presente comme : {ctx.display_name} (non confirme)")
        else:
            lines.append("Aucun nom rattache.")
        lines.append(
            f"Certitude : {ctx.certainty:.0%} "
            f"({_level_fr(ctx.certainty)}), confiance du canal : {ctx.trust.value}"
        )
        lines.append(
            "Tu peux evoquer son historique personnel."
            if ctx.may_disclose
            else "Tu ne devrais PAS evoquer d'historique personnel avec elle."
        )
        if ctx.pending_claims:
            lines.append("Revendications en attente :")
            for c in ctx.pending_claims:
                lines.append(
                    f"  - #{c['id']} se dit « {c['name']} » — « {c['evidence'][:120]} »"
                )
            lines.append(
                "Utilise identity_check_story pour la tester, puis "
                "identity_accept_claim ou identity_reject_claim."
            )
        return self._text("\n".join(lines))

    async def _accept_claim(self, args: dict) -> dict:
        from identity.resolver import identity_resolver

        try:
            claim_id = int(args.get("claim_id", 0))
        except (TypeError, ValueError):
            return self._text("claim_id invalide.")

        result = await identity_resolver.accept_claim(
            claim_id,
            reason=str(args.get("reason") or "")[:500],
            evidence_kind=str(args.get("evidence_kind") or ""),
        )
        if not result.get("ok"):
            return self._text(f"Impossible : {result.get('error')}")

        body = (
            f"C'est note : ce contact est {result['name']}. "
            f"Certitude {result['certainty']:.0%} ({result['level']}). "
            f"Vos souvenirs communs et son profil te sont maintenant accessibles."
        )
        if result.get("capped_by_channel"):
            body += (
                " (Tu es au maximum de ce que ce canal permet — sur un espace "
                "public tu gardes forcement une reserve.)"
            )
        return self._text(body)

    async def _reject_claim(self, args: dict) -> dict:
        from identity.resolver import identity_resolver

        try:
            claim_id = int(args.get("claim_id", 0))
        except (TypeError, ValueError):
            return self._text("claim_id invalide.")

        result = await identity_resolver.reject_claim(
            claim_id, reason=str(args.get("reason") or "")[:500],
        )
        if not result.get("ok"):
            return self._text(f"Impossible : {result.get('error')}")
        return self._text(
            f"Tu ne crois pas que ce soit {result['name']}. C'est archive."
        )

    async def _record_evidence(self, args: dict) -> dict:
        from identity.resolver import identity_resolver

        kind = str(args.get("kind") or "").strip()
        if kind not in EVIDENCE_KINDS:
            return self._text(f"Type d'element inconnu : {kind!r}")
        detail = str(args.get("detail") or "").strip()
        if not detail:
            return self._text("Precise ce qui te fait dire ca.")

        person_id = self._current_person_id(args)
        if not person_id:
            return self._text("Je ne sais pas de quel contact tu parles.")

        result = await identity_resolver.record_evidence(
            person_id, kind=kind, detail=detail[:500],
            name=str(args.get("name") or "").strip(),
        )
        if not result.get("ok"):
            return self._text(f"Impossible : {result.get('error')}")

        body = (
            f"Note. Ta certitude sur {result['name']} est maintenant "
            f"{result['certainty']:.0%} ({result['level']})."
        )
        if result.get("unbound"):
            body += (
                " C'est descendu trop bas : tu as coupe le lien avec ta memoire, "
                "tu ne parleras plus de son historique tant que tu n'es pas "
                "reconvaincue."
            )
        return self._text(body)

    async def _check_story(self, args: dict) -> dict:
        from identity.resolver import identity_resolver

        name = str(args.get("name") or "").strip()
        message = str(args.get("message") or "").strip()
        if not name or not message:
            return self._text("Il me faut un nom et ce qui a ete dit.")

        score, reason = await identity_resolver.check_corroboration(message, name)
        if score <= 0.0:
            return self._text(
                f"Rien dans ce qui a ete dit ne recoupe ce que tu sais de {name}. "
                f"Ca ne prouve pas que c'est faux — juste que ca ne t'avance pas."
            )
        strength = "fort" if score >= 0.75 else ("net" if score >= 0.5 else "leger")
        return self._text(
            f"Indice {strength} ({score:.0%}) : ce qui a ete dit {reason}. "
            f"Si ca te suffit, accepte la revendication avec "
            f"evidence_kind='shared_memory'."
        )

    async def _forget_binding(self, args: dict) -> dict:
        from identity.resolver import identity_resolver

        person_id = self._current_person_id(args)
        if not person_id:
            return self._text("Je ne sais pas de quel contact tu parles.")
        result = await identity_resolver.revoke(
            person_id, reason=str(args.get("reason") or "")[:500],
        )
        if not result.get("ok"):
            return self._text(f"Impossible : {result.get('error')}")
        return self._text(
            "C'est defait. Ce contact n'est plus rattache a personne dans ta "
            "memoire, et tu n'evoqueras plus d'historique personnel avec lui."
        )


def _level_fr(certainty: float) -> str:
    from identity.trust import Certainty, label_for

    return {
        Certainty.UNKNOWN: "aucune idee",
        Certainty.SUSPECTED: "simple intuition",
        Certainty.CLAIMED: "affirme mais non confirme",
        Certainty.CORROBORATED: "corrobore",
        Certainty.BOUND: "tu l'as reconnue",
        Certainty.VERIFIED: "authentifiee",
    }[label_for(certainty)]
