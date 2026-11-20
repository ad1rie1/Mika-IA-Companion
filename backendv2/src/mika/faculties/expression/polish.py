"""La seconde passe de l'autrice (ADR 0114) : la consigne et le message d'un appel où une autrice écrit la suite du
fil à partir de son premier jet (``polish``), ce qu'on garde de ce qu'elle a écrit (``authored`` : ses messages à
elle), et la passe d'une autrice sur un brouillon d'outil (``polish_draft``, ADR 0124)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mika.faculties.expression.tags import _plain
from mika.kernel.prompt import CONTEXT_FOOTER, unlabel
from mika.vocab import flows
from mika.vocab.phrasebook import phrase
from mika.vocab.tag import PROSODY, SILENCE_TOKEN
from mika.vocab.words import fold

#: une ligne vide : en chat, ce qui suit part dans une autre bulle (les clients découpent, ADR 0112)
_BUBBLES = re.compile(r"\n\s*\n")


def _bubbles(text: str) -> str:
    """Sa parole sans balise ni jeton de voix, ses bulles gardées (séparées par une ligne vide)."""
    return "\n\n".join(p for p in (_plain(b) for b in _BUBBLES.split(text or "")) if p)


# ── Sa réponse écrite par une autrice (ADR 0114) ──────────────────────────
#
# Ablation du 2026-10-15 : rejouer un appel mal jugé en retirant ou réécrivant un bloc de son prompt ne change presque
# rien — faire de ce qu'on lui dit une vérité générale, reformuler, finir par une question, c'est le modèle qui joue
# l'amie qui écoute. Banc du 2026-10-16 : tour par tour, même Opus reste une assistante qui joue un rôle et s'occupe de
# l'autre ; le même modèle, qui écrit un fil SMS entier en autrice, fait parler deux personnes. La seconde passe
# (``pipeline``, rôle ``polish``) est donc une autrice : elle lit son portrait, le fil et ce que le premier jet voulait
# dire, et écrit la suite du fil — ses messages à elle, puis la réponse probable de l'autre (l'écrire la garde
# autrice) ; seuls les siens partent. Ses balises, ses outils et ce qu'elle sait restent ceux du premier jet.
# ADR 0261 : la consigne demande toujours toute la suite (c'est elle qui fait l'autrice), mais l'appel s'arrête à la
# première ligne de l'autre (``stops``) — ce qu'on jetait n'est plus écrit, ce qu'on garde ne change pas.

#: les derniers messages du fil que lit l'autrice
_POLISH_THREAD = 16


def _thread_lines(role: str, content: str, name: str) -> list[str]:
    """Un message du fil en lignes de SMS : une par bulle pour elle, une pour l'autre."""
    if role != "assistant":
        said = _plain(content)
        return [phrase("expression.polish.them", text=said)] if said else []
    return [phrase("expression.polish.her", name=name, text=b) for b in _bubbles(content).split("\n\n") if b]


def _thread(history: Sequence[Any], name: str) -> list[str]:
    """Les derniers messages du fil (``_POLISH_THREAD``) en lignes de SMS, chacun précédé de son repère de temps
    quand du temps a passé (« [le lendemain, mardi 14h13] ») : sans eux, trois jours de fil se lisaient comme une
    seule conversation, et au « coucou » du matin elle pouvait reprendre la blague de la veille. Le repère seul qui
    précède un de ses messages (``ChatPrompt.chat_messages``) passe sur ce message."""
    entries: list[list[str]] = []
    pending = ""
    for m in history:
        mark, rest = ("", m.content) if m.role == "assistant" else unlabel(m.content)
        mark = mark or pending
        lines = _thread_lines(m.role, rest, name)
        if not lines:
            pending = mark
            continue
        pending = ""
        entries.append([phrase("expression.polish.mark", mark=mark), *lines] if mark else lines)
    return [line for entry in entries[-_POLISH_THREAD:] for line in entry]


