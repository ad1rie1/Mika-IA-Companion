"""Les blocs du prompt — un formateur par question, jamais une requête brute.

Chaque fonction répond à une question du tour (« que sait-elle de cette
personne ? », « a-t-elle rêvé cette nuit ? », « qu'a-t-elle en train ? »)
et rend le corps d'une section de ``pipeline.prompt``, ou ``""`` quand il
n'y a rien à dire. Les lectures passent par la couche de lecture
(``memory.read``, ``conscience.read``) — les tests de
``test_inner_state_read`` interdisent ici tout ``Model.objects`` direct.
``pipeline.context`` orchestre ; ce module ne lit ni le tampon
d'historique, ni le rappel mémoire, ni les outils.
"""

import re as _re_mood

from old.backend.configs.runtime import cfg_float, cfg_int
from old.backend.drives.engine import drive_engine
from old.backend.emotion.engine import emotion_engine
from old.backend.identity import divulgation as div
from old.backend.identity.resolver import identity_resolver
from old.backend.identity.trust import ChannelTrust
from old.backend.pipeline.context_history import _last_contact_gap
from old.backend.utils.degradation import degradations


# ── Plafonds des blocs sans borne naturelle ─────────────────────────────────
# Chaque bloc du prompt doit porter sa propre limite : rien en aval ne mesure
# ni ne tronque (pas de tokenizer dans le processus), donc un bloc qui grossit
# sans borne — un self-narrative que le consolidateur allonge, un module
# bavard, un projet aux consignes fleuves — gonfle chaque tour en silence.
# Les valeurs sont larges : le but est d'empêcher la dérive, pas de rogner
# le cas nominal.
# Ces cinq valeurs sont le repli des réglages ``pipeline.context.*``
# (section « Tour · Contexte ») et leur sont identiques au bit près.
_SELF_CONCEPT_MAX_CHARS = 1600
_MODULE_CONTEXT_MAX_CHARS = 1800
_PROJECT_TEXT_MAX_CHARS = 300
_PROJECT_LIST_ITEMS_MAX = 8
_IDENTITY_CLAIMS_MAX = 5


def _plafond_texte_projet() -> int:
    return cfg_int("pipeline.context.project_text_max_chars",
                   _PROJECT_TEXT_MAX_CHARS, mini=1)


def _plafond_liste_projet() -> int:
    return cfg_int("pipeline.context.project_list_items_max",
                   _PROJECT_LIST_ITEMS_MAX, mini=1)


def _plafond_revendications() -> int:
    return cfg_int("pipeline.context.identity_claims_max",
                   _IDENTITY_CLAIMS_MAX, mini=1)


