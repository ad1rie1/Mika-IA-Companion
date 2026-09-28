"""Conscience models — observations and decision logs."""

from django.db import models


class Observation(models.Model):
    """A signal observed, interpreted, and stored by the Conscience.

    This is the Conscience's short-term buffer. Each module event or
    external signal becomes an Observation after interpretation.
    """

    class Category(models.TextChoices):
        COMMUNICATION = "communication"  # email, telegram, chat
        EMOTIONAL = "emotional"          # mood overflow, shift
        MEMORY = "memory"                # souvenir surfacing
        TEMPORAL = "temporal"            # time-based triggers
        EXTERNAL = "external"            # RSS, news, APIs (future)
        SYSTEM = "system"                # wake, connect, startup

    # Raw signal
    source = models.CharField(max_length=100)
    event_type = models.CharField(max_length=100)
    raw_data = models.JSONField(default=dict)
    #: Les thèmes de l'interprétation — un CHAMP, plus une convention. Ils
    #: vivaient dans ``raw_data["themes"]`` et se relisaient par ``getattr``
    #: à trois endroits : un quatrième lecteur qui ignorait la convention
    #: recevait un tuple vide EN SILENCE — le mode de panne précis que ce
    #: moteur passe son temps à chasser. Les lignes d'avant la migration ont
    #: ``[]`` ici ; ``entretien.themes_de`` retombe alors sur ``raw_data``.
    themes = models.JSONField(default=list, blank=True)

    # Interpretation (filled by interpreter pipeline)
    summary = models.TextField(blank=True)
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.SYSTEM,
    )
    pertinence = models.FloatField(default=0.5)
    emotional_reaction = models.CharField(max_length=30, blank=True, default="")
    emotional_intensity = models.FloatField(default=0.0)

    # Memory link (if this observation created a souvenir)
    souvenir = models.ForeignKey(
        "memory.Souvenir",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="observations",
    )

    class Status(models.TextChoices):
        PENDING = "pending"    # Awaiting decision
        ACTED = "acted"        # Decision made, action taken
        SKIPPED = "skipped"    # Evaluated but below threshold
        FAILED = "failed"      # Action attempted but failed

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    action_response = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["category", "-pertinence"]),
        ]

    def __str__(self):
        return f"[{self.source}/{self.event_type}] {self.summary[:60]}"


