"""Lecture du verdict d'un pas de travail — ce que le modèle *dit* avoir fait.

C'est le contrat de sortie d'un pas de travail endogène : après avoir agi, elle
annonce si le travail est fini, s'il continue, s'il est bloqué, ou s'il faut le
reprendre plus tard. L'appelant en dépend pour décider s'il relance une passe,
s'il repose le sujet, ou s'il l'abandonne.

**Le producteur de ce contrat est un modèle de langage, potentiellement local.**
La revue adversariale l'a relevé explicitement : `projects/runner.py` distingue
déjà sept issues d'un appel (`ok`, `json_miss`, `empty`, `timeout`, `error`,
`quota_exceeded`, plus le cas non structuré) parce qu'un petit modèle rend du
JSON tronqué, refermé au mauvais endroit, ou pas de JSON du tout. Un lecteur qui
suppose du JSON bien formé transforme cette réalité en exception dans une boucle
que **personne ne supervise** : une passe de travail meurt, et la boucle avec.

D'où trois niveaux de tolérance, essayés dans cet ordre :

1. **Le bloc délimité** (`--- VERDICT --- … --- FIN VERDICT ---`), ce que le
   prompt demande. Le délimiteur est préféré à un JSON nu en queue de réponse
   pour deux raisons qui ne sont pas cosmétiques :

   * il **borne une portée retirable**. Le texte rendu au lecteur doit être
     nettoyé de sa propre comptabilité ; avec un JSON nu on sait où il finit,
     jamais où il commence — la prose d'avant peut contenir des accolades, et
     `strip_markdown_json` le documente déjà (« format {cle: valeur} »).
   * il **survit à un corps illisible**. Le bloc reste repérable même quand le
     JSON dedans est tronqué, et on peut alors relire son corps ligne à ligne
     au lieu de tout jeter. La forme est la même que les délimiteurs déjà
     employés dans les prompts (`--- ETAT INTERNE ---`), donc le modèle la
     produit sans qu'on lui apprenne un dialecte de plus.

2. **Le marqueur court** `[SUITE:attendre:600]`, ce qu'un petit modèle
   reproduit plus sûrement qu'un objet : un seul crochet, sur une ligne, dans
   un vocabulaire (`[SIGH]`, `[PAUSE:ms]`) qu'il émet déjà.

3. **Rien.** Et c'est le point important : « aucun verdict lisible » est rendu
   comme un **fait** (`EtatVerdict.ILLISIBLE`, `NiveauVerdict.ABSENT`), jamais
   comme une exception. L'appelant peut compter les passes sans verdict et
   finir par bloquer un travail qui n'en produit jamais — au lieu de boucler
   pour toujours sur un modèle qui ne sait pas répondre au format demandé.

Module **pur** : aucune base, aucun réseau, aucune lecture de configuration.
Les valeurs réglables vivent dans ``VerdictTuning``, dataclasse gelée dont les
défauts *sont* les constantes de module — même motif que
``conscience/scoring.py::ScoringTuning``, et pour la même raison : les tests
mesurent la calibration déclarée, pas la base de la machine qui les exécute.
La résolution vers la configuration se fait au bord, chez l'appelant.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

from utils.degradation import degradations
from utils.parsing import strip_markdown_json

# ── Constantes de repli (défauts de VerdictTuning) ───────────────────────────

#: Délai servi quand elle demande d'attendre sans dire combien. Cinq minutes :
#: assez pour que « plus tard » veuille dire quelque chose, assez peu pour que
#: l'oubli d'un chiffre ne gèle pas un travail jusqu'au soir.
DELAI_DEFAUT_S = 300.0

#: Plafond dur du délai. Un modèle qui rend `604800` (une semaine) ou
#: `1e12` ne se trompe pas de valeur, il se trompe d'ordre de grandeur : ce
#: n'est plus une attente dans une session de veille, c'est une action
#: programmée, qui a son propre modèle. On ramène dans le domaine plutôt que
#: de rendre à l'appelant un nombre qu'il passera tel quel à un calcul
#: d'échéance.
DELAI_MAX_S = 86400.0

#: Bornes de recopie. Le résumé part dans un journal et, plus loin, sous les
#: yeux du modèle au tour suivant : une hallucination de dix mille caractères
#: ne doit pas devenir un bloc de prompt.
RESUME_MAX_CHARS = 400
MOTIF_MAX_CHARS = 300

#: Corps de bloc effectivement analysé. Un délimiteur ouvert et jamais refermé
#: capture jusqu'à la fin du texte ; sans cette borne, une réponse de 100 000
#: caractères deviendrait un « corps de verdict » qu'on passerait entier à
#: ``json.loads`` puis aux relectures ligne à ligne.
BLOC_MAX_CHARS = 8000

#: Extrait brut conservé dans le verdict, pour que « illisible » soit
#: diagnosticable sans ressortir la réponse complète des journaux.
BRUT_MAX_CHARS = 300


@dataclass(frozen=True)
class VerdictTuning:
    """Les bornes du lecteur, avec les constantes de module pour défauts.

    ``VerdictTuning()`` sans argument reproduit exactement le comportement
    décrit ci-dessus. Aucune de ces valeurs n'est lue dans la configuration
    ici : ce module reste pur.
    """

    delai_defaut_s: float = DELAI_DEFAUT_S
    delai_max_s: float = DELAI_MAX_S
    resume_max_chars: int = RESUME_MAX_CHARS
    motif_max_chars: int = MOTIF_MAX_CHARS
    bloc_max_chars: int = BLOC_MAX_CHARS
    brut_max_chars: int = BRUT_MAX_CHARS


#: Réglage partagé : le construire une fois évite de rebâtir la dataclasse à
#: chaque lecture, et donne au repli une identité stable.
DEFAULT_TUNING = VerdictTuning()


class EtatVerdict(str, Enum):
    """Ce que le pas de travail annonce de lui-même.

    ``str`` en base : les valeurs voyagent dans des journaux et des payloads
    JSON, et un ``Enum`` nu s'y sérialise en ``"EtatVerdict.FINI"``.
    """

    FINI = "fini"
    CONTINUE = "continue"
    BLOQUE = "bloque"
    ATTENDRE = "attendre"
    #: Un verdict a peut-être été écrit, mais rien d'exploitable n'en sort.
    #: C'est un état, pas une erreur : il se compte.
    ILLISIBLE = "illisible"


class NiveauVerdict(str, Enum):
    """Duquel des trois niveaux de tolérance vient la lecture.

    Utile à l'appelant pour deux décisions distinctes : « elle n'a rien écrit »
    (ABSENT) appelle un rappel de format ou un abandon après N passes ; « elle
    a écrit un bloc que je n'ai pas su lire » (BLOC + ILLISIBLE) est un défaut
    de *notre* lecteur ou un état inventé, et se répare ici.
    """

    BLOC = "bloc"
    MARQUEUR = "marqueur"
    ABSENT = "absent"


@dataclass(frozen=True)
class Verdict:
    """Ce qu'on a su lire. Toujours renseigné, jamais ``None``."""

    etat: EtatVerdict = EtatVerdict.ILLISIBLE
    resume: str = ""
    motif_blocage: str = ""
    #: Uniquement pour ``ATTENDRE`` — ailleurs c'est ``None``, pour que
    #: l'appelant ne puisse pas confondre « elle a dit d'attendre 0 s » et
    #: « elle n'a pas parlé d'attente ».
    delai_s: float | None = None
    #: Pour ``ATTENDRE`` seulement : QUI elle attend, tel que le verdict
    #: le nomme (un prénom, ou un person_id que le modèle a sous les yeux).
    #: Vide = attente purement temporelle. La résolution vers des handles
    #: appartient au réveil (couche identité), jamais à ce lecteur.
    qui: str = ""
    #: Auto-évaluation : ce résultat vaut-il d'être raconté sans qu'on le
    #: demande ? ``None`` = pas prononcé — l'appelant choisit son défaut, et
    #: l'absence reproduit le comportement d'avant (tout aboutissement était
    #: « notable », seule la fenêtre d'espacement filtrait). Borné [0, 1] à
    #: la lecture ; la méfiance documentée reste : un juge qui note son
    #: propre travail note haut, d'où le seuil de diffusion à 0.80.
    notable: float | None = None
    niveau: NiveauVerdict = NiveauVerdict.ABSENT
    #: Extrait de ce qui a été trouvé, tronqué. Vide quand il n'y avait rien.
    brut: str = ""

    @property
    def present(self) -> bool:
        """Quelque chose a-t-il été écrit à l'emplacement du verdict ?"""
        return self.niveau is not NiveauVerdict.ABSENT

    @property
    def exploitable(self) -> bool:
        """Le verdict peut-il piloter la suite du travail ?

        Distinct de ``present`` : un bloc bien délimité annonçant un état
        inventé est présent et inexploitable. Les deux compteurs ne servent
        pas la même décision.
        """
        return self.etat is not EtatVerdict.ILLISIBLE