def _unquoted(text: str) -> str:
    """Une ligne tout entière entre guillemets, sans eux ; ceux d'une citation qui la finit restent (le 2026-10-27,
    « … un simple « j'achète et je touche plus à rien » » perdait son guillemet fermant, et il ne comprenait plus)."""
    m = _QUOTED.match(text)
    return next(g for g in m.groups() if g is not None).strip() if m else text


def authored(text: str, name: str) -> str:
    """Ses messages dans la suite écrite par l'autrice : les lignes « {name} : … » (ou sans nom) jusqu'à la première
    de l'autre ou au premier repère de temps, une bulle chacune (séparées par une ligne vide) ; « » si l'autrice ne
    lui fait rien dire. Un repère (« [le soir, mardi 19h04] ») dit que du temps a passé : ce qui suit est un message
    d'après, inventé avec la suite du fil (le 2026-10-27, « alors, cette terrasse ? » du soir est parti à 9h51)."""
    out: list[str] = []
    # deux messages sur une ligne (« … Mika : … », « … [plus tard] L'autre : … ») : chacun sur la sienne
    them = phrase("expression.polish.them", text="").strip()
    split = re.compile(rf"\s+(?=(?:\[[^\]\n]*\]\s*)?(?:{re.escape(name)}|{re.escape(them.rstrip(':').strip())})\s*:)")
    for line in (part for raw in (text or "").splitlines() for part in split.split(raw)):
        line = _unquoted(line.strip())
        mark = _TIME_MARK.match(line)
        if mark and not PROSODY.match(line) and not line.startswith(SILENCE_TOKEN):
            if out:
                break
            line = line[mark.end():]  # le repère de ce message-ci, redit avant lui
        if not line:
            continue
        who = _SPEAKER.match(line)
        label = who.group(1).strip() if who else ""
        if label and fold(label.split("(")[0].strip().lower()) == fold(name.lower()):  # « Mika (brouillon) »
            said = _unquoted(who.group(2).strip())  # « Mika : « coucou » »
        elif label[:1].isupper():
            break  # l'autre (« L'autre : … », un prénom) : la suite n'est plus à elle
        else:
            said = line  # « bon : t'as raison » est une bulle à elle, pas un nom
        if said:
            out.append(said)
    return "\n\n".join(out)


def stops() -> tuple[str, ...]:
    """Où l'autrice s'arrête d'écrire (``LLMRequest.stop_sequences``, ADR 0261) : le début d'une ligne de l'autre, tel
    que le fil le montre (``expression.polish.them`` : « L'autre : ») — avec ou sans espace avant les deux-points,
    l'apostrophe droite ou typographique. Ce qu'on garde de sa suite (``authored``) finit à cette ligne : ce qui la
    suit ne s'écrit plus. Toujours en début de ligne : dans un de ses messages, « L'autre : » ne coupe rien. Une forme
    que ces séquences ne prévoient pas (un prénom, du gras) laisse l'appel aller au bout, et ``authored`` coupe."""
    other = phrase("expression.polish.them", text="").strip().rstrip(":").strip()
    forms = dict.fromkeys((other, other.replace("'", "’")))
    return tuple(f"\n{form}{colon}" for form in forms for colon in (" :", ":"))


#: les sections de son état qui disent qui est l'autre (qui écrit, le ton entre eux, sa fiche), que l'autrice lit
OTHER_SECTIONS = ("who", "register", "about_person")


#: « Nom : … » en tête d'une ligne de SMS (un nom court, éventuellement en gras)
_SPEAKER = re.compile(r"^\**([^:*\n]{1,24}?)\**\s*:\s*(.*)$")
#: un repère de temps en tête de ligne, comme ceux du fil (``expression.polish.mark``) — un jeton de voix aussi, que
#: l'appelant écarte
_TIME_MARK = re.compile(r"^\[[^\]\n]*\]\s*")
#: une ligne tout entière entre guillemets, sans autre guillemet dedans
_QUOTED = re.compile(r'^(?:«([^«»]*)»|"([^"]*)"|“([^“”]*)”)$')