def _clip(text: str, limit: int) -> str:
    """Hard cap with a visible marker — a silent slice hides the loss."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_identity_block(ctx) -> str:
    """Render the identity situation as the `--- QUI TU AS EN FACE ---` body.

    Silent for internal person_ids (Mika's own conscience triggers don't need
    to be told who they are) and silent when an authenticated session made
    the question moot *and* nothing is pending — in that case the person
    context block already names them, and a paragraph explaining that she is
    certain would only invite the model to talk about certainty.
    """
    if ctx.is_internal:
        return ""

    # Session authentifiee et rien en attente : la question ne se pose pas.
    # `describe_fr` rendrait « Aucun doute a avoir », ce qui n'apprend rien de
    # plus que le bloc suivant et invite le modele a parler de sa certitude.
    if ctx.trust is ChannelTrust.AUTHENTICATED and not ctx.pending_claims:
        return ""

    lines = [ctx.description] if ctx.description else []

    if ctx.pending_claims:
        lines.append("")
        # Compte borné : chaque ligne coûte à chaque tour, et au-delà de
        # quelques revendications simultanées le modèle n'arbitre plus rien.
        plafond_revendications = _plafond_revendications()
        for claim in ctx.pending_claims[:plafond_revendications]:
            lines.append(
                f"- Revendication #{claim['id']} : se presente comme "
                f"« {claim['name']} » (« {claim['evidence'][:140]} »)"
            )
        hidden = len(ctx.pending_claims) - plafond_revendications
        if hidden > 0:
            lines.append(f"- (+{hidden} autre(s) revendication(s) en attente)")
        lines.append(
            "Tu peux la tester avec identity_check_story (est-ce que ce qui "
            "est dit recoupe ce que tu sais ?), puis trancher avec "
            "identity_accept_claim ou identity_reject_claim. Rien ne t'oblige "
            "a decider maintenant — tu as le droit de rester prudente et de "
            "poser une question dont seule la vraie personne aurait la reponse."
        )
    elif not ctx.may_disclose and not ctx.is_identified:
        lines.append(
            "Si tu veux savoir a qui tu parles, demande-le simplement — "
            "c'est plus honnete que de deviner."
        )

    return "\n".join(line for line in lines if line is not None).strip()


def _format_project_block(data: dict) -> str:
    """Render a dict from ``detection.load_project_for_prompt`` as the
    body of the ``--- PROJET EN COURS ---`` prompt section.

    Conservative with wording — the LLM will read this as directive,
    not descriptive. When emotion_policy is OFF the block explicitly
    reminds the model to drop emoji / informal markers.
    """
    plafond_texte = _plafond_texte_projet()
    plafond_liste = _plafond_liste_projet()
    lines: list[str] = [f"Titre : {data['title']}"]
    if data.get("description"):
        lines.append(f"Cadre : {_clip(data['description'], 2 * plafond_texte)}")
    if data.get("tone_directive"):
        lines.append(f"Ton à utiliser : {_clip(data['tone_directive'], plafond_texte)}")
    instr = data.get("instructions") or []
    if instr:
        lines.append("Consignes :")
        for i in instr[:plafond_liste]:
            lines.append(f"  - {_clip(i, plafond_texte)}")
    oos = data.get("out_of_scope") or []
    if oos:
        lines.append("Hors de portée :")
        for o in oos[:plafond_liste]:
            lines.append(f"  - {_clip(o, plafond_texte)}")

    policy = data.get("emotion_policy", "off")
    if policy == "off":
        lines.append(
            "Politique émotionnelle : OFF. "
            "N'inclus PAS de balise [EMOTION:...]. "
            "Pas d'emojis, pas de langage familier, pas d'interjections "
            "(pff, hehe, mdr). Ton factuel et posé uniquement."
        )
    elif policy == "muted":
        lines.append(
            "Politique émotionnelle : atténuée. "
            "Tu peux inclure [EMOTION:...] mais avec une intensité modérée "
            "(≤ 0.5). Pas d'exubérance."
        )
    # policy == "full" → default personality behavior, no extra line needed.

    if data.get("requires_approval"):
        lines.append(
            "Actions à effet de bord : à soumettre à l'utilisateur avant "
            "exécution (aucune envoi / écriture sans approbation)."
        )

    todo = data.get("todo_tasks") or []
    if todo:
        lines.append("Tâches en cours / à faire :")
        for t in todo[:5]:
            lines.append(f"  - {t}")

    return "\n".join(lines)


def _fatigue_fog_context() -> str:
    """Return a short French sentence shaping Mika's TONE when her energy
    is low — a "cognitive fog" layer distinct from the action threshold.

    Empty string when energy is mid-to-high: sober humans don't need the
    reminder. Only kicks in below ~0.5 and ramps up as energy drops.
    """
    try:
        energy = float(drive_engine.energy_level())
    except (TypeError, ValueError, Exception):
        # Defensive: drive_engine may be mocked in tests returning a
        # non-numeric value. Absence of fog is a safe default.
        return ""

    if energy >= 0.5:
        return ""
    if energy >= 0.3:
        return (
            "Tu sens une petite baisse de regime. Tes phrases peuvent etre un "
            "peu plus courtes, tu accroches moins vite, ton humour est plus "
            "calme. Ce n'est pas grave — tu restes toi, juste en version moins "
            "explosive."
        )
    if energy >= 0.15:
        return (
            "Tu es clairement fatiguee. Tes pensees partent en vrille plus "
            "facilement, tu laisses des phrases en suspens, tu as moins de "
            "patience pour te relire. Laisse-toi etre moins parfaite — c'est "
            "plus honnete que faire semblant d'etre fraiche."
        )
    return (
        "Tu es epuisee. Tes associations d'idees flottent, tu confonds des "
        "mots, tu peux demander de repeter. Tu n'as pas l'energie pour des "
        "reponses travaillees — va au plus simple, quitte a etre un peu "
        "a cote de la plaque. Un humain crame ne dissimule pas, il fatigue."
    )


# Dream-recall window: after waking, for how many hours is last night's
# dream eligible to surface in the prompt. Keeps the residue morning-
# bound — a dream from last night shouldn't pop up at 21h.
# Repli de ``pipeline.context.dream_recall_window_hours``.
_DREAM_RECALL_WINDOW_HOURS = 8
# Only dreams above this vividness are mentionable at all — faint ones
# stay purely internal (they still nudged the self-narrative elsewhere).
# Repli de ``pipeline.context.dream_vividness_threshold``.
_DREAM_VIVIDNESS_THRESHOLD = 0.6


async def _fetch_dream_context() -> tuple[str, object | None]:
    """Return ``(residue, dream)`` for last night's dream, or ``("", None)``.

    Gating: current hour must be before the profile-derived night end + window, the
    dream must not have been recalled yet, and vividness above threshold.

    The dream is *not* marked here. Marking it during context assembly spent
    it before the AI call, so a timeout consumed it forever while the fallback
    never mentioned it — the caller marks it once the turn succeeded.
    """
    from datetime import datetime

    from old.backend.memory import read
    from old.backend.memory.sleep import SleepCycle

    now = datetime.now()
    # La fin de nuit appartient au cycle de sommeil : on lit SON accesseur —
    # dérivé du profil circadien (phase MORNING) depuis que la clé
    # `memory.sleep_night_end_hour` est supprimée. Relire une clé morte ici
    # aurait fait diverger la fenêtre du rêve de la nuit réelle sur tout
    # profil nocturne — la divergence exacte que la dérivation supprime.
    fin_de_nuit = SleepCycle._night_end_hour()
    fenetre = cfg_int("pipeline.context.dream_recall_window_hours",
                      _DREAM_RECALL_WINDOW_HOURS, mini=1)
    # Only eligible in the morning window [fin de nuit, +fenêtre]
    if not (fin_de_nuit <= now.hour < fin_de_nuit + fenetre):
        return "", None

    try:
        dream = await read.dream_of_last_night(
            unrecalled_only=True,
            min_vividness=cfg_float(
                "pipeline.context.dream_vividness_threshold",
                _DREAM_VIVIDNESS_THRESHOLD, mini=0.0, maxi=1.0),
        )
    except Exception as exc:
        degradations.record("prompt: dream context", exc)
        return "", None

    if not dream:
        return "", None

    # Build a human-readable residue hint.
    type_label = {
        "associative": "un reve un peu bizarre, des associations libres",
        "nightmare": "un reve inconfortable, pas tragique mais derangeant",
        "pleasant": "un reve plutot doux",
        "mundane": "un reve banal mais tu t'en souviens quand meme",
    }.get(dream.dream_type, "un reve")
    emotion_hint = f" (teinte : {dream.emotion})" if dream.emotion else ""
    return (
        f"Tu as fait cette nuit {type_label}{emotion_hint}.\n"
        f"Le souvenir du reve : \"{dream.content[:400]}\"\n"
        "Tu peux le mentionner si la conversation s'y prete (ou au contraire "
        "le garder pour toi). N'en parle pas tout de suite si l'autre commence "
        "par quelque chose d'important — laisse la conversation couler naturellement.",
        dream,
    )


# Cap on the journal narrative injected into the prompt — the recap is
# a thread, not a transcript.
# Repli de ``pipeline.context.journal_max_chars``.
_JOURNAL_MAX_CHARS = 450


def _redige_sans_tiers(texte: str, noms: list[str]) -> str:
    """Remplace les noms de tiers par « quelqu'un » dans un texte libre.

    Le récit du journal est écrit à la première personne à partir des
    souvenirs de la veille : il cite donc les gens et ce qu'ils ont confié.
    On ne connaît pas d'autre inventaire de ces noms que
    ``persons_interacted``, ce qui suffit — ce sont exactement les personnes
    que la nuit a identifiées dans sa journée.
    """
    import re as _re

    for nom in sorted((n for n in noms if n and len(n) > 2), key=len, reverse=True):
        texte = _re.sub(
            rf"\b{_re.escape(nom)}\b", "quelqu'un", texte, flags=_re.IGNORECASE,
        )
    return texte


async def divulgation_du_tour(identity_ctx) -> div.Divulgation:
    """Le niveau de divulgation du tour (``identity.divulgation``), calculé
    une fois, au bord, à partir de ce que l'identité vient de résoudre.

    Les cinq faits : la certitude effective et le canal (``identity_ctx``,
    déjà clampés), la proximité de l'interlocuteur (``PersonProfile`` de
    l'entité liée — une colonne), la chaleur de l'ancre affective
    (``emotion_engine.chaleur_envers``, RAM) ; la proximité avec la personne
    concernée est la facette ``avec_temoin``, décidée ligne par ligne par le
    retriever. Un tour interne (conscience, pas de chantier) porte sa mémoire
    entière ; un ``anon_*`` tombe sur ``anodin`` par la politique (certitude
    nulle) ; une panne ferme (``FERME``), comptée.
    """
    if identity_ctx.is_internal:
        return div.TOUT
    try:
        from old.backend.identity.resolver import politique_divulgation
        from old.backend.memory import read

        closeness = await read.closeness_of(identity_ctx.entity_id)
        chaleur = await emotion_engine.chaleur_envers(identity_ctx.person_id)
        return div.decider(
            float(identity_ctx.certainty), identity_ctx.trust,
            closeness=closeness, chaleur=chaleur,
            fiche_ouverte=bool(identity_ctx.may_disclose),
            tuning=politique_divulgation(),
        )
    except Exception as exc:
        degradations.record("prompt: niveau de divulgation", exc)
        return div.FERME


async def _fetch_journal_context(niveau: div.Niveau = div.Niveau.CONFIDENCE) -> str:
    """Return a compact recap of yesterday's journal, or ''.

    ``niveau`` est le niveau de divulgation du tour. Le bloc n'était gardé
    que par ``is_internal_person`` : un handle jamais identifié recevait
    donc, dès son premier « salut », le récit à la première personne de la
    veille — « Thomas m'a raconté que sa mère était hospitalisée » — et la
    liste nominative des gens croisés, dans le prompt même où le bloc
    identité lui dit de ne rien raconter de personnel sur qui que ce soit.
    L'outil ``memory_read_journal``, lui, refusait déjà.

    Sous ``personnel``, elle garde son fil — c'est le sien — mais elle ne
    nomme plus personne. À partir de ``personnel``, le fil est complet.

    The nightly journal gives Mika a causal thread through the previous
    day; without this injection it was write-only (frontend panel + tool
    only) and "hier" relied on semantic retrieval luck. Available all
    day: unlike a dream, yesterday doesn't fade by mid-afternoon.
    """
    from old.backend.memory import read

    # Strictly yesterday, not "the latest": light sleep writes a journal late
    # on the evening of the day it covers, so between 23h and midnight the
    # newest row is *today's*. A block titled "ton fil d'hier" must not
    # narrate the day currently in progress. The panels ask the other
    # question — see memory.read.latest_journal.
    try:
        journal = await read.journal_for(read.yesterday())
    except Exception as exc:
        degradations.record("prompt: journal context", exc)
        return ""

    if not journal or not journal.narrative:
        return ""

    plafond = cfg_int("pipeline.context.journal_max_chars",
                      _JOURNAL_MAX_CHARS, mini=1)
    narrative = journal.narrative.strip()
    if len(narrative) > plafond:
        narrative = narrative[:plafond].rstrip() + "..."

    persons = [p for p in (journal.persons_interacted or []) if p]

    may_disclose = div.RANG[niveau] >= div.RANG[div.Niveau.PERSONNEL]
    if not may_disclose:
        narrative = _redige_sans_tiers(narrative, persons)

    lines = [f"Ce que tu retiens d'hier : {narrative}"]
    if persons and may_disclose:
        lines.append("Tu avais interagi avec : " + ", ".join(persons[:4]) + ".")
    if journal.dominant_emotion:
        lines.append(f"La journee etait teintee de : {journal.dominant_emotion}.")
    if may_disclose:
        lines.append(
            "C'est ton fil de continuite — tu peux y faire reference naturellement "
            "(\"comme hier...\") sans le reciter."
        )
    else:
        lines.append(
            "C'est ton fil de continuite, pour toi. Tu ne sais pas assez qui "
            "tu as en face pour raconter ta journee ni nommer les gens que tu "
            "as croises — garde ca pour toi, ca colore juste ton humeur."
        )
    return "\n".join(lines)


async def _fetch_rumination_context() -> str:
    """Return a short French block describing the top active ruminations.

    These are unresolved thoughts promoted from stale pertinent observations.
    Were previously visible only during conscience._act(); surfacing them
    every turn lets them color REACTIONS too, not just spontaneous speech.
    Empty string when the table is missing, empty, or intensities are low.
    """
    from old.backend.conscience import read as conscience_read

    try:
        # Top 3 above a floor: a thought too faint to notice should not be
        # narrated as one. The panel shows more, and fainter — see
        # conscience.read.active_ruminations.
        items = await conscience_read.active_ruminations(
            limit=3, min_intensity=0.2,
        )
    except Exception as exc:
        degradations.record("prompt: rumination context", exc)
        return ""

    return format_ruminations([
        {"summary": r.summary, "intensity": r.intensity, "emotion": r.emotion}
        for r in items
    ])


def format_ruminations(items: list[dict]) -> str:
    """Même présentation pour le rappel courant et le lot retenu d'un acte."""
    if not items:
        return ""
    lines = []
    for r in items:
        label = "fortement" if r["intensity"] > 0.7 else (
            "encore" if r["intensity"] > 0.4 else "par intermittence"
        )
        line = f"- Tu repenses {label} a : {r['summary'][:140]}"
        if r.get("emotion"):
            line += f" (teinte : {r['emotion']})"
        lines.append(line)
    return (
        "Meme si tu reponds a ce qui arrive maintenant, ces pensees restent "
        "en arriere-plan et colorent subtilement ton humeur :\n"
        + "\n".join(lines)
    )