#: Verdict rendu quand il n'y a rien à lire. Partagé : il est immuable.
VERDICT_ABSENT = Verdict()


# ── Consigne de prompt ───────────────────────────────────────────────────────

#: Le format demandé au modèle, écrit **ici**, à côté du lecteur.
#:
#: Un format décrit dans un fichier de prompt et analysé dans un autre finit
#: toujours par diverger d'un délimiteur ou d'un nom de clef, et la divergence
#: est silencieuse : le lecteur rend « illisible », la boucle tourne, personne
#: ne voit pourquoi. Un test épingle la propriété qui compte — l'exemple de
#: cette consigne est relu par ``lire_verdict`` et donne un verdict de niveau
#: BLOC.
CONSIGNE_VERDICT = """\
Termine par un bloc de verdict, et rien après lui :

--- VERDICT ---
{"etat": "continue", "resume": "ce que tu viens de faire, une phrase", "motif": "", "delai_s": 0, "notable": 0.3}
--- FIN VERDICT ---

`etat` vaut "fini" (le travail est terminé), "continue" (il reste des pas),
"bloque" (tu ne peux pas avancer — dis pourquoi dans `motif`) ou "attendre"
(reprendre plus tard — dis dans combien de secondes dans `delai_s`, et si tu
attends la réponse de quelqu'un, son nom dans `qui` : un message de cette
personne te réveillera plus tôt).
`notable` (0.0-1.0) : est-ce que ce résultat vaut d'être raconté à quelqu'un
sans qu'on te le demande ? Sois exigeante — la plupart des pas valent 0.2.

Si tu ne peux pas produire ce bloc, écris au moins un marqueur court sur sa
propre ligne : [SUITE:continue] ou [SUITE:attendre:600] ou [SUITE:bloque:il me
manque la clef API].
"""


