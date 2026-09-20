"""Fiches de lecture : champs choisis explicitement, liens vers leurs sources."""
from __future__ import annotations

import json
from datetime import date, datetime

from django.apps import apps
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from GestionSysteme import panels as P, tables
from GestionSysteme.formatting import clip, dt, dt_full, display_text, dream_label
from GestionSysteme.nav import item_for
from GestionSysteme.retour import retour_sur
from GestionSysteme.shell import page_context

# type : modèle, destination, onglet, titre, textes, métadonnées, données structurées.
RECORDS = {
    "journal": ("memory.DailyJournal", "memory", "journaux", "Journal",
        (("narrative", "Récit de la journée"),),
        (("date", "Journée couverte"), ("dominant_emotion", "Ressenti"),
         ("word_count", "Nombre de mots"), ("created_at", "Écrit le")),
        (("persons_interacted", "Personnes rencontrées"), ("unresolved_at_sleep", "Pensées encore ouvertes au coucher"))),
    "reve": ("memory.Dream", "memory", "journaux", "Rêve",
        (("content", "Récit du rêve"),),
        (("night_of", "Nuit du"), ("dream_type", "Nature"), ("vividness", "Vivacité"),
         ("emotion", "Ressenti"), ("recalled_at", "Rappelé le"), ("created_at", "Créé le")), ()),
    "souvenir": ("memory.Souvenir", "memory", "souvenirs", "Souvenir",
        (("content", "Épisode vécu"),),
        (("emotion", "Ressenti"), ("importance", "Importance"), ("sensibilite", "Sensibilité"),
         ("occurred_at", "Vécu le"), ("created_at", "Extrait le"), ("decayed_at", "Dernière décroissance")), ()),
    "connaissance": ("memory.Connaissance", "memory", "connaissances", "Connaissance",
        (("content", "Fait retenu"),),
        (("confidence", "Confiance"), ("is_valid", "Valide"), ("sensibilite", "Sensibilité"),
         ("created_at", "Créée le"), ("updated_at", "Modifiée le"), ("decayed_at", "Dernière décroissance")), ()),
    "message": ("memory.Message", "memory", "messages", "Message",
        (("content", "Contenu intégral"),),
        (("role", "Rôle"), ("source", "Canal"), ("person_id", "Personne"), ("created_at", "Envoyé le"),
         ("emotion", "Ressenti"), ("emotion_intensity", "Intensité"), ("is_internal", "Message interne"),
         ("awaiting_reply", "En attente de réponse")),
        (("attachments_meta", "Pièces jointes"), ("transport_meta", "Contexte de réception"))),
    "observation": ("conscience.Observation", "conscience", "observations", "Observation",
        (("summary", "Interprétation"), ("action_response", "Réponse produite")),
        (("status", "État"), ("source", "Source"), ("event_type", "Événement"), ("category", "Catégorie"),
         ("pertinence", "Pertinence"), ("emotional_reaction", "Réaction"), ("emotional_intensity", "Intensité"),
         ("created_at", "Reçue le")), (("themes", "Thèmes"), ("raw_data", "Signal d'origine"))),
    "decision": ("conscience.ConscienceLog", "conscience", "decisions", "Décision",
        (("reason", "Motif"), ("texte", "Paroles produites"), ("outils", "Résultat des outils")),
        (("created_at", "Décidée le"), ("decision", "Décision"), ("conduite", "Conduite"), ("score", "Score"),
         ("person_id", "Destinataire"), ("observations_count", "Observations"), ("max_pertinence", "Pertinence maximale"),
         ("global_mood", "Humeur"), ("global_intensity", "Intensité"), ("energie", "Énergie"),
         ("sleep_phase", "Sommeil"), ("idle_seconds", "Inactivité (s)"), ("cooldown_restant_s", "Délai restant (s)"),
         ("acts_today", "Actes du jour"), ("consecutive_ignored", "Actes ignorés consécutifs")),
        (("trousse", "Modules disponibles"), ("memory_actions", "Actions sur la mémoire"))),
    "rumination": ("conscience.Rumination", "inner", "ruminations", "Rumination",
        (("summary", "Pensée"),),
        (("origine", "Origine"), ("status", "État"), ("emotion", "Émotion"), ("intensity", "Intensité"),
         ("created_at", "Créée le"), ("updated_at", "Modifiée le"), ("reflechie_le", "Réfléchie le"),
         ("decayed_at", "Dernière décroissance")), (("themes", "Thèmes"),)),
    "chantier": ("conscience.Travail", "inner", "chantiers", "Chantier",
        (("titre", "Intention"), ("raison_blocage", "Blocage"), ("resultat", "Résultat")),
        (("origine", "Origine"), ("reference", "Référence"), ("statut", "État"), ("envie", "Envie enregistrée"),
         ("pas_effectues", "Étapes effectuées"), ("pas_max", "Budget d'étapes"), ("dernier_pas_le", "Dernière étape"),
         ("en_attente_de_reponse", "Attend une réponse"), ("attend_qui", "Attend qui"), ("reprendre_le", "Reprise prévue"),
         ("created_at", "Créé le"), ("updated_at", "Modifié le")), (("themes", "Thèmes"), ("modules", "Modules"))),
    "planification": ("conscience.ScheduledAction", "conscience", "planification", "Action planifiée",
        (("prompt", "Intention"), ("resultat", "Résultat"), ("raison_echec", "Dernier échec")),
        (("status", "État"), ("source", "Source"), ("priority", "Priorité"), ("scheduled_at", "Prévue le"),
         ("executed_at", "Exécutée le"), ("tentatives", "Tentatives"), ("reessayer_le", "Nouvel essai"),
         ("created_at", "Créée le")), (("modules", "Modules"), ("context_data", "Contexte"))),
    "prompt-projet": ("projects.ProjectPromptHistory", "projects", "journal", "Trace IA du projet",
        (("user_prompt", "Demande"), ("raw_response", "Réponse brute"), ("system_prompt", "Contexte transmis")),
        (("created_at", "Date"), ("outcome", "Issue"), ("duration_ms", "Durée (ms)")),
        (("parsed_output", "Résultat interprété"),)),
    "execution": ("projects.ProjectLog", "projects", "journal", "Exécution de projet",
        (("summary", "Compte rendu"),), (("action", "Action"), ("created_at", "Exécutée le")),
        (("tools_used", "Outils utilisés"),)),
}