async def _fetch_travaux_context() -> str:
    """Un court bloc français : ses chantiers en cours, et ceux finis du jour.

    Même couche de lecture que le tableau de bord (`conscience.read`), jamais
    une requête directe ici — la règle qui a déjà servi aux ruminations et au
    journal. Aucun nombre destiné à être relu par une machine : le prompt dit
    « presque au bout », pas « pas 4/5 à envie 0.31 ».
    """
    from old.backend.conscience import read as conscience_read

    try:
        en_cours = await conscience_read.travaux_en_cours(limit=3)
        aboutis = await conscience_read.travaux_aboutis_depuis(
            conscience_read.debut_du_jour_local(), limit=2,
        )
    except Exception as exc:
        degradations.record("prompt: travaux context", exc)
        return ""

    if not en_cours and not aboutis:
        return ""

    lines = []
    for t in en_cours:
        etape = ""
        if t.pas_max:
            if t.pas_effectues <= 0:
                etape = " (tu n'as pas encore commence)"
            elif t.pas_effectues >= t.pas_max - 1:
                etape = " (presque au bout)"
            else:
                etape = " (en cours)"
        if not t.en_attente_de_reponse:
            attente = ""
        elif getattr(t, "attend_qui", ""):
            attente = (
                f" Tu attends une reponse de {t.attend_qui} pour continuer."
            )
        else:
            attente = " Tu attends une reponse pour continuer."
        lines.append(f"- Tu as entrepris : {t.titre[:140]}{etape}.{attente}")
    for t in aboutis:
        lines.append(f"- Tu as mene au bout aujourd'hui : {t.titre[:140]}.")
    return (
        "Ce sont TES chantiers — des choses que tu as decide de faire de "
        "toi-meme. Tu peux en parler si on te demande ce que tu fais :\n"
        + "\n".join(lines)
    )


