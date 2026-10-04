"""Historique étiqueté et daté — qui a parlé, et quand.

Le tampon court terme est un fil unique partagé par tout le monde, et
c'est voulu (voir ``memory.manager``). Ce module lui rend ce qu'il ne porte
pas : un ``speaker`` sur les tours d'un autre interlocuteur, un marqueur de
temps sur les segments séparés par un trou, et la phrase « on ne s'est pas
parlé depuis … » lue sur le dernier message de la personne en face.
Consommé par ``pipeline.context`` ; ne formate aucun bloc de prompt.
"""

from old.backend.configs.runtime import cfg_int
from old.backend.identity.resolver import identity_resolver
from old.backend.utils.degradation import degradations




# Comment designer un tour venu de quelqu'un dont aucun nom n'est connu.
# Vague exprès : « web_6f3e22ccb0ae » n'apprendrait rien au modele, alors
# que « quelqu'un d'autre » dit tout ce qui compte — ce n'est pas la
# personne en face.
_UNKNOWN_SPEAKER = "quelqu'un d'autre"


async def _label_history_speakers(history: list[dict], person_id: str) -> list[dict]:
    """Marque les tours dits par quelqu'un d'autre que l'interlocuteur courant.

    Seuls les tours ``user`` d'un autre ``person_id`` recoivent un
    ``speaker`` : les reponses de Mika sont les siennes quel que soit le
    destinataire, et un tour de la personne en face n'a rien a signaler. Le
    prompt ne paie donc un nom que quand le locuteur change.

    Une seule requete groupee, et uniquement s'il y a effectivement un autre
    locuteur — le cas mono-interlocuteur, qui est le nominal, ne coute rien.
    Les entrees non marquees sont renvoyees telles quelles (jamais mutees :
    ``get_conversation_context`` ne copie que la liste, pas les dicts).
    """
    others = {
        (msg.get("person_id") or "")
        for msg in history
        if msg.get("role") == "user"
    } - {person_id, ""}
    if not others:
        return history

    # « Un autre » se mesure à l'identité, pas au handle : la même personne
    # liée sur le web (``user_5``) et sur Telegram (``tg_9``) voyait ses
    # propres tours Telegram étiquetés comme ceux d'un tiers dans son prompt
    # web. Même périmètre que ``_last_contact_gap`` ; ``own_handles`` se
    # replie sur le handle brut et compte l'échec. Payé seulement quand un
    # handle étranger apparaît — le cas mono-interlocuteur reste gratuit.
    others -= set(await own_handles(person_id))
    if not others:
        return history

    try:
        names = await identity_resolver.display_names_for(sorted(others))
    except Exception as exc:
        degradations.record("prompt: history speakers", exc)
        names = {}

    labelled: list[dict] = []
    for msg in history:
        if msg.get("role") == "user" and (msg.get("person_id") or "") in others:
            speaker = names.get(msg["person_id"]) or _UNKNOWN_SPEAKER
            labelled.append({**msg, "speaker": speaker})
        else:
            labelled.append(msg)
    return labelled


async def own_handles(person_id: str) -> list[str]:
    """Les handles de l'identité de ``person_id`` — repli fermé sur le sien.

    Même formule que ``retriever._episodic_lane`` : la politique « own
    identity only » ne doit pas avoir deux définitions selon la voie qui la
    demande. Une résolution qui échoue ferme le périmètre, jamais l'inverse.
    """
    try:
        rows = await identity_resolver.handles_for_person(person_id)
        handles = sorted({h["person_id"] for h in rows if h.get("person_id")})
        return handles or [person_id]
    except Exception as exc:
        degradations.record("identite: perimetre des handles", exc)
        return [person_id]


# En deçà, deux messages sont la même conversation : le cas nominal ne doit
# pas payer une ligne de prompt à chaque tour, et un fil continu ne doit pas
# se retrouver tapissé de marqueurs.
#
# Deux cadrans distincts malgré la valeur identique, et ils le restent en
# configuration (``pipeline.context.gap_mention_floor_hours`` et
# ``pipeline.context.history_gap_hours``) : le premier décide si Mika *dit* à
# quelqu'un qu'on ne s'est pas parlé depuis un moment, le second date un
# segment de l'historique rejoué au modèle. Les fusionner ferait dépendre une
# phrase adressée à une personne d'un réglage de mise en forme du fil.
_ECART_PLANCHER_S = 6 * 3600
_HISTORY_GAP_SECONDS = 6 * 3600