def _value(obj, key):
    value = getattr(obj, key)
    if isinstance(value, datetime):
        return dt_full(value)
    if isinstance(value, date):
        return dt(value)
    if value is None or value == "":
        return "Non renseigné"
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if key == "dream_type":
        return dream_label(value)
    if key in {"emotion", "dominant_emotion", "emotional_reaction", "global_mood"}:
        from GestionSysteme.formatting import emotion_fr
        return emotion_fr(value)
    return str(value)


def record_url(kind, pk):
    return reverse("gestionsysteme:record-detail", args=[kind, pk])


def detail(request, kind, pk):
    spec = RECORDS.get(kind)
    if spec is None or not 0 < pk <= 9223372036854775807:
        raise Http404("Type de fiche inconnu")
    model, family, tab, label, texts, metadata, structured = spec
    obj = get_object_or_404(apps.get_model(model), pk=pk)
    item = item_for(family)
    back = reverse(f"gestionsysteme:{item.url_name}-tab", args=[tab])
    back = retour_sur(request, back, source="GET", prefix="/gestion/")
    main = [P.Prose(display_text(getattr(obj, key) or "Aucun contenu enregistré.", limit=100_000), title=title)
            for key, title in texts]
    side = [P.Fields([P.Field(title, _value(obj, key)) for key, title in metadata], title="Repères")]
    for key, title in structured:
        value = getattr(obj, key)
        main.append(P.Disclosure(title, [P.Code(display_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), limit=200_000))]))
    if kind == "chantier":
        from conscience.conduite import TravailEnCours, envie_courante
        from django.utils import timezone
        current = envie_courante(TravailEnCours(identifiant=obj.pk, titre=obj.titre,
            envie=obj.envie, ancre_envie=obj.ancre), timezone.now())
        side.insert(0, P.Fields([P.Field("Envie actuelle", f"{current:.0%}")], title="État actuel"))
    relations = []
    for field, target, title in (("source_souvenir_id", "souvenir", "Souvenir source"),
                                 ("souvenir_id", "souvenir", "Souvenir créé"),
                                 ("source_rumination_id", "rumination", "Rumination source"),
                                 ("observation_id", "observation", "Observation source")):
        value = getattr(obj, field, None)
        if value:
            relations.append(P.Field(title, f"Ouvrir #{value}", kind="link", href=record_url(target, value)))
    conversation = getattr(obj, "conversation_id", None)
    if conversation:
        from urllib.parse import urlencode
        href = reverse("gestionsysteme:memory-tab", args=["messages"]) + "?" + urlencode({"conversation": conversation})
        relations.append(P.Field("Conversation source", f"Conversation #{conversation}", kind="link", href=href))
    if kind in {"execution", "prompt-projet"}:
        relations.append(P.Field("Projet", str(obj.project), kind="link",
                                href=reverse("gestionsysteme:project-detail", args=[obj.project_id])))
        if getattr(obj, "task", None):
            main.append(P.Prose(display_text(obj.task.description, limit=100_000), title="Tâche concernée"))
    if kind in {"souvenir", "connaissance"}:
        from urllib.parse import urlencode
        for theme in obj.themes.all():
            relations.append(P.Field("Thème", theme.name, kind="link", href=
                reverse("gestionsysteme:memory-tab", args=[tab]) + "?" + urlencode({"theme": theme.name})))
        for entity in obj.entities.all():
            href = reverse("gestionsysteme:person-detail", args=[entity.pk]) if entity.entity_type == "person" else (
                reverse("gestionsysteme:memory-tab", args=[tab]) + "?" + urlencode({"entite": entity.pk}))
            relations.append(P.Field("Entité", entity.name, kind="link", href=href))
    if kind == "souvenir":
        page = tables.paginate(request, obj.derived_connaissances.order_by("-created_at", "-pk"), per_page=10)
        main.append(P.Table([P.Column("Connaissance dérivée"), P.Column("Valide")],
            [P.Row((P.text(c.content), P.boolean(c.is_valid)), href=record_url("connaissance", c.pk)) for c in page.rows],
            page=page, caption="Ce qui en a été retenu", empty="Aucune connaissance issue de ce souvenir."))
    if kind in {"journal", "reve"}:
        from memory.models import Souvenir
        if kind == "journal":
            # Les références peuvent avoir disparu avec la rétention de mémoire.
            ids = {int(v) for v in (obj.key_moments or [])
                   if len(str(v)) <= 19 and str(v).isdecimal() and 0 < int(v) <= 9223372036854775807}
            sources = Souvenir.objects.filter(pk__in=ids)
            missing = len(ids) - sources.count()
            if missing:
                main.append(P.Note(f"{missing} souvenir(s) source ne sont plus conservés.", tone="info"))
        else:
            sources = obj.source_souvenirs.all()
        page = tables.paginate(request, sources.order_by("-occurred_at", "-pk"), per_page=10)
        main.append(P.Table([P.Column("Souvenir source"), P.Column("Vécu le")],
            [P.Row((P.text(clip(s.content, 280)), P.text(dt(s.occurred_at))), href=record_url("souvenir", s.pk)) for s in page.rows],
            page=page, caption="Souvenirs à l'origine", empty="Aucun souvenir source conservé."))
    if relations:
        side.insert(0, P.Fields(relations, title="Liens et sources"))
    ctx = page_context(request, item=item, active_key=family, active_tab=tab, title=f"{label} #{pk}",
                       description="Contenu intégral, contexte et sources.")
    ctx.update(main_blocks=main, side_blocks=side, back_url=back, record_label=label)
    return render(request, "gestion/record.html", ctx)