# Regex assets for user-mood heuristic
_CAPS_RUN = _re_mood.compile(r"[A-ZÉÈÀÔÂÊÎÛ]{4,}")
_EXCLAM_RUN = _re_mood.compile(r"!{2,}")
_QUESTION_RUN = _re_mood.compile(r"\?{2,}")
_ELLIPSIS_RUN = _re_mood.compile(r"\.{3,}|…")
_POSITIVE_WORDS = {
    "super", "génial", "genial", "trop bien", "j'adore", "jadore",
    "youpi", "merci", "haha", "mdr", "lol", "ptdr", "yes", "nickel",
    "parfait", "cool", "top",
}
_NEGATIVE_WORDS = {
    "triste", "déprimé", "deprime", "naze", "nul", "marre", "fatigué",
    "fatigue", "épuisé", "epuise", "galère", "galere", "chiant", "putain",
    "merde", "j'en peux plus", "ras le bol", "pleure",
}
_ANGRY_WORDS = {
    "énervé", "enerve", "furieux", "rage", "dégueu", "degueu",
    "honteux", "insupportable",
}


def detect_user_mood_hint(message: str) -> str:
    """Heuristic read of the user's emotional tone from raw text.

    This does NOT call the AI — it's fast, cheap, and deterministic.
    Gives Mika "she sounds pissed", "they seem down", "excited" cues
    she can react to rather than only declaring her own emotion.

    Returns '' when no confident signal — silence beats noise in a prompt.
    """
    if not message or len(message.strip()) < 2:
        return ""

    text = message.strip()
    low = text.lower()

    signals = []

    # Structural cues
    caps_hits = len(_CAPS_RUN.findall(text))
    if caps_hits >= 1 and len(text) >= 6:
        signals.append("en majuscules (ton elevé ou emphase)")

    if _EXCLAM_RUN.search(text):
        signals.append("plusieurs points d'exclamation — emotion marquee")
    if _QUESTION_RUN.search(text):
        signals.append("questions en rafale — surprise ou doute")
    if _ELLIPSIS_RUN.search(text):
        signals.append("des points de suspension — hesitation, lassitude ou flou")

    # Length cue
    words = len(text.split())
    if words <= 3:
        signals.append("tres court — soit agace, soit pressé, soit peu inspire")
    elif words >= 80:
        signals.append("long message — sujet qui lui tient a coeur ou besoin de vider son sac")

    # Lexical cues
    pos_hits = sum(1 for w in _POSITIVE_WORDS if w in low)
    neg_hits = sum(1 for w in _NEGATIVE_WORDS if w in low)
    ang_hits = sum(1 for w in _ANGRY_WORDS if w in low)

    if ang_hits:
        signals.append("mots qui trahissent de la colere ou de l'exasperation")
    if neg_hits >= 2 or (neg_hits and "pleure" in low):
        signals.append("mots qui trahissent une humeur sombre, tristesse ou epuisement")
    elif neg_hits:
        signals.append("une teinte negative legere")
    if pos_hits:
        signals.append("des marqueurs positifs / enjoues")

    # Emoji burst
    if len(_re_mood.findall(r"[😀-🙏🤔-🫧]", text)) >= 2:
        signals.append("beaucoup d'emojis — registre expressif, chaleureux")

    if not signals:
        return ""

    hint = (
        "Ce que tu captes dans la maniere dont il/elle ecrit (pur ressenti, "
        "tu peux te tromper) : "
        + " ; ".join(signals[:4])
        + ". Accueille-le dans ta reponse au lieu de l'ignorer — une vraie "
        "personne remarque ces signes."
    )
    return hint


