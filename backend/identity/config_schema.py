"""Config schema for the identity & trust layer.

Ce que règle cette section : **à quel point Mika doit être convaincue avant
de raconter à quelqu'un ce qu'elle sait de lui**, et ce que vaut chaque
raison d'y croire.

Ce qui n'y est **pas**, délibérément : les plafonds de canal
(``_CHANNEL_CEILING``). Aucune quantité de conversation ne doit rendre une
affirmation faite dans un salon public aussi bonne qu'une connexion
authentifiée ; c'est une garantie de sécurité, pas un réglage. Idem pour les
identifiants internes, les préfixes éphémères et les lexiques du détecteur.
"""
from __future__ import annotations

from configs.types import ConfigItem, ConfigSection

#: Répété sur les trois clés qui composent l'équation. Un opérateur qui
#: n'ouvre qu'un champ doit voir le calcul entier.
_INVARIANT_CALIBRAGE = (
    "INVARIANT DE CALIBRAGE : « je suis Thomas » (0.20) ne franchit JAMAIS "
    "la barre seul, « il sait un truc que seul Thomas sait » (0.50) non plus "
    "— mais les deux ensemble tombent EXACTEMENT dessus (0.20 + 0.50 = "
    "0.70). C'est ce que « se laisser convaincre » veut dire sur un canal "
    "sans identification. Baisser la barre, ou monter un seul poids, laisse "
    "un inconnu se faire lire la fiche de quelqu'un d'autre. "
    "``backend/tests/test_identity_trust.py`` vérifie cette arithmétique."
)