class ConscienceLog(models.Model):
    """Trace of each conscience decision cycle."""

    observations_count = models.IntegerField(default=0)
    max_pertinence = models.FloatField(default=0.0)
    global_mood = models.CharField(max_length=30, blank=True, default="")
    global_intensity = models.FloatField(default=0.0)
    idle_seconds = models.IntegerField(default=0)
    # "failed" = elle a decide de parler mais l'appel IA a echoue : rien n'a
    # ete dit, donc la ligne ne doit pas etre relue comme une prise de parole.
    decision = models.CharField(max_length=30)  # "act" | "wait" | "skip" | "failed"
    reason = models.CharField(max_length=200, blank=True, default="")
    memory_actions = models.JSONField(default=list)
    # Les modules dont les outils ont réellement accompagné cet acte.
    #
    # Sans cette trace, « elle n'a pas utilisé ses outils » et « on ne lui en a
    # donné aucun » sont indiscernables après coup — et c'était le second cas,
    # systématiquement, dès qu'une initiative ne venait pas d'une observation.
    # Vide sur un cycle qui n'a pas agi, ce qui est une information et non un
    # trou.
    trousse = models.JSONField(default=list, blank=True)
    #: La conduite retenue par le cycle — parler, poursuivre un travail, en
    #: ouvrir un, ou se taire. `decision` ne distinguait que « act / wait /
    #: skip / failed » : un cycle qui fait avancer un chantier en silence y
    #: était indiscernable d'un cycle qui n'a rien fait.
    conduite = models.CharField(max_length=20, blank=True, default="")

    # ── Ce qu'il faut pour reconstituer une décision après coup ──────
    #
    # Rien de tout ceci n'était persisté : le score n'existait qu'interpolé
    # dans `reason`, et l'écran fait pour répondre à « pourquoi elle n'a rien
    # dit depuis trois jours » ne pouvait pas y répondre.
    #
    # `score` est NULLABLE et non 0.0 : écrire zéro dans les dizaines de
    # milliers de lignes déjà en base affirmerait un fait faux, ce qui est
    # exactement le mensonge que ces colonnes retirent. « Pas mesuré » et
    # « mesuré à zéro » sont deux choses différentes.
    score = models.FloatField(null=True, blank=True)
    cooldown_restant_s = models.IntegerField(null=True, blank=True)
    acts_today = models.IntegerField(null=True, blank=True)
    consecutive_ignored = models.IntegerField(null=True, blank=True)
    energie = models.FloatField(null=True, blank=True)
    sleep_phase = models.CharField(max_length=15, blank=True, default="")
    #: À qui elle a parlé. Vide sur un cycle qui n'a pas parlé.
    person_id = models.CharField(max_length=100, blank=True, default="")
    #: Ce qu'elle a dit. Sans lui, le journal dit qu'elle a parlé sans dire
    #: quoi, et il faut recouper avec la table des messages pour le savoir.
    texte = models.TextField(blank=True, default="")
    #: Bilan des appels d'outils : leurs noms ET leur issue.
    outils = models.CharField(max_length=300, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        # Requise toutes les 30 s par l'introspection (`filter(decision="act",
        # created_at__gte=…).count()` + `order_by("-created_at")[:5]`), au
        # boot (cooldown, salutations), par la rétention et par le tableau
        # de bord — sans index, chacune balayait une table qui gagne ~2 880
        # lignes par jour.
        indexes = [
            models.Index(fields=["decision", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"[{self.decision}] {self.reason[:60]} ({self.created_at:%H:%M})"


class Rumination(models.Model):
    """A persistent thought — a signal that was perceived as pertinent
    but never acted upon, that Mika keeps turning over in her head.

    Lifecycle:
      - created from an Observation that stayed pending > 30 min
        while having pertinence >= 0.5
      - decays on a wall-clock half-life (see ``decayed_at``)
      - bleeds emotional charge into global mood, throttled in time
      - status="resolved" when Mika speaks (intensity halved, may drop
        below 0.1 threshold) and "faded" when it decays out on its own
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        RESOLVED = "resolved"    # Mika spoke about it / got it off her chest
        FADED = "faded"          # Decayed naturally below threshold

    class Origine(models.TextChoices):
        """D'où vient la pensée. Un champ, pas une convention de forme.

        Les pensées d'audit se reconnaissaient à « sans observation et sans
        thème », les pensées de manque à « nostalgic avec un prénom en
        premier thème ». Deux lecteurs déduisaient l'origine de la forme :
        une pensée promue dont l'observation avait été purgée (FK SET_NULL
        à 48 h) passait pour un audit et se faisait faner par son plafond ;
        une pensée d'audit dérivée vers `nostalgic` dont le premier thème
        était un prénom déclenchait « le retour d'un absent ». Les lignes
        d'avant la migration gardent `""` et les anciennes déductions
        restent en repli pour elles seules.
        """
        OBSERVATION = "observation"  # promue d'un signal resté sans suite
        AUDIT = "audit"              # « ai-je bien dit ça ? » après une réplique
        MANQUE = "manque"            # quelqu'un dont elle n'a plus de nouvelles
        REVISION = "revision"        # une croyance qu'elle a dû abandonner
        BLOCAGE = "blocage"          # un chantier bloqué

    summary = models.TextField()
    themes = models.JSONField(default=list)
    origine = models.CharField(
        max_length=20, choices=Origine.choices, blank=True, default="",
    )
    # Quand la digestion nocturne en a tiré un souvenir réflexif. Une pensée
    # assez lourde (≥ 0,4 après digestion) restait active et REDONNAIT un
    # « Après y avoir repensé cette nuit… » chaque nuit, tant qu'elle ne
    # s'était pas fanée — trois nuits, trois souvenirs jumeaux (MEM-11).
    reflechie_le = models.DateTimeField(null=True, blank=True)
    # Emotional label (uses the 29-emotion vocabulary) that tints mood
    # while the rumination is active. Empty means no bleed.
    emotion = models.CharField(max_length=30, blank=True, default="")
    intensity = models.FloatField(default=0.5)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE,
    )
    observation = models.ForeignKey(
        "conscience.Observation",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="ruminations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Ancre de la décroissance, en temps réel et non en tours de boucle.
    #
    # L'ancienne formule était `intensity *= 0.95` À CHAQUE CYCLE DE DÉCISION
    # (30 s) : une pensée « persistante » tombait sous le seuil de fade en
    # 22 minutes. Tous ses lecteurs, eux, raisonnent en heures — la digestion
    # nocturne exige 120 minutes d'âge, le journal du soir la relit, la
    # rétention garde les fanées 90 jours. L'intersection était vide : la
    # phase de guérison du sommeil profond n'a jamais rien eu à digérer.
    #
    # `decayed_at` n'avance qu'à l'écriture (même idiome que
    # `Souvenir.decayed_at`) : le temps écoulé sous le seuil d'écriture
    # s'accumule au lieu d'être perdu, ce qui rend la décroissance
    # indépendante de la cadence de la boucle qui l'applique.
    decayed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-intensity", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-intensity"]),
        ]

    def __str__(self):
        return f"[{self.status}:{self.intensity:.2f}] {self.summary[:60]}"

    @property
    def decay_anchor(self):
        """Depuis quand le temps n'a pas encore été facturé à cette pensée."""
        return self.decayed_at or self.created_at


class Travail(models.Model):
    """Un chantier qu'elle s'est ouvert, et qui vieillit tout seul.

    C'est la pièce qui manquait pour que « aller au bout » veuille dire quelque
    chose : jusqu'ici aucun modèle ne portait un travail — ni progression, ni
    résultat, ni raison de blocage — si bien que chaque cycle de décision
    repartait de la base et qu'aucune intention ne survivait au tour suivant.

    Il est délibérément **plus léger qu'un `Project`** et n'en est pas une
    variante allégée : un projet porte un mandat professionnel, avec
    `emotion_policy=OFF` par défaut et une détection par mots-clés qui le fait
    remonter dans une conversation ordinaire sous la bannière « PROJET EN
    COURS ». Y loger « j'ai envie de lire les news » obligerait à réinjecter la
    personnalité dans un prompt qui l'a volontairement retirée.

    **L'envie décroît en temps d'horloge, sur une ancre qui n'avance qu'à
    l'écriture** — même idiome que `Rumination.decayed_at`, et pour la même
    raison : une décroissance par tour de boucle lie la durée de vie d'une
    intention à la cadence du moteur, alors que tous ses lecteurs raisonnent en
    heures. Le temps passé sous le seuil d'écriture s'accumule au lieu d'être
    perdu.
    """

    class Statut(models.TextChoices):
        EN_COURS = "en_cours"
        TRANSFERE = "transfere"
        ABOUTIE = "aboutie"
        BLOQUEE = "bloquee"
        ABANDONNEE = "abandonnee"     # l'envie est tombée sous le plancher

    class Origine(models.TextChoices):
        OBSERVATION = "observation"   # le dehors a produit quelque chose
        PENSEE = "pensee"             # une rumination qui insiste
        PULSION = "pulsion"           # une envie endogène, sans objet extérieur

    titre = models.CharField(max_length=200)
    projet = models.ForeignKey("projects.Project", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="intentions")
    origine = models.CharField(max_length=20, choices=Origine.choices)
    #: Ce qui permet de retrouver la ligne d'origine — pk d'Observation, pk de
    #: Rumination, ou nom de pulsion. Stocké en texte parce que les trois
    #: natures ne partagent aucune table ; sert surtout à la déduplication.
    reference = models.CharField(max_length=100, blank=True, default="")
    themes = models.JSONField(default=list, blank=True)
    #: Les modules dont les outils accompagnent CHAQUE pas de ce chantier,
    #: figés à l'ouverture (depuis ``Graine.modules``). Sans eux, la trousse
    #: d'un pas se dérivait de la tension de pulsion du moment — que le
    #: premier pas réussi fait retomber (``on_act`` assouvit la curiosité de
    #: 0.5) : le chantier perdait ses mains en cours de route et finissait
    #: « bloquée » au lieu d'« aboutie ».
    modules = models.JSONField(default=list, blank=True)

    #: Envie **telle qu'écrite**. La valeur courante se calcule en la faturant
    #: du temps écoulé depuis l'ancre : ne jamais la lire seule.
    envie = models.FloatField(default=0.5)
    #: L'ancre. Les deux moitiés du même geste — valeur et ancre — ne doivent
    #: jamais s'écrire séparément : la valeur sans l'ancre re-facture le même
    #: temps au tour suivant, l'ancre sans la valeur efface la décroissance.
    #: C'est exactement ce qui est arrivé à `Connaissance`, ancrée sur un
    #: `auto_now` que Django ne rafraîchit pas sous `update_fields`.
    ancre_envie = models.DateTimeField(null=True, blank=True)

    statut = models.CharField(
        max_length=15, choices=Statut.choices, default=Statut.EN_COURS,
    )
    raison_blocage = models.TextField(blank=True, default="")
    resultat = models.TextField(blank=True, default="")

    pas_effectues = models.IntegerField(default=0)
    pas_max = models.IntegerField(default=5)
    dernier_pas_le = models.DateTimeField(null=True, blank=True)
    #: Bloqué en attente : un pas de plus reposerait la même question.
    #: Posé par le verdict ATTENDRE (`_appliquer_verdict`), relâché par la
    #: lecture des travaux quand `reprendre_le` est passé.
    en_attente_de_reponse = models.BooleanField(default=False)
    #: Quand une attente cesse d'en être une. TOUJOURS posé avec le booléen :
    #: un drapeau sans échéance est un cul-de-sac — le verdict ATTENDRE le
    #: posait et rien ne le relevait jamais, si bien qu'« attendre » voulait
    #: dire « se faner jusqu'à l'abandon ». Le lecteur de verdict garantit un
    #: délai (défaut 300 s, plafond 24 h), donc l'échéance existe toujours.
    reprendre_le = models.DateTimeField(null=True, blank=True)
    #: QUI elle attend, tel que le verdict le nomme (prénom ou person_id).
    #: Vide = attente purement temporelle. Un message de cette personne —
    #: résolu par la couche identité au réveil, jamais par égalité de nom au
    #: moment de l'écriture — relève l'attente avant l'échéance.
    attend_qui = models.CharField(max_length=100, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-envie", "-created_at"]
        indexes = [
            models.Index(fields=["statut", "-envie"]),
            models.Index(fields=["statut", "origine", "reference"]),
        ]

    def __str__(self):
        return f"[{self.statut}:{self.envie:.2f}] {self.titre[:60]}"

    @property
    def ancre(self):
        """Depuis quand le temps n'a pas encore été facturé à cette envie."""
        return self.ancre_envie or self.created_at


class EstimeDeSoi(models.Model):
    """La valeur propre — une ligne, lente, persistée.

    Ni un trait (le tempérament ne bouge pas) ni un état (l'humeur vit en
    minutes) : une variable qui encaisse les événements par petits coups et
    rappelle vers le neutre en trois jours. Persistée parce que c'est
    précisément ce qui doit survivre à un redémarrage — perdre trois jours
    de confiance avec un reboot serait le contraire de sa définition. Toute
    la physique vit dans ``conscience/estime.py`` ; le modèle ne porte que
    le couple (valeur, ancre) — les deux moitiés d'un même geste, comme
    l'envie d'un ``Travail``.
    """

    valeur = models.FloatField(default=0.5)
    #: L'ancre de la décroissance vers le neutre — n'avance qu'à l'écriture.
    ancre = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"estime {self.valeur:.2f}"


class ScheduledAction(models.Model):
    """A deferred action scheduled by the conscience or Claude.

    Created via the schedule_action tool. Picked up by the conscience
    decision loop when scheduled_at <= now, contributing to the score
    as Factor 6. Executed during _act() alongside pending observations.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        EXECUTED = "executed"
        UNCERTAIN = "uncertain"
        CANCELLED = "cancelled"
        #: Tentée assez de fois pour qu'on cesse d'y croire. Le filtre de
        #: l'écran proposait déjà « échouée » — une valeur qui ne correspondait
        #: à aucun statut de l'énumération, donc un filtre qui ne rendait
        #: jamais rien.
        FAILED = "failed"

    scheduled_at = models.DateTimeField()
    prompt = models.TextField()
    priority = models.FloatField(default=0.5)
    source = models.CharField(max_length=50)
    context_data = models.JSONField(default=dict)
    #: Les modules dont l'acte aura besoin pour honorer ce rendez-vous —
    #: la « demande explicite » que ``trousse.souhaits`` classe juste après
    #: le socle. Sans ce champ, « vérifie tes emails demain matin » partait
    #: sans l'outil email (sauf coïncidence de pulsion), le prompt lui
    #: interdisait de raconter, et l'action était quand même marquée
    #: exécutée : une intention différée pouvait être « honorée » sans avoir
    #: jamais été possible.
    modules = models.JSONField(default=list, blank=True)
    #: Ce que l'acte a produit. « Exécutée » sans résultat ne prouve rien : le
    #: statut ne disait que « l'appel IA n'a pas planté », pas que le
    #: rendez-vous avait été honoré. `ProjectTask` porte ces deux champs depuis
    #: toujours ; l'asymétrie n'avait aucune raison d'être.
    resultat = models.TextField(blank=True, default="")
    raison_echec = models.TextField(blank=True, default="")
    tentatives = models.IntegerField(default=0)
    #: Pas avant cette date : la dernière tentative a échoué, et
    #: `_poll_scheduled_actions` ne la remonte plus comme due d'ici là. C'est
    #: ce qui donne un sens au compteur ci-dessus — sans délai, trois échecs
    #: à 30 s d'intervalle épuisaient le plafond en une minute et demie pour
    #: une panne passagère, et un rendez-vous prioritaire levait le cooldown
    #: et le veto de sommeil à chaque cycle entre-temps. `scheduled_at`, lui,
    #: reste l'heure qu'elle s'était donnée : on ne réécrit pas l'intention.
    reessayer_le = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheduled_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self):
        return f"[{self.status}] {self.prompt[:60]} @ {self.scheduled_at:%H:%M}"