# ── Repérage ─────────────────────────────────────────────────────────────────

_DELIM_DEBUT = r"-{2,}\s*VERDICT\s*-{2,}"
_DELIM_FIN = r"-{2,}\s*FIN\s+VERDICT\s*-{2,}"

#: Le corps est non gourmand et la fin **alternative** avec ``\Z`` : un bloc
#: ouvert et jamais refermé — la panne la plus banale d'un modèle coupé par sa
#: limite de tokens — reste lisible jusqu'à la fin du texte au lieu de
#: disparaître.
_BLOC_RE = re.compile(
    rf"{_DELIM_DEBUT}(?P<corps>.*?)(?:{_DELIM_FIN}|\Z)",
    re.IGNORECASE | re.DOTALL,
)

#: Marqueur court. ``[^\]\n]`` sur la charge utile : un crochet jamais refermé
#: ne doit pas avaler le reste de la réponse.
_MARQUEUR_RE = re.compile(
    r"\[\s*SUITE\s*[:=]\s*(?P<etat>[^\]\n:=]{1,40})"
    r"(?:\s*[:=]\s*(?P<charge>[^\]\n]{0,400}))?\s*\]",
    re.IGNORECASE,
)

#: Même chose sans crochets, en tête de ligne : un modèle qui « oublie » la
#: syntaxe garde souvent le mot. On exige le début de ligne, sinon « la suite :
#: on verra » dans la prose deviendrait un verdict.
_MARQUEUR_LIGNE_RE = re.compile(
    r"^[\s>*_-]*SUITE\s*[:=]\s*(?P<etat>[^\s\n:=]{1,20})"
    r"(?:\s*[:=]\s*(?P<charge>[^\n]{0,400}))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

#: Fences markdown devenues vides après retrait du bloc qu'elles entouraient.
_FENCE_VIDE_RE = re.compile(r"```[a-zA-Z]*\s*```")

_LIGNES_VIDES_RE = re.compile(r"\n{3,}")


# ── Vocabulaire ──────────────────────────────────────────────────────────────

def _sans_accents(valeur: str) -> str:
    """« bloqué » et « bloque » sont le même état. Le modèle écrit en français
    et l'accent n'est pas un choix qu'il fait exprès."""
    decompose = unicodedata.normalize("NFD", valeur)
    return "".join(c for c in decompose if not unicodedata.combining(c))


#: Synonymes acceptés, français et anglais. La liste est délibérément fermée :
#: un mot inconnu rend ``ILLISIBLE``, pas un état par défaut. Traduire
#: l'inconnu en « continue » ferait tourner pour toujours un travail dont
#: personne ne comprend le verdict — exactement la boucle que ce module existe
#: pour rendre finie.
_SYNONYMES: dict[str, EtatVerdict] = {
    "fini": EtatVerdict.FINI,
    "finie": EtatVerdict.FINI,
    "termine": EtatVerdict.FINI,
    "terminee": EtatVerdict.FINI,
    "acheve": EtatVerdict.FINI,
    "done": EtatVerdict.FINI,
    "finished": EtatVerdict.FINI,
    "complete": EtatVerdict.FINI,
    "continue": EtatVerdict.CONTINUE,
    "continuer": EtatVerdict.CONTINUE,
    "encours": EtatVerdict.CONTINUE,
    "en_cours": EtatVerdict.CONTINUE,
    "poursuivre": EtatVerdict.CONTINUE,
    "suite": EtatVerdict.CONTINUE,
    "in_progress": EtatVerdict.CONTINUE,
    "working": EtatVerdict.CONTINUE,
    "bloque": EtatVerdict.BLOQUE,
    "bloquee": EtatVerdict.BLOQUE,
    "blocage": EtatVerdict.BLOQUE,
    "blocked": EtatVerdict.BLOQUE,
    "echec": EtatVerdict.BLOQUE,
    "failed": EtatVerdict.BLOQUE,
    "attendre": EtatVerdict.ATTENDRE,
    "attente": EtatVerdict.ATTENDRE,
    "differe": EtatVerdict.ATTENDRE,
    "pause": EtatVerdict.ATTENDRE,
    "wait": EtatVerdict.ATTENDRE,
    "waiting": EtatVerdict.ATTENDRE,
    "later": EtatVerdict.ATTENDRE,
}


def _etat_depuis(valeur: object) -> EtatVerdict | None:
    """Mot → état, ou ``None`` si le mot n'est pas du vocabulaire."""
    if not isinstance(valeur, str):
        return None
    mot = _sans_accents(valeur).strip().strip("\"'.,;!").lower()
    mot = mot.replace(" ", "_").replace("-", "_")
    return _SYNONYMES.get(mot)


# ── Lecture des champs ───────────────────────────────────────────────────────

def _cle(source: dict, noms: tuple[str, ...]) -> object | None:
    """Première clef renseignée parmi ``noms``, insensible à la casse et aux
    accents : le modèle écrit « état » un jour, « state » le lendemain."""
    index = {_sans_accents(str(k)).lower(): v for k, v in source.items()}
    for nom in noms:
        valeur = index.get(nom)
        if valeur not in (None, ""):
            return valeur
    return None


_CLES_ETAT = ("etat", "state", "statut", "status")
_CLES_RESUME = ("resume", "summary", "resume_court", "texte", "note")
_CLES_MOTIF = ("motif", "motif_blocage", "blocage", "reason", "blocked_reason", "raison")
_CLES_DELAI = ("delai_s", "delai", "delay", "delay_s", "attente_s", "wait_seconds", "delai_secondes")
_CLES_NOTABLE = ("notable", "notabilite", "noteworthy", "interet", "interest")
_CLES_QUI = ("qui", "attend", "personne", "who", "waiting_for")


def _cle_ligne(corps: str, noms: tuple[str, ...]) -> str | None:
    """Relecture ligne à ligne d'un corps de bloc que ``json.loads`` a refusé.

    C'est ce qui sauve le cas le plus fréquent — le JSON tronqué en plein
    milieu : ``{"etat": "continue", "resume": "j'ai lu les tr`` n'est pas un
    objet, mais l'état, lui, est là et parfaitement lisible. Jeter le tout
    ferait compter comme « sans verdict » une passe qui en avait un.
    """
    alternatives = "|".join(re.escape(n) for n in noms)
    # L'ancre n'est pas le seul début de ligne : un objet tronqué tient
    # souvent sur **une** ligne (`{"etat": "bloque", "motif": "il me manque`),
    # et exiger `^` n'y trouverait que la première clef. On accepte donc aussi
    # une clef précédée d'une accolade ou d'une virgule — mais jamais une
    # occurrence en pleine prose, qui ferait d'« un état de fatigue » un état.
    motif = re.compile(
        rf'(?:^|[{{,])[\s"\'`*\-]*(?:{alternatives})\s*"?\s*[:=]\s*"?(?P<valeur>[^"\n,}}]*)',
        re.IGNORECASE | re.MULTILINE,
    )
    for ligne in motif.finditer(_sans_accents(corps)):
        valeur = ligne.group("valeur").strip()
        if valeur:
            return valeur
    return None


def _texte(valeur: object, limite: int) -> str:
    """Recopie bornée. Un modèle qui rend une liste ou un objet là où on
    attendait une phrase ne doit pas faire tomber la lecture : on le rend
    lisible plutôt que de le refuser."""
    if valeur is None:
        return ""
    if isinstance(valeur, str):
        texte = valeur.strip()
    else:
        texte = str(valeur).strip()
    texte = texte.strip("\"'")
    return texte[:limite].strip()


def _delai(valeur: object, tuning: VerdictTuning) -> float:
    """Nombre de secondes défendable, quoi qu'on nous passe.

    Trois pièges réels, tous rencontrés en sortie de modèle : la valeur
    textuelle (« 600 » ou « bientôt »), la valeur négative (« -1 » pour dire
    « tout de suite »), et le non-fini — ``json.loads`` accepte ``Infinity``
    et ``NaN``, et un ``NaN`` traverse silencieusement ``min``/``max`` pour
    ressortir intact dans un calcul d'échéance.
    """
    if isinstance(valeur, bool):  # `True` n'est pas une seconde.
        return tuning.delai_defaut_s
    if isinstance(valeur, (int, float)):
        nombre = float(valeur)
    elif isinstance(valeur, str):
        trouve = re.search(r"-?\d+(?:[.,]\d+)?", valeur)
        if not trouve:
            return tuning.delai_defaut_s
        try:
            nombre = float(trouve.group(0).replace(",", "."))
        except ValueError:
            return tuning.delai_defaut_s
    else:
        return tuning.delai_defaut_s

    if not math.isfinite(nombre):
        return tuning.delai_defaut_s
    # Un délai négatif n'est pas une erreur de format : c'est « tout de suite ».
    return max(0.0, min(tuning.delai_max_s, nombre))


def _notable(valeur: object) -> float | None:
    """Auto-évaluation de notabilité, ou ``None`` si rien d'exploitable.

    ``None`` et non 0.0 : « il n'a rien dit » laisse l'appelant choisir son
    défaut, « il a dit zéro » est une opinion. Mêmes pièges que ``_delai`` —
    texte, booléen, NaN — et la borne [0, 1] parce que la valeur finit dans
    une comparaison de seuil.
    """
    if valeur is None or isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float)):
        nombre = float(valeur)
    elif isinstance(valeur, str):
        trouve = re.search(r"-?\d+(?:[.,]\d+)?", valeur)
        if not trouve:
            return None
        try:
            nombre = float(trouve.group(0).replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(nombre):
        return None
    return max(0.0, min(1.0, nombre))


def _assembler(
    etat: EtatVerdict,
    *,
    resume: str,
    motif: str,
    delai_source: object,
    notable_source: object = None,
    qui_source: object = None,
    niveau: NiveauVerdict,
    brut: str,
    tuning: VerdictTuning,
) -> Verdict:
    """Fabrique le verdict final, avec la seule règle de cohérence du module :
    le délai n'existe que pour ``ATTENDRE``, et le motif ne survit qu'à
    ``BLOQUE``. Laisser un motif sur un « fini » ferait remonter dans les
    journaux un blocage qui n'a pas eu lieu."""
    delai = _delai(delai_source, tuning) if etat is EtatVerdict.ATTENDRE else None
    return Verdict(
        etat=etat,
        resume=_texte(resume, tuning.resume_max_chars),
        motif_blocage=_texte(motif, tuning.motif_max_chars) if etat is EtatVerdict.BLOQUE else "",
        delai_s=delai,
        qui=_texte(qui_source, 80) if etat is EtatVerdict.ATTENDRE else "",
        notable=_notable(notable_source),
        niveau=niveau,
        brut=_texte(brut, tuning.brut_max_chars),
    )


# ── Niveau 1 : le bloc délimité ──────────────────────────────────────────────

def _corps_du_dernier_bloc(texte: str, tuning: VerdictTuning) -> str | None:
    """Corps du **dernier** bloc de verdict, borné.

    Le dernier et non le premier : quand un modèle produit deux blocs, c'est
    qu'il s'est repris — soit il a recopié le gabarit de la consigne avant de
    répondre, soit il a corrigé son verdict. Dans les deux cas le mot final
    est celui de la fin, et c'est déjà l'ancrage retenu par
    ``strip_markdown_json`` pour la même raison.
    """
    corps = None
    for trouve in _BLOC_RE.finditer(texte):
        corps = trouve.group("corps")
    if corps is None:
        return None
    return corps[: tuning.bloc_max_chars]


def _lire_bloc(texte: str, tuning: VerdictTuning) -> Verdict | None:
    """Niveau 1. ``None`` si aucun bloc n'est délimité dans ``texte``."""
    corps = _corps_du_dernier_bloc(texte, tuning)
    if corps is None:
        return None

    brut = corps.strip()

    # 1a. Le corps est un objet JSON — le cas nominal. ``strip_markdown_json``
    # traverse au passage les fences que le modèle ajoute *à l'intérieur* du
    # bloc quand on lui a demandé du JSON.
    donnees: dict | None = None
    try:
        charge = json.loads(strip_markdown_json(brut))
        if isinstance(charge, dict):
            donnees = charge
    except Exception as exc:
        # Attendu, pas exceptionnel : c'est exactement la panne pour laquelle
        # le niveau 1b existe. On compte quand même, pour que « son JSON n'est
        # jamais valide » soit une question à laquelle la fiche santé répond.
        degradations.record("verdict: bloc json invalide", exc)

    if donnees is not None:
        etat = _etat_depuis(_cle(donnees, _CLES_ETAT))
        if etat is not None:
            return _assembler(
                etat,
                resume=_texte(_cle(donnees, _CLES_RESUME), tuning.resume_max_chars),
                motif=_texte(_cle(donnees, _CLES_MOTIF), tuning.motif_max_chars),
                delai_source=_cle(donnees, _CLES_DELAI),
                notable_source=_cle(donnees, _CLES_NOTABLE),
                qui_source=_cle(donnees, _CLES_QUI),
                niveau=NiveauVerdict.BLOC,
                brut=brut,
                tuning=tuning,
            )
        # Objet valide, état inventé : présent et inexploitable. On garde le
        # niveau BLOC — ce n'est pas la même panne que « elle n'a rien écrit ».
        return Verdict(
            etat=EtatVerdict.ILLISIBLE,
            resume=_texte(_cle(donnees, _CLES_RESUME), tuning.resume_max_chars),
            niveau=NiveauVerdict.BLOC,
            brut=_texte(brut, tuning.brut_max_chars),
        )

    # 1b. JSON refusé : relecture ligne à ligne du corps.
    etat = _etat_depuis(_cle_ligne(brut, _CLES_ETAT))
    if etat is not None:
        return _assembler(
            etat,
            resume=_cle_ligne(brut, _CLES_RESUME) or "",
            motif=_cle_ligne(brut, _CLES_MOTIF) or "",
            delai_source=_cle_ligne(brut, _CLES_DELAI),
            notable_source=_cle_ligne(brut, _CLES_NOTABLE),
            qui_source=_cle_ligne(brut, _CLES_QUI),
            niveau=NiveauVerdict.BLOC,
            brut=brut,
            tuning=tuning,
        )

    # 1c. Un bloc délimité dont on ne tire rien. On ne rend pas ``None`` :
    # descendre en silence au niveau 2 ferait dire « aucun bloc » à un texte
    # qui en contient un, et l'appelant perdrait la seule information utile
    # ici — elle respecte le format, c'est le contenu qui est cassé.
    # ``lire_verdict`` tentera quand même un marqueur de secours, et ne
    # retombera sur ce constat que si le secours ne donne rien non plus.
    return Verdict(
        etat=EtatVerdict.ILLISIBLE,
        niveau=NiveauVerdict.BLOC,
        brut=_texte(brut, tuning.brut_max_chars),
    )


# ── Niveau 2 : le marqueur court ─────────────────────────────────────────────

def _lire_marqueur(texte: str, tuning: VerdictTuning) -> Verdict | None:
    """Niveau 2. ``None`` si aucun marqueur n'apparaît."""
    dernier = None
    for trouve in _MARQUEUR_RE.finditer(texte):
        dernier = trouve
    if dernier is None:
        for trouve in _MARQUEUR_LIGNE_RE.finditer(texte):
            dernier = trouve
    if dernier is None:
        return None

    etat = _etat_depuis(dernier.group("etat"))
    charge = (dernier.group("charge") or "").strip()
    brut = dernier.group(0)
    if etat is None:
        return Verdict(
            etat=EtatVerdict.ILLISIBLE,
            niveau=NiveauVerdict.MARQUEUR,
            brut=_texte(brut, tuning.brut_max_chars),
        )
    # La charge utile est polysémique par construction — c'est le prix d'une
    # forme courte. Elle vaut le délai pour une attente, le motif pour un
    # blocage, le résumé sinon. Elle ne vaut *qu'une* de ces trois choses :
    # laisser « 600 » devenir aussi le résumé d'une attente mettrait un nombre
    # nu dans le journal de travail.
    sans_resume = (EtatVerdict.BLOQUE, EtatVerdict.ATTENDRE)
    return _assembler(
        etat,
        resume="" if etat in sans_resume else charge,
        motif=charge,
        delai_source=charge,
        niveau=NiveauVerdict.MARQUEUR,
        brut=brut,
        tuning=tuning,
    )


# ── Surface publique ─────────────────────────────────────────────────────────

def _en_texte(valeur: object) -> str:
    """Tout ce qui entre devient du texte, ou rien.

    L'entrée vient d'un fournisseur : ``None`` sur un timeout, des octets sur
    un transport qui n'a pas décodé. Rendre ``ILLISIBLE`` sur ces cas est un
    fait mesurable ; lever un ``TypeError`` dans une boucle non supervisée ne
    l'est pas.
    """
    if isinstance(valeur, str):
        return valeur
    if isinstance(valeur, (bytes, bytearray)):
        try:
            return bytes(valeur).decode("utf-8", errors="replace")
        except Exception as exc:
            degradations.record("verdict: entree non decodable", exc)
            return ""
    return ""


def lire_verdict(texte: object, tuning: VerdictTuning | None = None) -> Verdict:
    """Lit le verdict d'une réponse de modèle. **Ne lève jamais.**

    Rend toujours un ``Verdict`` : ``VERDICT_ABSENT`` (état ``ILLISIBLE``,
    niveau ``ABSENT``) quand rien n'est lisible. C'est un fait à compter, pas
    une erreur à traiter.
    """
    t = tuning or DEFAULT_TUNING
    try:
        brut = _en_texte(texte)
        if not brut.strip():
            return VERDICT_ABSENT
        verdict = _lire_bloc(brut, t)
        if verdict is not None:
            if verdict.exploitable:
                return verdict
            # Bloc présent mais inexploitable : un marqueur ailleurs dans la
            # réponse reste préférable à un constat d'échec. Le repli ne
            # s'applique que dans ce sens — un marqueur ne prend jamais le pas
            # sur un bloc lisible, sinon un gabarit recopié en cours de prose
            # renverserait le verdict final.
            secours = _lire_marqueur(brut, t)
            if secours is not None and secours.exploitable:
                return secours
            return verdict
        verdict = _lire_marqueur(brut, t)
        if verdict is not None:
            return verdict
        return VERDICT_ABSENT
    except Exception as exc:
        # Filet de dernier recours. Le corps ci-dessus est écrit pour ne pas
        # lever ; si l'on se trompe, la boucle de travail doit continuer de
        # tourner et le défaut apparaître sur la fiche santé, pas éteindre la
        # conscience jusqu'au prochain redémarrage.
        degradations.record("verdict: lecture", exc)
        return VERDICT_ABSENT


def texte_sans_verdict(texte: object, tuning: VerdictTuning | None = None) -> str:
    """Le texte à dire, débarrassé de sa comptabilité. **Ne lève jamais.**

    Ce qu'elle dit à voix haute ne doit pas contenir le bloc où elle se rend
    des comptes : il partirait en TTS, dans l'historique relu au tour suivant,
    et dans l'extraction nocturne — le même défaut que les jetons de prosodie,
    que ``strip_prosody`` répare partout où le texte ne va pas à une voix.
    """
    t = tuning or DEFAULT_TUNING
    try:
        brut = _en_texte(texte)
        if not brut:
            return ""
        # Tous les blocs, pas seulement celui qu'on a lu : un gabarit recopié
        # avant la réponse est du bruit exactement au même titre.
        propre = _BLOC_RE.sub("", brut)
        propre = _MARQUEUR_RE.sub("", propre)
        propre = _MARQUEUR_LIGNE_RE.sub("", propre)
        # Le bloc était peut-être enfermé dans une fence markdown ; en le
        # retirant on laisse ```` ```json``` ```` orphelin sur deux lignes.
        propre = _FENCE_VIDE_RE.sub("", propre)
        propre = _LIGNES_VIDES_RE.sub("\n\n", propre)
        return propre.strip()
    except Exception as exc:
        degradations.record("verdict: nettoyage", exc)
        return _en_texte(texte).strip()


def depouiller_verdict(
    texte: object, tuning: VerdictTuning | None = None
) -> tuple[str, Verdict]:
    """``(texte_a_dire, verdict)`` en un appel. **Ne lève jamais.**

    Les deux lectures vont toujours ensemble chez l'appelant, et les séparer
    invite à n'en faire qu'une : un verdict lu mais pas retiré du texte est
    prononcé à voix haute.
    """
    return texte_sans_verdict(texte, tuning), lire_verdict(texte, tuning)