def polish(draft: str, messages: Sequence[Any], heard: str = "", persona: Any = None, author: Any = None,
           bodies: Mapping[str, str] | None = None
           ) -> tuple[str, str, Callable[[str], str], tuple[str, ...]] | None:
    """La seconde passe sur sa réponse : (consigne, message, ce qu'on garde de la suite écrite, où s'arrêter de
    l'écrire — ``stops``) d'un appel où une autrice écrit la suite du fil à partir de son premier jet, ou ``None``
    sans premier jet. ``persona`` : sa persona
    rendue pour la conversation (``text``, ``name``, ``reference`` : un fil de référence pour le registre) ;
    ``author`` : l'autrice du chat (``vocab.flows.Author``, ADR 0124) — ses codes s'ajoutent au cadre, son exemple
    prend la place du fil de référence ; ``bodies`` : le texte de chaque section de son prompt, par clé — l'autrice
    en lit qui est l'autre (``OTHER_SECTIONS``)."""
    text = _bubbles(draft)
    if not text:
        return None
    name = getattr(persona, "name", "") or phrase("expression.polish.unnamed")
    turns = [m for m in messages if getattr(m, "role", "") in ("user", "assistant") and (m.content or "").strip()]
    state = turns[-1].content if turns and turns[-1].role == "user" else ""
    history = turns[:-1] if state else turns
    lines = _thread(history, name)
    # le moment du message en cours par rapport au dernier (pour ce qu'elle lance d'elle-même : de maintenant), en
    # tête de ce qui suit son état interne
    now = unlabel(state.split(CONTEXT_FOOTER, 1)[-1].lstrip())[0]
    if now:
        lines.append(phrase("expression.polish.mark", mark=now))
    # ce que la personne vient d'écrire — jamais le cadrage d'un épisode (« personne ne vient de t'écrire… »)
    if _plain(heard):
        lines.append(phrase("expression.polish.them", text=_plain(heard)))
    system = phrase("expression.polish.system", name=name, portrait=(getattr(persona, "text", "") or "").strip())
    # qui est l'autre, d'après ce qu'elle a vécu avec lui (sa fiche, déjà filtrée pour cette audience) : l'autrice
    # écrit aussi ses réponses à venir (banc du 2026-10-16 : avec sa fiche, il plaisante comme lui)
    other = [body for key in OTHER_SECTIONS if (body := (bodies or {}).get(key, "").strip())]
    if other:
        system += "\n\n" + phrase("expression.polish.other", name=name, about="\n".join(other))
    codes = (getattr(author, "codes", "") or "").strip()
    if codes:
        system += "\n\n" + phrase("expression.polish.codes", codes=codes)
    reference = (getattr(author, "example", "") or "").strip() or (getattr(persona, "reference", "") or "").strip()
    if reference:
        system += "\n\n" + phrase("expression.polish.reference", thread=reference, name=name)
    message = phrase("expression.polish.message", thread="\n".join(lines), name=name,
                     draft=" / ".join(text.split("\n\n")))
    return system, message, lambda written: authored(written, name), stops()


def polish_draft(flow: str, draft: str, about: str, author: Any) -> tuple[str, str] | None:
    """La passe d'une autrice sur un brouillon d'outil (ADR 0124) : (consigne, message) d'un appel qui le récrit dans
    le genre de son flux (un courriel, un message Teams ou un SMS écrits à la place de la personne) et selon ses codes,
    sans rien y ajouter ; ``None`` pour une forme qui ne se récrit pas ainsi (le chat a sa seconde passe) ou un
    brouillon vide. ``about`` : ce à quoi il répond."""
    form = flows.form_of(flow)
    text = (draft or "").strip()
    if form not in flows.DRAFTS or not text:
        return None
    parts = [phrase("expression.author.system", genre=phrase(f"expression.author.genre.{form}"))]
    codes = (getattr(author, "codes", "") or "").strip()
    if codes:
        parts.append(phrase("expression.author.codes", codes=codes))
    example = (getattr(author, "example", "") or "").strip()
    if example:
        parts.append(phrase("expression.author.example", example=example))
    message = phrase("expression.author.message", about=(about or "").strip() or phrase("expression.author.opening"),
                     draft=text)
    return "\n\n".join(parts), message