CONFIG_SCHEMA = [
    ConfigSection(
        key="identity", label="Identité & confiance", icon="⚿", order=35,
        description="Ce qu'il faut pour qu'elle reconnaisse quelqu'un, et ce "
                    "que cette reconnaissance ouvre.",
    ),

    # ── Divulgation ──────────────────────────────────────────────
    ConfigItem(
        key="identity.private_context_threshold", type="float",
        section="identity", group="Divulgation",
        label="Certitude requise pour ouvrir la fiche d'une personne",
        default=0.70, min=0.0, max=1.0, hot_reload=True,
        hint="Sous cette barre, seul son ressenti envers l'interlocuteur "
             "entre dans l'invite : le profil, les engagements et l'historique "
             "de l'autre restent fermés. Un salon public ne la franchit "
             "jamais, à aucune certitude — le risque y est l'auditoire, pas "
             "l'erreur d'identité. " + _INVARIANT_CALIBRAGE,
    ),
    ConfigItem(
        key="identity.confident_threshold", type="float",
        section="identity", group="Divulgation",
        label="Certitude au-delà de laquelle elle s'adresse à la personne sans réserve",
        default=0.70, min=0.0, max=1.0, hot_reload=True,
        hint="Affecte le ton (« tu reconnais Thomas » plutôt que « tu crois "
             "deviner »), pas ce qu'elle a le droit de dire : c'est la clé "
             "au-dessus qui ouvre la fiche.",
    ),

    # ── Poids des preuves ────────────────────────────────────────
    ConfigItem(
        key="identity.evidence_weight.self_declared", type="float",
        section="identity", group="Poids des preuves",
        label="« Je suis Thomas » (affirmation seule)",
        default=0.20, min=0.0, max=1.0, hot_reload=True,
        hint="Bon marché à dire, donc bon marché en poids. "
             + _INVARIANT_CALIBRAGE,
    ),
    ConfigItem(
        key="identity.evidence_weight.passive_inference", type="float",
        section="identity", group="Poids des preuves",
        label="Nom déduit sans qu'on le lui dise",
        default=0.10, min=0.0, max=1.0, hot_reload=True,
        hint="Mention à la troisième personne, signature, métadonnée d'un "
             "module.",
    ),
    ConfigItem(
        key="identity.evidence_weight.shared_memory", type="float",
        section="identity", group="Poids des preuves",
        label="Il évoque ce que seule cette personne sait",
        default=0.50, min=0.0, max=1.0, hot_reload=True,
        hint="La preuve la plus forte disponible sans transport qui prouve "
             "quoi que ce soit. " + _INVARIANT_CALIBRAGE,
    ),
    ConfigItem(
        key="identity.evidence_weight.vouched", type="float",
        section="identity", group="Poids des preuves",
        label="Quelqu'un de confiance se porte garant",
        default=0.35, min=0.0, max=1.0, hot_reload=True,
        hint="Lourd, mais la parole d'un ami ne vaut pas savoir ce que seul "
             "l'intéressé peut savoir.",
    ),
    ConfigItem(
        key="identity.evidence_weight.authenticated", type="float",
        section="identity", group="Poids des preuves",
        label="Le transport l'a prouvé (session)",
        default=1.0, min=0.0, max=1.0, hot_reload=True,
    ),

    # ── Doute ────────────────────────────────────────────────────
    ConfigItem(
        key="identity.counter_weight.contradicted", type="float",
        section="identity", group="Doute",
        label="Il s'est trompé sur un fait partagé",
        default=-0.35, min=-1.0, max=0.0, hot_reload=True,
        hint="Le doute est une preuve aussi. Valeurs négatives.",
    ),
    ConfigItem(
        key="identity.counter_weight.denied", type="float",
        section="identity", group="Doute",
        label="Il nie être la personne qu'elle croyait",
        default=-0.50, min=-1.0, max=0.0, hot_reload=True,
        hint="Appliqué immédiatement, sans délibération : si elle appelle un "
             "inconnu par le nom d'un ami, tout ce qui suit est déjà faux.",
    ),
    ConfigItem(
        key="identity.counter_weight.revoked", type="float",
        section="identity", group="Doute",
        label="Elle cesse explicitement d'y croire",
        default=-1.0, min=-1.0, max=0.0, hot_reload=True,
    ),

    # ── Revendications ───────────────────────────────────────────
    ConfigItem(
        key="identity.pending_claim_ttl_days", type="int",
        section="identity", group="Revendications",
        label="Péremption d'une revendication non tranchée (j)",
        default=7, min=1, max=3650, hot_reload=True,
        hint="Ne pas trancher est un choix légitime, mais sans borne une "
             "revendication revenait dans l'invite à chaque tour, "
             "indéfiniment — détecteur passif compris, qui produit des faux "
             "positifs par construction. ATTENTION : le balayage de "
             "rétention (``memory/retention.py``) lit encore la constante du "
             "module et non cette clé ; les deux doivent s'accorder, sinon "
             "une revendication invisible reste comptée comme pendante.",
    ),
    ConfigItem(
        key="identity.max_pending_claims_shown", type="int",
        section="identity", group="Revendications",
        label="Revendications montrées simultanément dans l'invite",
        default=3, min=1, max=50, hot_reload=True,
        hint="Au-delà, la liste n'aide plus à trancher : elle noie le bloc "
             "identité, à ~50 tokens la ligne, renvoyés à chaque tour.",
    ),

    # ── Corroboration ────────────────────────────────────────────
    ConfigItem(
        key="identity.max_corroboration_facts", type="int",
        section="identity", group="Corroboration",
        label="Faits mémoire confrontés à un message",
        default=12, min=1, max=200, hot_reload=True,
        hint="Petit exprès : cette recherche tourne dans un tour de "
             "conversation.",
    ),
    ConfigItem(
        key="identity.min_overlap_terms", type="int",
        section="identity", group="Corroboration",
        label="Mots de contenu communs pour que ça compte",
        default=3, min=1, max=20, hot_reload=True,
        hint="Un mot partagé est une coïncidence, deux un sujet commun "
             "(« aime » + « musique » ne dit rien de qui tape). Trois est le "
             "point où ils parlent plausiblement de la même chose précise.",
    ),
    ConfigItem(
        key="identity.corroboration_saturation_terms", type="float",
        section="identity", group="Corroboration",
        label="Mots communs valant un score de 1.0",
        default=4.0, min=1.0, max=50.0, hot_reload=True,
        hint="Le score de recoupement sature à ce nombre de mots partagés. "
             "Il reste un indice soumis à Mika, jamais une promotion "
             "automatique.",
    ),
]
