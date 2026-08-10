"""Réglages du tour de conversation — le pipeline et la voix.

``pipeline`` n'est pas une application Django : ni modèle, ni migration, et
le déclarer app pour un seul fichier de schéma serait le promouvoir pour la
mauvaise raison. ``configs.apps`` importe donc ce module explicitement
(``_SCHEMAS_HORS_APPS``), et ``CONFIG_SCHEMA`` est lu au niveau module.

Chaque constante rapatriée ici **reste déclarée dans son module d'origine**
et y sert de repli : le ``default`` ci-dessous lui est identique au bit près.
Le repli ne sert que lorsque le registre est hors d'atteinte — import avant
``migrate``, base verrouillée, collecte des tests — et n'est donc pas un
second défaut déclaré (l'erreur que le pont ``env_fallback`` a coûté cher à
nettoyer).
"""
from __future__ import annotations

from configs.types import ConfigGroup, ConfigItem, ConfigSection

CONFIG_SCHEMA = [

    # ══ Tour · Traitement ═══════════════════════════════════════════
    ConfigSection(
        key="pipeline_tour", label="Traitement du tour", icon="⟳", order=26,
        family="conversation",
        summary="La file qui sérialise les tours, la voix intérieure, la passe de préparation.",
        description="Ce qui borne un tour de conversation : la file qui les "
                    "sérialise, la voix intérieure, la passe de préparation.",
    ),
    ConfigGroup(
        section="pipeline_tour", key="File des tours", order=10, advanced=True,
        description="Les tours ne sont pas traités dans la socket qui les "
                    "reçoit : ils passent par une file, sinon la connexion "
                    "devient sourde pendant toute la réponse et les "
                    "surveillances de liveness reconnectent en plein tour. "
                    "Ce qu'on règle ici, c'est la profondeur du dossier "
                    "d'attente et ce qu'un redémarrage a le droit de rejouer.",
    ),
    ConfigGroup(
        section="pipeline_tour", key="Voix intérieure", order=20,
        description="Quand elle agit d'elle-même, elle murmure ce qu'elle "
                    "s'apprête à faire. Ce murmure est fabriqué à chaque "
                    "fois, à partir de l'action et de ce qui vient d'en "
                    "revenir — et il se tait plutôt que d'afficher une erreur.",
    ),
    ConfigGroup(
        section="pipeline_tour", key="Préparation", order=30,
        description="La partie *exécution* de la pré-passe de rappel dirigé : "
                    "le temps accordé à ses recherches, la longueur de la note "
                    "de focus qu'elle glisse en dernière couche du prompt, et "
                    "le lexique de politesses qui la court-circuite. Le modèle "
                    "qui produit le plan, lui, se choisit dans IA · Rôles.",
    ),

    # ── File des tours ──────────────────────────────────────────────
    ConfigItem(
        key="pipeline.turns.max_pending", type="int", section="pipeline_tour",
        group="File des tours",
        label="Backlog maximum",
        default=100, min=1, max=10000, restart_required=True,
        description="Nombre de tours en attente au-delà duquel un nouveau "
                    "message est refusé à voix haute (accusé « overloaded »).",
        hint="Redémarrage obligatoire : la valeur est figée dans le "
             "asyncio.Queue à sa construction, la changer à chaud ne "
             "toucherait pas la file déjà en service.",
    ),
    ConfigItem(
        key="pipeline.turns.max_resumed", type="int", section="pipeline_tour",
        group="File des tours",
        label="Tours rejoués au démarrage",
        default=10, min=0, max=200, hot_reload=True,
        description="Plafond de questions interrompues (awaiting_reply) "
                    "remises en file après un redémarrage.",
        hint="Un redémarrage au milieu d'une minute chargée doit reprendre "
             "une conversation, pas ouvrir sur une rafale de réponses à des "
             "questions déjà oubliées.",
    ),

    # ── Voix intérieure ─────────────────────────────────────────────
    ConfigItem(
        key="pipeline.inner_voice.timeout_seconds", type="int",
        section="pipeline_tour", group="Voix intérieure",
        label="Échéance de la pensée (s)",
        default=12, min=1, max=120, hot_reload=True,
        description="Budget de l'appel au rôle INNER_VOICE qui produit le "
                    "murmure accompagnant une initiative.",
        hint="Dépassée, la pensée est simplement tue : le silence est une "
             "issue valable, jamais une erreur affichée.",
    ),
    ConfigItem(
        key="pipeline.inner_voice.max_thought_chars", type="int",
        section="pipeline_tour", group="Voix intérieure",
        label="Longueur maximale d'une pensée",
        default=160, min=20, max=1000, hot_reload=True,
        description="Troncature dure du murmure.",
        hint="Volontairement serré : une pensée longue cesse de sonner "
             "comme une pensée.",
    ),

    # ── Préparation ─────────────────────────────────────────────────
    # Les clés portent le préfixe ``ai.preparation.`` des réglages déjà
    # déclarés (deadline_ms, min_chars, max_rappels) : c'est le même
    # réglage vu par le même administrateur. Seule la *section* diffère,
    # « IA · Contexte » parlant du budget de fenêtre, pas de la passe.
    ConfigItem(
        key="ai.preparation.exec_budget_ms", type="int",
        section="pipeline_tour", group="Préparation",
        label="Budget d'exécution du plan (ms)",
        default=700, min=50, max=10000, hot_reload=True,
        description="Temps accordé aux intents « echanges_passes » du plan "
                    "avant abandon.",
        hint="À côté de ai.preparation.deadline_ms, qui borne l'appel qui "
             "*produit* le plan ; celui-ci borne son exécution. Dépassé, "
             "les résultats partiels sont conservés.",
    ),
    ConfigItem(
        key="ai.preparation.note_max_chars", type="int",
        section="pipeline_tour", group="Préparation",
        label="Longueur maximale de la note de focus",
        default=200, min=20, max=2000, hot_reload=True,
        description="Plafond de la pensée pré-verbale injectée en dernière "
                    "couche du prompt.",
        hint="Annoncé au petit modèle dans son prompt système *et* appliqué "
             "au parse : les deux lisent cette valeur.",
    ),
    ConfigItem(
        key="ai.preparation.small_talk_terms", type="list",
        section="pipeline_tour", group="Préparation",
        label="Lexique small-talk",
        default=[
            "salut", "coucou", "bonjour", "bonsoir", "hello", "yo", "hey",
            "ok", "oui", "non", "merci", "mdr", "lol", "ptdr", "haha", "hihi",
            "bonne nuit", "a plus", "à plus", "bye", "ciao",
            "ca va", "ça va", "et toi", "cool", "super", "top",
            "d'accord", "daccord",
        ],
        hot_reload=True,
        description="Messages qui ne déclenchent jamais de passe de "
                    "préparation (aucun appel LLM).",
        hint="Comparés en minuscules, ponctuation et emoji retirés. Le "
             "message doit valoir *exactement* un de ces termes.",
    ),

    # ══ Tour · Pièces jointes ═══════════════════════════════════════
    ConfigSection(
        key="pipeline_medias", label="Pièces jointes", icon="⊞",
        order=27,
        family="conversation",
        summary="Ce qu'un message peut porter, et ce qu'on en fait avant que le modèle le lise.",
        description="Ce qu'un message peut porter, et ce que les "
                    "préprocesseurs en font avant que le modèle le lise.",
    ),
    ConfigGroup(
        section="pipeline_medias", key="Pièces jointes", order=10,
        description="Ce qu'un message a le droit de porter. Un dépassement "
                    "n'est jamais silencieux : la pièce écartée est nommée "
                    "dans l'accusé de réception, avec sa raison, et le client "
                    "l'affiche sous la bulle — les deux côtés doivent voir le "
                    "même message.",
    ),
    ConfigGroup(
        section="pipeline_medias", key="Types acceptés", order=20, advanced=True,
        description="Ces listes ne filtrent pas, elles *aiguillent* : elles "
                    "décident quel préprocesseur prend la pièce — légende "
                    "d'image, transcription, extraction de texte. Un type "
                    "absent des trois n'est pas refusé, il retombe sur "
                    "l'extraction générique.",
    ),
    ConfigGroup(
        section="pipeline_medias", key="Prétraitement", order=30,
        description="Une image devient une légende, un vocal une "
                    "transcription, un PDF du texte — le pipeline en aval ne "
                    "voit que du texte. Tout cela se passe dans le routeur, "
                    "donc AVANT le budget d'appel IA et en occupant le worker "
                    "de la file : ces échéances s'ajoutent à l'attente de la "
                    "personne. Ce qui n'aboutit pas devient un placeholder, "
                    "jamais une erreur affichée comme du contenu.",
    ),

    ConfigItem(
        key="pipeline.media.max_attachments", type="int",
        section="pipeline_medias", group="Pièces jointes",
        label="Pièces jointes par message",
        default=5, min=1, max=50, hot_reload=True,
        description="Au-delà, le surplus est écarté et nommé dans l'accusé "
                    "(raison « too_many »).",
        hint="Chaque pièce coûte un préprocesseur, donc un appel réseau "
             "dans le budget du tour.",
    ),
    ConfigItem(
        key="pipeline.media.max_file_size_mb", type="int",
        section="pipeline_medias", group="Pièces jointes",
        label="Taille maximale d'un fichier (Mo)",
        default=5, min=1, max=100, hot_reload=True,
        description="Mesurée sur les octets décodés. Un fichier plus gros "
                    "est écarté et nommé dans l'accusé (« too_large »).",
        hint="Le canal Telegram annonce cette limite dans son refus — "
             "vérifie que le texte affiché la suit.",
    ),
    ConfigItem(
        key="pipeline.media.max_filename_chars", type="int",
        section="pipeline_medias", group="Pièces jointes",
        label="Longueur maximale d'un nom de fichier",
        default=80, min=8, max=255, hot_reload=True,
        description="Le nom vient de l'émetteur et finit dans le prompt "
                    "système du propriétaire : il est ramené à une ligne "
                    "unique et bornée avant toute persistance.",
        hint="Ne pas dépasser 255 : c'est le max_length de la colonne "
             "(SQLite ne l'applique pas, donc rien d'autre ne le défend).",
    ),
    ConfigItem(
        key="pipeline.media.allowed_image_types", type="list",
        section="pipeline_medias", group="Types acceptés",
        label="Types MIME image",
        default=["image/jpeg", "image/png", "image/gif", "image/webp"],
        hot_reload=True,
        description="Classe la pièce jointe en « image » : légendée par le "
                    "préprocesseur vision.",
        hint="Un type absent des trois listes retombe en « unknown » — "
             "l'extraction est tentée, elle n'est pas refusée.",
    ),
    ConfigItem(
        key="pipeline.media.allowed_audio_types", type="list",
        section="pipeline_medias", group="Types acceptés",
        label="Types MIME audio",
        default=[
            "audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg",
            "audio/webm", "audio/mp4", "audio/x-wav",
        ],
        hot_reload=True,
        description="Classe la pièce jointe en « audio » : transcrite par "
                    "le préprocesseur audio (Whisper).",
    ),
    ConfigItem(
        key="pipeline.media.allowed_text_types", type="list",
        section="pipeline_medias", group="Types acceptés",
        label="Types MIME texte",
        default=[
            "text/plain", "text/csv", "text/markdown", "text/html",
            "application/json", "application/xml",
        ],
        hot_reload=True,
        description="Classe la pièce jointe en « texte ». Tout "
                    "``text/*`` est de toute façon accepté en plus de "
                    "cette liste.",
    ),

    # ── Prétraitement ───────────────────────────────────────────────
    ConfigItem(
        key="pipeline.preprocess.timeout_seconds", type="int",
        section="pipeline_medias", group="Prétraitement",
        label="Échéance globale du lot (s)",
        default=60, min=5, max=600, hot_reload=True,
        description="Borne l'étape entière, toutes pièces jointes "
                    "confondues — elles sont traitées en parallèle.",
        hint="S'exécute dans le routeur, donc AVANT le budget d'appel IA du "
             "processeur, et occupe pendant tout ce temps l'unique worker de "
             "la file des tours. Ce qui n'a pas abouti retombe sur le "
             "placeholder d'erreur.",
    ),
    ConfigItem(
        key="pipeline.vision.timeout_seconds", type="int",
        section="pipeline_medias", group="Prétraitement",
        label="Échéance d'une légende image (s)",
        default=30, min=1, max=300, hot_reload=True,
        description="Par image. Même borne réutilisée par l'outil "
                    "files_analyze_image.",
    ),
    ConfigItem(
        key="pipeline.vision.max_caption_chars", type="int",
        section="pipeline_medias", group="Prétraitement",
        label="Longueur maximale d'une légende",
        default=600, min=50, max=5000, hot_reload=True,
        description="Plafond dur pour qu'un modèle bavard ne fasse pas "
                    "exploser le budget du prompt.",
    ),
    ConfigItem(
        key="pipeline.audio.transcribe_timeout_seconds", type="int",
        section="pipeline_medias", group="Prétraitement",
        label="Échéance d'une transcription (s)",
        default=45, min=1, max=600, hot_reload=True,
        description="Par clip audio. Même borne réutilisée par l'outil "
                    "files_transcribe.",
        hint="Couvre l'envoi du fichier et l'inférence.",
    ),
    ConfigItem(
        key="pipeline.audio.max_transcript_chars", type="int",
        section="pipeline_medias", group="Prétraitement",
        label="Longueur maximale d'une transcription",
        default=2000, min=100, max=50000, hot_reload=True,
        description="Un message vocal plus long est tronqué, jamais rejeté.",
    ),
    ConfigItem(
        key="pipeline.files.extract_timeout_seconds", type="int",
        section="pipeline_medias", group="Prétraitement",
        label="Échéance d'une extraction fichier (s)",
        default=20, min=1, max=300, hot_reload=True,
        description="Extraction texte d'un document (PDF, DOCX, HTML, "
                    "texte brut).",
        hint="L'échéance libère le *tour*, pas le thread : "
             "``asyncio.to_thread`` n'est pas annulable et un PDF "
             "pathologique continue d'occuper son worker.",
    ),
    ConfigItem(
        key="pipeline.files.max_extract_chars", type="int",
        section="pipeline_medias", group="Prétraitement",
        label="Texte extrait maximum",
        default=8000, min=200, max=200000, hot_reload=True,
        description="Au-delà, le contenu est tronqué avec un marqueur "
                    "visible dans le prompt.",
    ),
    ConfigItem(
        key="pipeline.files.max_pdf_pages", type="int",
        section="pipeline_medias", group="Prétraitement",
        label="Pages PDF lues",
        default=20, min=1, max=500, hot_reload=True,
        description="Chaque page est une passe d'extraction ; les pages "
                    "au-delà sont annoncées comme non lues.",
    ),

    # ══ Tour · Contexte ═════════════════════════════════════════════
    ConfigSection(
        key="pipeline_contexte", label="Contexte du prompt", icon="◫", order=28,
        family="conversation",
        summary="Les plafonds des blocs de prompt, et les seuils qui décident si un bloc paraît.",
        description="Les plafonds des blocs de prompt sans borne naturelle, "
                    "et les seuils qui décident si un bloc paraît.",
    ),
    ConfigGroup(
        section="pipeline_contexte", key="Plafonds des blocs", order=10,
        advanced=True,
        description="Des garde-fous, pas des réglages : rien en aval ne mesure "
                    "ni ne tronque ces blocs, donc celui qui grossit — récit "
                    "de soi, contexte des modules, revendications d'identité — "
                    "alourdit chaque tour sans que rien ne le dise. Les valeurs "
                    "sont larges exprès : empêcher la dérive, pas rogner le cas "
                    "nominal.",
    ),
    ConfigGroup(
        section="pipeline_contexte", key="Rythme du fil", order=20,
        description="Ce qui fait qu'une conversation a une histoire plutôt "
                    "qu'un présent perpétuel : au-delà de quel trou un segment "
                    "du fil est daté pour elle, et au-delà de quel silence elle "
                    "se permet de dire à la personne qu'on ne s'était pas parlé "
                    "depuis un moment. Deux cadrans distincts, même si leur "
                    "valeur par défaut coïncide.",
    ),
    ConfigGroup(
        section="pipeline_contexte", key="Rêve", order=30,
        description="À quelles conditions le rêve de la nuit lui revient. Il "
                    "n'est proposé qu'une fois, le matin, et présenté comme "
                    "mentionnable si ça tombe — pas comme quelque chose à "
                    "raconter. Un rêve trop flou reste interne : il a quand "
                    "même nourri le récit de soi.",
    ),

    # ── Plafonds des blocs ──────────────────────────────────────────
    # Rien en aval ne mesure ni ne tronque (pas de tokenizer dans le
    # processus) : un bloc qui grossit sans borne gonfle chaque tour en
    # silence. Les valeurs sont larges — empêcher la dérive, pas rogner le
    # cas nominal.
    ConfigItem(
        key="pipeline.context.self_concept_max_chars", type="int",
        section="pipeline_contexte", group="Plafonds des blocs",
        label="Bloc « qui tu es devenue »",
        default=1600, min=100, max=20000, hot_reload=True,
        description="Plafond du récit de soi injecté dans le préfixe stable.",
        hint="Dans la zone mise en cache par les providers : ce qui grossit "
             "ici est payé à chaque tour, même inchangé.",
    ),
    ConfigItem(
        key="pipeline.context.module_context_max_chars", type="int",
        section="pipeline_contexte", group="Plafonds des blocs",
        label="Bloc « contexte modules »",
        default=1800, min=100, max=20000, hot_reload=True,
        description="Somme de tous les modules réunis.",
        hint="Chaque module se borne déjà lui-même ; leur somme — Forge "
             "inclus, qui concatène tous ses mini-modules — n'avait aucune "
             "limite globale.",
    ),
    ConfigItem(
        key="pipeline.context.project_text_max_chars", type="int",
        section="pipeline_contexte", group="Plafonds des blocs",
        label="Longueur d'une ligne de projet",
        default=300, min=40, max=5000, hot_reload=True,
        description="Ton, consignes et hors-portée. Le cadre du projet vaut "
                    "le double.",
    ),
    ConfigItem(
        key="pipeline.context.project_list_items_max", type="int",
        section="pipeline_contexte", group="Plafonds des blocs",
        label="Consignes de projet listées",
        default=8, min=1, max=100, hot_reload=True,
        description="S'applique séparément aux consignes et aux hors-portée.",
    ),
    ConfigItem(
        key="pipeline.context.identity_claims_max", type="int",
        section="pipeline_contexte", group="Plafonds des blocs",
        label="Revendications d'identité affichées",
        default=5, min=1, max=50, hot_reload=True,
        description="Le surplus est compté sur une ligne, pas détaillé.",
        hint="Chaque ligne coûte à chaque tour, et au-delà de quelques "
             "revendications simultanées le modèle n'arbitre plus rien.",
    ),
    ConfigItem(
        key="pipeline.context.journal_max_chars", type="int",
        section="pipeline_contexte", group="Plafonds des blocs",
        label="Bloc « ton fil d'hier »",
        default=450, min=50, max=5000, hot_reload=True,
        description="Le récapitulatif de la veille est un fil, pas une "
                    "transcription.",
    ),

    # ── Rythme du fil ───────────────────────────────────────────────
    # Deux cadrans distincts malgré la valeur identique : l'un date des
    # segments *dans* l'historique envoyé au modèle, l'autre décide si la
    # personne s'entend dire qu'on ne s'est pas parlé depuis un moment.
    ConfigItem(
        key="pipeline.context.history_gap_hours", type="int",
        section="pipeline_contexte", group="Rythme du fil",
        label="Trou datant un segment d'historique (h)",
        default=6, min=1, max=720, hot_reload=True,
        description="Au-delà de cet écart entre deux messages du tampon, le "
                    "second est préfixé « [il y a …] ».",
        hint="Cadran distinct de « écart mentionné à l'interlocuteur », "
             "malgré la valeur par défaut identique : celui-ci marque le "
             "fil rejoué au modèle, l'autre écrit une phrase à la personne.",
    ),
    ConfigItem(
        key="pipeline.context.gap_mention_floor_hours", type="int",
        section="pipeline_contexte", group="Rythme du fil",
        label="Écart mentionné à l'interlocuteur (h)",
        default=6, min=1, max=720, hot_reload=True,
        description="En deçà, aucune phrase sur le temps écoulé depuis le "
                    "dernier échange.",
        hint="Cadran distinct de « trou datant un segment d'historique », "
             "malgré la valeur par défaut identique : un fil continu ne doit "
             "pas se retrouver tapissé de marqueurs, et le cas nominal ne "
             "doit pas payer une ligne de prompt à chaque tour.",
    ),

    # ── Rêve ────────────────────────────────────────────────────────
    ConfigItem(
        key="pipeline.context.dream_recall_window_hours", type="int",
        section="pipeline_contexte", group="Rêve",
        label="Fenêtre de remémoration (h)",
        default=8, min=1, max=24, hot_reload=True,
        description="Durée après la fin de la nuit pendant laquelle le rêve "
                    "de la nuit peut encore remonter dans le prompt.",
        hint="Comptée depuis memory.sleep_night_end_hour : le résidu reste "
             "matinal, un rêve ne resurgit pas à 21h.",
    ),
    ConfigItem(
        key="pipeline.context.dream_vividness_threshold", type="float",
        section="pipeline_contexte", group="Rêve",
        label="Netteté minimale d'un rêve mentionnable",
        default=0.6, min=0.0, max=1.0, hot_reload=True,
        description="En dessous, le rêve reste purement interne (il a tout "
                    "de même nourri le récit de soi).",
    ),

    # ══ Voix ════════════════════════════════════════════════════════
    ConfigSection(
        key="voice", label="Voix", icon="♪", order=66,
        family="conversation",
        summary="Quand elle parle à voix haute, et avec quelle voix. Décidé côté serveur.",
        description="Quand Mika parle à voix haute, et avec quelle voix. La "
                    "décision est prise côté serveur, pas dans le navigateur.",
    ),
    ConfigGroup(
        section="voice", key="Heures calmes", order=10,
        description="La plage où un haut-parleur en pièce partagée reste muet. "
                    "Elle ne concerne que lui : un onglet ouvert continue de "
                    "parler, et une note vocale part quelle que soit l'heure — "
                    "son destinataire l'écoutera quand il voudra.",
    ),
    ConfigGroup(
        section="voice", key="Profil « adressé »", order=20, advanced=True,
        description="Multiplicateurs appliqués par-dessus la modulation "
                    "émotionnelle, quand elle s'adresse à quelqu'un. À 1,0 "
                    "partout — le défaut — la voix est exactement celle que "
                    "l'émotion a réglée, et ce bloc ne fait rien.",
    ),
    ConfigGroup(
        section="voice", key="Profil « pensée »", order=30,
        description="Sa voix quand elle pense tout haut plutôt qu'elle ne "
                    "parle à quelqu'un : plus bas, plus lent, nettement plus "
                    "discret. C'est ce contraste qui fait entendre un murmure "
                    "surpris au lieu d'une phrase adressée.",
    ),

    ConfigItem(
        key="voice.quiet_hours_start", type="int", section="voice",
        group="Heures calmes",
        label="Début des heures calmes",
        default=22, min=0, max=23, hot_reload=True,
        description="Heure à partir de laquelle un haut-parleur en pièce "
                    "partagée reste muet.",
        hint="La fenêtre est supposée enjamber minuit (heure ≥ début OU "
             "heure < fin). Un couple qui ne l'enjambe pas — début 8, fin "
             "22 — inverse le sens : ce sont alors les heures de journée "
             "qui deviennent calmes.",
    ),
    ConfigItem(
        key="voice.quiet_hours_end", type="int", section="voice",
        group="Heures calmes",
        label="Fin des heures calmes",
        default=8, min=0, max=23, hot_reload=True,
        description="Heure à partir de laquelle le haut-parleur reparle.",
        hint="La fenêtre est supposée enjamber minuit (heure ≥ début OU "
             "heure < fin). Une fin postérieure au début — début 8, fin "
             "22 — inverse le sens : ce sont alors les heures de journée "
             "qui deviennent calmes.",
    ),

    # ── Profils vocaux ──────────────────────────────────────────────
    # Multiplicateurs appliqués PAR-DESSUS la modulation émotionnelle,
    # côté frontend. 1.0 = la voix telle que l'émotion l'a réglée.
    ConfigItem(
        key="voice.profile.speaking.pitch", type="float", section="voice",
        group="Profil « adressé »",
        label="Hauteur", default=1.0, min=0.1, max=3.0, hot_reload=True,
        description="Multiplicateur appliqué par-dessus la modulation "
                    "émotionnelle, quand Mika s'adresse à quelqu'un.",
    ),
    ConfigItem(
        key="voice.profile.speaking.rate", type="float", section="voice",
        group="Profil « adressé »",
        label="Débit", default=1.0, min=0.1, max=3.0, hot_reload=True,
    ),
    ConfigItem(
        key="voice.profile.speaking.gain", type="float", section="voice",
        group="Profil « adressé »",
        label="Volume", default=1.0, min=0.0, max=2.0, hot_reload=True,
    ),
    ConfigItem(
        key="voice.profile.inner.pitch", type="float", section="voice",
        group="Profil « pensée »",
        label="Hauteur", default=0.94, min=0.1, max=3.0, hot_reload=True,
        description="Le monologue intérieur a sa propre identité vocale : "
                    "un peu plus bas, plus lent, nettement plus discret — "
                    "ça se lit comme une pensée surprise, pas comme une "
                    "phrase adressée.",
    ),
    ConfigItem(
        key="voice.profile.inner.rate", type="float", section="voice",
        group="Profil « pensée »",
        label="Débit", default=0.9, min=0.1, max=3.0, hot_reload=True,
    ),
    ConfigItem(
        key="voice.profile.inner.gain", type="float", section="voice",
        group="Profil « pensée »",
        label="Volume", default=0.45, min=0.0, max=2.0, hot_reload=True,
    ),
]