def _fetch_circadian_context() -> str:
    """Return a short French description of Mika's current circadian state."""
    try:
        from old.backend.emotion import circadian

        try:
            from old.backend.config.personality import personality
            profile = personality.circadian_profile
        except Exception:
            profile = None

        state = circadian.current_state(profile=profile)
        return circadian.phase_description_fr(state)
    except Exception as exc:
        degradations.record("prompt: circadian context", exc)
        return ""


async def _fetch_self_concept() -> str:
    """Return the most recent self-narrative content, or '' if none."""
    from old.backend.memory import read

    try:
        latest = await read.latest_self_narrative()
        if latest and latest.content:
            return _clip(latest.content,
                         cfg_int("pipeline.context.self_concept_max_chars",
                                 _SELF_CONCEPT_MAX_CHARS, mini=1))
        return ""
    except Exception as exc:
        degradations.record("prompt: self-concept", exc)
        return ""


# System/internal person_ids live in identity.trust — one definition, because
# "is this id a person?" was previously answered in three places that had
# already drifted apart.


async def _fetch_person_context(identity_ctx) -> str:
    """Return a prompt-ready block combining everything Mika knows/feels
    about this specific person:
      - semantic profile (summary, closeness, preferred tone, topics)
      - current affective stance (live PAD oscillator via EmotionEngine)
      - weekly emotional trend (EmotionalSummary)
      - pending commitments toward them

    This block replaces the per-person half of what used to live in
    `emotion_context`. It gives the LLM a unified relational picture.

    Resolution goes through the identity layer, not through
    ``entity__name=person_id``. The old lookup could only ever match when a
    person's memory Entity happened to be named after their transport handle
    — which never happens in practice, because the consolidator names
    entities after what people are *called* ("Thomas") while handles are
    ``web_6f3e22ccb0ae``. Every profile lookup silently missed.

    Empty string when internal/system person_id, when nothing is known, or
    when certainty is too low to justify reading out someone's private
    history to whoever is currently holding the handle.
    """
    person_id = identity_ctx.person_id
    if identity_ctx.is_internal:
        return ""

    affect = emotion_engine.get_person_affect_context(person_id)
    # Le temps écoulé est un fait sur l'échange avec CE handle, pas un extrait
    # de la fiche d'un tiers : il reste sous le seuil de divulgation, au même
    # titre que la stance affective. Sans lui, « tu m'as manqué » n'a aucune
    # base mécanique — le prompt ne porte que l'heure courante et « hier ».
    derniere_interaction = await _last_contact_gap(person_id)

    # Not sure enough who this is: the affective stance toward the handle is
    # still Mika's own feeling and safe to keep, but the semantic profile,
    # the shared history and the commitments are someone else's business.
    if not identity_ctx.may_disclose:
        return "\n".join(x for x in (affect, derniere_interaction) if x)

    entity = None
    try:
        from old.backend.memory import read

        entity = await identity_resolver.entity_for_person(person_id)
        if entity is None:
            return "\n".join(x for x in (affect, derniere_interaction) if x)

        profile = await read.person_profile_for(entity)
        commitments = await read.pending_commitments_for(entity)
        weekly_trend = _summarize_emotional_trend(
            await read.recent_daily_summaries(person_id)
        )

        if (
            not affect
            and not derniere_interaction
            and profile is None
            and not commitments
            and not weekly_trend
        ):
            return ""

        return _format_person_context(
            profile=profile,
            commitments=commitments,
            affect=affect,
            weekly_trend=weekly_trend,
            derniere_interaction=derniere_interaction,
        )

    except Exception as exc:
        degradations.record("prompt: person context", exc)
        # If DB failed but we at least have an affect string, return that —
        # it's better than a silent blank about the person.
        return "\n".join(x for x in (affect, derniere_interaction) if x)