def _ecart_plancher_s() -> int:
    return cfg_int("pipeline.context.gap_mention_floor_hours",
                   _ECART_PLANCHER_S // 3600, mini=1) * 3600


def _history_gap_seconds() -> int:
    return cfg_int("pipeline.context.history_gap_hours",
                   _HISTORY_GAP_SECONDS // 3600, mini=1) * 3600

_EN_LETTRES = {
    2: "deux", 3: "trois", 4: "quatre", 5: "cinq", 6: "six",
    7: "sept", 8: "huit", 9: "neuf", 10: "dix", 11: "onze",
}


def _duree_approx(seconds: float) -> str:
    """Durée en prose française, arrondie. Jamais un nombre de secondes.

    Le prompt se lit, il ne se calcule pas : « depuis 1814400s » n'aide pas
    un modèle qui doit ensuite écrire « ça fait un moment ».
    """
    jours = max(0.0, seconds) / 86400
    if jours < 1:
        return "quelques heures"
    if jours < 2:
        return "un jour"
    if jours < 7:
        return f"{_EN_LETTRES.get(int(jours), int(jours))} jours"
    if jours < 14:
        return "une semaine"
    if jours < 30:
        semaines = int(jours // 7)
        return f"{_EN_LETTRES.get(semaines, semaines)} semaines"
    if jours < 60:
        return "un mois"
    mois = int(jours // 30)
    return f"{_EN_LETTRES.get(mois, mois)} mois"


def _phrase_ecart(seconds: float) -> str:
    """Le temps écoulé depuis le dernier échange, ou '' s'il est négligeable."""
    if seconds < _ecart_plancher_s():
        return ""
    if seconds < 86400:
        return "Vous vous etes deja parle plus tot dans la journee."
    if seconds < 2 * 86400:
        return "Vous ne vous etes pas parle depuis hier."
    return f"Vous ne vous etes pas parle depuis {_duree_approx(seconds)}."


async def _last_contact_gap(person_id: str) -> str:
    """Depuis combien de temps cette personne ne s'est pas manifestée.

    Rien du tout quand aucune ligne n'existe : dire « c'est la premiere fois »
    contredirait une identité liée qui revient sur un nouveau handle, et une
    absence de donnée n'est pas un fait sur la relation.
    """
    from django.db.models import Max
    from django.utils import timezone

    from old.backend.memory.models import Message

    try:
        handles = await own_handles(person_id)
        row = await Message.objects.filter(
            person_id__in=handles, is_internal=False,
        ).aaggregate(dernier=Max("created_at"))
        last = row.get("dernier")
        if last is None:
            return ""
        return _phrase_ecart((timezone.now() - last).total_seconds())
    except Exception as exc:
        degradations.record("prompt: derniere interaction", exc)
        return ""


# Mémo id → ``created_at`` des messages du fil (voir ``_stamp_history_gaps``).
# Borné : au-delà, les plus anciens ids sortent — ce sont aussi ceux qui ont
# quitté le tampon court terme.
_MESSAGE_DATES: dict[int, object] = {}
_MESSAGE_DATES_MAX = 2000


def _prune_message_dates() -> None:
    if len(_MESSAGE_DATES) <= _MESSAGE_DATES_MAX:
        return
    for pk in sorted(_MESSAGE_DATES)[: len(_MESSAGE_DATES) - _MESSAGE_DATES_MAX]:
        _MESSAGE_DATES.pop(pk, None)


async def _stamp_history_gaps(history: list[dict]) -> list[dict]:
    """Date les segments d'historique séparés par un trou.

    Un fil réhydraté après trois semaines se lit exactement comme la suite de
    la conversation d'il y a cinq minutes : le tampon ne porte aucun
    horodatage et ``ChatPrompt.chat_messages()`` ne rend que ``{role,
    content}``. Le marqueur va donc DANS le contenu — une clé supplémentaire
    n'atteindrait aucun modèle.

    Les dicts du tampon sont partagés avec ``MemoryManager.short_term`` : on
    recopie, jamais on ne mute.
    """
    if len(history) < 2:
        return history

    from django.utils import timezone

    from old.backend.memory.models import Message

    try:
        ids = [m["id"] for m in history if isinstance(m.get("id"), int)]
        if not ids:
            return history
        # ``created_at`` ne change jamais : une date lue une fois vaut pour
        # la vie du process. Sans ce mémo, c'était un ``SELECT … pk IN (500)``
        # à chaque tour, sur l'exécuteur partagé, pour relire 498 dates déjà
        # connues.
        missing = [pk for pk in ids if pk not in _MESSAGE_DATES]
        if missing:
            async for pk, created in Message.objects.filter(
                pk__in=missing
            ).values_list("id", "created_at"):
                _MESSAGE_DATES[pk] = created
            _prune_message_dates()
        dates = {pk: _MESSAGE_DATES[pk] for pk in ids if pk in _MESSAGE_DATES}

        now = timezone.now()
        ecart_min = _history_gap_seconds()
        stamped: list[dict] = []
        previous = None
        for msg in history:
            # Une entrée jamais persistée est de maintenant : c'est le tour
            # en cours, pas un fragment d'archive.
            current = dates.get(msg.get("id")) or now
            if previous is not None:
                gap = (current - previous).total_seconds()
                if gap >= ecart_min:
                    msg = {
                        **msg,
                        "content": f"[il y a {_duree_approx(gap)}] "
                                   + (msg.get("content") or ""),
                    }
            stamped.append(msg)
            previous = current
        return stamped
    except Exception as exc:
        degradations.record("prompt: horodatage historique", exc)
        return history
