"""Mise en forme partagée — valeurs brutes → chaînes lisibles.

Ces fonctions ne renvoient **jamais** de balisage. Le HTML est l'affaire des
gabarits ; ici on ne produit que du texte et des identifiants de style. C'est
ce qui permet d'afficher la même valeur dans un tableau, une fiche et une
réponse JSON sans trois implémentations divergentes.
"""
from __future__ import annotations

from datetime import date, datetime

from django.utils import timezone

# Les 29 émotions, dans l'ordre de ``emotion/types.py``. Recopiée ici comme
# **liste close de noms sûrs** : la valeur sert à composer un nom de variable
# CSS (``var(--emo-happy)``), donc une chaîne arbitraire venue de la base ne
# doit jamais y arriver. Un nom inconnu retombe sur ``neutral`` au lieu
# d'injecter n'importe quoi dans un attribut ``style``.
EMOTION_NAMES = frozenset({
    "neutral",
    "happy", "excited", "love", "proud", "grateful",
    "playful", "amused", "hopeful", "relieved",
    "sad", "angry", "scared", "disgusted", "frustrated",
    "lonely", "anxious", "bored", "jealous",
    "surprised", "thinking", "confused", "embarrassed",
    "nostalgic", "dreamy", "determined", "mischievous",
    "curious", "melancholic",
})

# Familles utilisées pour teinter une jauge (positif → vert, négatif → rouge).
POSITIVE_EMOTIONS = frozenset({
    "happy", "excited", "love", "proud", "grateful",
    "playful", "amused", "hopeful", "relieved",
})
NEGATIVE_EMOTIONS = frozenset({
    "sad", "angry", "scared", "disgusted", "frustrated",
    "lonely", "anxious", "bored", "jealous",
})


def emotion_var(name: str | None) -> str:
    """Référence de variable CSS pour une émotion.

    Toujours sûre à interpoler dans un attribut ``style`` : la sortie est
    ``var(--emo-<nom>)`` avec ``<nom>`` pris dans ``EMOTION_NAMES``.
    """
    key = (name or "").strip().lower()
    if key not in EMOTION_NAMES:
        key = "neutral"
    return f"var(--emo-{key})"


def emotion_tone(name: str | None) -> str:
    """``ok`` / ``danger`` / ``""`` — pour teinter une jauge d'intensité."""
    key = (name or "").strip().lower()
    if key in POSITIVE_EMOTIONS:
        return "ok"
    if key in NEGATIVE_EMOTIONS:
        return "danger"
    return ""


def pct(value: float | None, digits: int = 0) -> str:
    """0.734 → ``73 %``. ``None`` → ``—``."""
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.{digits}f} %".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def num(value, digits: int = 2) -> str:
    """Nombre en notation française (virgule décimale)."""
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def dt(value: datetime | date | None) -> str:
    """Horodatage absolu, fuseau local, précision minute."""
    if not value:
        return "—"
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d/%m/%Y %H:%M")
    return value.strftime("%d/%m/%Y")


def dt_full(value: datetime | None) -> str:
    """Idem, à la seconde — pour les journaux où l'ordre compte."""
    if not value:
        return "—"
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%d/%m/%Y %H:%M:%S")


def ago(value: datetime | None) -> str:
    """Ancienneté relative compacte : ``3 min``, ``5 h``, ``12 j``.

    Complète ``dt()`` plutôt qu'elle ne la remplace : le relatif répond à
    « est-ce récent ? », l'absolu à « quand exactement ? ». Les gabarits
    affichent le relatif et mettent l'absolu en ``title``.
    """
    if not value:
        return "—"
    now = timezone.now() if timezone.is_aware(value) else datetime.now()
    delta = now - value
    seconds = delta.total_seconds()
    if seconds < 0:
        # Événement daté dans le futur (action planifiée) : on répond à
        # « dans combien de temps ».
        return "dans " + ago_span(-seconds)
    return ago_span(seconds)


def ago_span(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} s"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h"
    days = int(seconds // 86400)
    if days < 31:
        return f"{days} j"
    if days < 365:
        return f"{days // 30} mois"
    return f"{days // 365} an" + ("s" if days // 365 > 1 else "")


def duration(seconds: float | None) -> str:
    """Durée lisible : ``2 h 14 min``, ``45 s``."""
    if seconds is None:
        return "—"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days} j {hours} h"
    if hours:
        return f"{hours} h {minutes:02d} min"
    return f"{minutes} min {sec:02d} s"


def clip(text: str | None, length: int = 160) -> str:
    """Tronque proprement sur une frontière de mot."""
    s = (text or "").strip()
    if len(s) <= length:
        return s
    cut = s[:length]
    space = cut.rfind(" ")
    if space > length * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:") + "…"


def yes_no(value) -> str:
    return "oui" if value else "non"


def humanize_key(key: str) -> str:
    """``conscience.act_threshold`` → ``Act threshold``.

    Repli quand un déclarant n'a pas fourni de libellé. Volontairement bête :
    un libellé inventé pour une clé qu'on n'a pas lue vaut moins qu'une clé
    brute légèrement mise en forme.
    """
    tail = key.rsplit(".", 1)[-1]
    return tail.replace("_", " ").replace("-", " ").capitalize()


def tone_for_ratio(value: float | None, *, invert: bool = False) -> str:
    """Teinte d'une jauge selon un ratio 0→1.

    ``invert=True`` quand une valeur haute est mauvaise (tension d'un drive,
    consommation d'un quota).
    """
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if invert:
        if v >= 0.85:
            return "danger"
        if v >= 0.6:
            return "warn"
        return "ok"
    if v >= 0.66:
        return "ok"
    if v >= 0.33:
        return "warn"
    return "danger"