def _format_person_context(
    *, profile, commitments: list[str], affect: str, weekly_trend: str,
    derniere_interaction: str = "",
) -> str:
    """Assemble a compact French block covering everything Mika knows+feels."""
    lines: list[str] = []

    if profile and profile.summary:
        lines.append(profile.summary)

    if profile:
        extras = []
        if profile.closeness and profile.closeness != "stranger":
            extras.append(f"proximite: {profile.closeness}")
        if profile.preferred_tone and profile.preferred_tone != "unknown":
            extras.append(f"ton prefere avec elle/lui: {profile.preferred_tone}")
        if profile.topics_of_interest:
            extras.append(
                "sujets qui l'interessent: "
                + ", ".join(profile.topics_of_interest[:4])
            )
        if profile.sensitive_topics:
            extras.append(
                "sujets sensibles a manier avec prudence: "
                + ", ".join(profile.sensitive_topics[:3])
            )
        if extras:
            lines.append(" | ".join(extras))

    if affect:
        lines.append(affect)

    if derniere_interaction:
        lines.append(derniere_interaction)

    if weekly_trend:
        lines.append(weekly_trend)

    if commitments:
        lines.append(
            "Tu lui avais dit: " + "; ".join(c[:120] for c in commitments)
        )

    return "\n".join(lines)


def _summarize_emotional_trend(summaries: list) -> str:
    """Build a short French line from recent EmotionalSummary rows.

    Empty when fewer than 2 days of data — a single-day snapshot isn't
    really a "trend". Returns e.g. "Sur les 5 derniers jours avec elle/lui
    tu as ete majoritairement happy (tendance warming)."
    """
    if not summaries or len(summaries) < 2:
        return ""

    from collections import Counter
    dominant_per_day = [s.dominant_emotion for s in summaries if s.dominant_emotion]
    if not dominant_per_day:
        return ""

    counter = Counter(dominant_per_day)
    top, top_count = counter.most_common(1)[0]
    most_recent = summaries[0]

    if top_count >= len(summaries) * 0.6:
        return (
            f"Sur les {len(summaries)} derniers jours avec elle/lui tu as ete "
            f"majoritairement {top} (tendance recente: {most_recent.trend})."
        )
    return (
        f"Emotions variees avec elle/lui sur {len(summaries)} jours "
        f"(tendance recente: {most_recent.dominant_emotion}, {most_recent.trend})."
    )
