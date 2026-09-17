import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass

from configs.runtime import cfg_float, cfg_int
from emotion import dynamics, pad, persistence, physics
from emotion.dynamics import OscillatorParams
from emotion.pad import Vec3
from emotion.types import EmotionData
from emotion.state import (
    REST_TOLERANCE,
    TEMPERAMENT_PREFIX,
    EmotionHistoryEntry,
    GlobalMood,
    MessageEmotion,
    PersonMood,
    Temperament,
    load_temperament,
)
from identity.trust import is_identifiable_person, is_internal_person
from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Physics tick period (seconds) used by the decay loop.
_TICK_DT = 1.0
# ── Réglages rapatriés en configuration ──────────────────────────────
#
# Les constantes qui suivent restent déclarées ici et gardent leur valeur :
# elles sont le REPLI de la clé ``emotion.*`` correspondante (section Émotion
# du dashboard), servi quand le registre est hors d'atteinte — import avant
# ``migrate``, base verrouillée, collecte des tests. Le défaut déclaré dans
# ``emotion/config_schema.py`` vaut exactement la constante, donc une
# installation neuve se comporte à l'identique ; ce qui change, c'est
# seulement l'origine de la valeur. Voir ``configs/runtime.py``. Les
# constantes de la physique (constantes de temps, cliquets, bornes des
# ancres, plafond de rattrapage) vivent avec leurs lecteurs dans
# ``emotion/physics.py`` ; ici ne restent que celles des impulsions et des
# vues.

# Résonance de tempérament : une impulsion alignée sur le fond du personnage
# (l'ancre PAD de `default_mood`) est amplifiée — gain × (1 + k·cos), cos
# retenu seulement s'il est positif. AMPLIFICATION SEULEMENT, jamais
# d'armure : atténuer les impulsions contraires rendrait un fond heureux
# structurellement intouchable par la tristesse, alors que « résister » est
# déjà ce que `recovery_speed` et le point de repos expriment. C'est la
# propriété que `test_melancholic_resonates_with_sadness` nommait en restant
# volontairement rouge : mélancolique et défaut ne différaient que par
# `intensity_base`, le fond n'entrait dans la physique que par le point de
# repos — sous 1 % par tour à τ = 1059 s.
RESONANCE_STRENGTH = 0.45
# Modulation du gain global par l'intensité déclarée : gain_effectif =
# gain_base × (PLANCHER + PENTE × intensité), plafonné. À 0.2 d'intensité une
# émotion effleure l'humeur générale, à 1.0 elle la traverse. Un gain fixe
# rendait « tu te sens contente, comme d'habitude » lisible dans le prompt
# pendant qu'on lui écrivait « je pleure ».
# Le facteur reste RELATIF au gain du tempérament : `global_bleed` promet « à
# 0 elle compartimente entièrement », et un plafond absolu aurait fait passer
# une émotion forte par-dessus ce curseur. Un tempérament stoïque module donc
# dans sa propre échelle, sans jamais en sortir.
GLOBAL_GAIN_FLOOR = 0.4
GLOBAL_GAIN_SLOPE = 1.6
GLOBAL_GAIN_MAX_FACTOR = 2.0

# Part de l'humeur par défaut dans le point de repos commun : home =
# default_mood × ce poids + teinte circadienne. C'était un littéral nu au
# milieu de ``_home_vector``, alors que c'est exactement le curseur qui décide
# de la place du personnage dans son propre repos.
HOME_DEFAULT_MOOD_WEIGHT = 0.15

# Ancrage personnel : part du point de repos d'une personne qui vient de ce
# qu'elle a déjà provoqué, contre le repos circadien commun.
PERSON_ANCHOR_WEIGHT = 0.6

# « Bien ancrée » : une stance construite, pas déclenchée une fois.
ANCHORED_MIN_NORM = 0.4
ANCHORED_MIN_IMPULSES = 2
ANCHORED_WINDOW_S = 900.0


@dataclass(frozen=True)
class TurnEmotionView:
    """Ce qu'un tour porte comme émotion, côté sortie.

    La balise ``[EMOTION:]`` est la vérité du tour : c'est ce que le modèle a
    choisi en écrivant sa réponse. L'oscillateur, lui, dit où en est la
    relation — utile, mais ce n'est pas ce qui vient d'être dit.
    """
    emotion: str
    intensity: float
    blend: list[tuple[str, float]]
    state: dict
    declared: bool



class EmotionEngine:
    """Central emotion orchestrator, PAD-dimensional + damped oscillator.

    Three layers:
    1. Per-person mood  (person_moods)  — one oscillator per person
    2. Global mood       (global_mood)   — one oscillator for overall state
    3. Message emotion   (computed)      — blend of person + global per message

    Le moteur tient les impulsions, les vues et les accesseurs de contexte.
    L'intégration et les ancres sont dans ``emotion/physics.py`` (pur), les
    relevés et résumés dans ``emotion/persistence.py`` (ORM) ; les délégués
    d'une ligne ci-dessous gardent la surface que les tests et les autres
    sous-systèmes appellent ou patchent.

    Persistence strategy (two-tier, backwards-compatible schema):
    - EmotionSnapshot  : (label, intensity) pairs, retained for
                         EMOTION_SNAPSHOT_RETENTION_DAYS. Restored lossy
                         via label_to_pad().
    - EmotionalSummary : daily aggregates built by the consolidator, used
                         as fallback when snapshots were pruned.
    """

    _SNAPSHOT_DECAY_DAYS: int = 2
    _SUMMARY_DECAY_DAYS: int = 30
    # Idle cleanup: remove persons untouched for this long with no emotion.
    _IDLE_EVICTION_SECONDS: int = 3600

    def __init__(self):
        self.person_moods: dict[str, PersonMood] = {}
        self.global_mood = GlobalMood()
        self.temperament = Temperament()
        self._person_params = OscillatorParams()
        self._global_params = OscillatorParams()
        self._decay_task: asyncio.Task | None = None
        self._initialized = False
        self._last_snapshot_time: dict[str, float] = {}
        self._snapshot_interval: int = 30
        # Protects the snapshot-interval check. Without it, two concurrent
        # process_message() calls for the same person_id could both read
        # the old timestamp, both see "enough time has passed", and both
        # insert a snapshot. Cheap lock, always contended briefly only.
        self._snapshot_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self):
        """Load temperament from personality, restore state, start decay loop."""
        if self._initialized:
            return

        from config.personality import personality
        self.temperament = personality.temperament
        self._recompute_params()

        from configs.service import config_service
        self._snapshot_interval = config_service.get("emotion.snapshot_interval")
        self._SNAPSHOT_DECAY_DAYS = config_service.get("emotion.snapshot_retention_days")
        config_service.on_change(
            "emotion.snapshot_interval",
            lambda k, v: setattr(self, "_snapshot_interval", v),
        )
        # Le tempérament est déclaré ``hot_reload`` : les cinq curseurs se
        # règlent en regardant l'humeur qu'ils gouvernent bouger, ce qui n'a
        # aucun sens si la valeur n'est relue qu'au démarrage. Recharger le
        # tempérament ne suffit pas — ``_recompute_params`` en dérive la masse,
        # la raideur et l'amortissement de l'oscillateur, et c'est cela que la
        # boucle lit à chaque pas.
        config_service.on_change(
            TEMPERAMENT_PREFIX, lambda k, v: self._reload_temperament(k),
        )

        restored = await self._restore_state()

        self._decay_task = asyncio.create_task(self._decay_loop())
        self._initialized = True
        logger.info(
            "EmotionEngine initialized (temperament: volatility=%.1f, "
            "intensity_base=%.1f, recovery=%.1f, default_mood=%s, bleed=%.1f)"
            "%s",
            self.temperament.volatility,
            self.temperament.intensity_base,
            self.temperament.recovery_speed,
            self.temperament.default_mood.value,
            self.temperament.global_bleed,
            " [restored from snapshot]" if restored else "",
        )

    async def shutdown(self):
        """Stop the decay loop, then save emotional state.

        In that order: the decay loop evicts idle persons, and `_save_state`
        awaits once per person — saving while it runs is iterating a dict
        somebody else is writing.
        """
        if self._decay_task:
            self._decay_task.cancel()
            try:
                await self._decay_task
            except asyncio.CancelledError:
                pass

        await self._save_state()
        logger.info("EmotionEngine shut down (state saved)")

    def _reload_temperament(self, key: str) -> None:
        """Re-read the temperament after a dashboard edit and re-derive params."""
        self.temperament = load_temperament()
        self._recompute_params()
        logger.info(
            "Temperament reloaded after %s changed (volatility=%.2f, "
            "intensity_base=%.2f, recovery=%.2f, default_mood=%s, bleed=%.2f)",
            key,
            self.temperament.volatility,
            self.temperament.intensity_base,
            self.temperament.recovery_speed,
            self.temperament.default_mood.value,
            self.temperament.global_bleed,
        )

    def _recompute_params(self) -> None:
        """Derive OscillatorParams from the current temperament (``physics.derive_params``)."""
        self._person_params, self._global_params = physics.derive_params(self.temperament)

    # ------------------------------------------------------------------
    # State persistence — ``emotion/persistence.py``
    # ------------------------------------------------------------------

    async def _save_state(self) -> None:
        await persistence.save_all(self)

    async def _restore_state(self) -> bool:
        return await persistence.restore_state(self)

    async def ensure_person_loaded(self, person_id: str) -> None:
        await persistence.ensure_person_loaded(self, person_id)

    def _person_tau(self) -> float:
        return physics.tau_of(self._person_params)

    def _global_tau(self) -> float:
        """L'humeur de fond est deux fois plus paresseuse."""
        return physics.tau_of(self._global_params)

    _aged_position = staticmethod(physics.aged_position)
    _heal_anchor = staticmethod(physics.heal_anchor)

    def _note_anchor(self, mood: PersonMood, position: Vec3) -> None:
        physics.fold_anchor(mood, position, self._home_vector())

    def _anchor_from_snapshots(self, rows) -> Vec3 | None:
        return physics.anchor_from_rows(rows, self._home_vector())

    # ------------------------------------------------------------------
    # Periodic snapshots (for emotional memory)
    # ------------------------------------------------------------------

    async def save_snapshot(
        self, person_id: str, declared: EmotionData | None = None,
    ) -> None:
        """Save a snapshot if enough time has passed since the last one.

        `declared` is what the turn's [EMOTION:] tag said, when there was one;
        that is what gets persisted, since it is what she meant by the reply
        the snapshot is supposed to remember.

        The throttle is stamped on the *write*, not on the attempt: stamping
        first meant one message closed the next 30 seconds, and a failed write
        closed them for nothing. The lock now covers the write too, so
        snapshots for one person serialise — they are rare by construction.
        """
        # Une seule garde, à l'écriture : ``ensure_person_loaded`` refusait
        # déjà les non-personnes mais ``_get_person_mood`` les créait, et le
        # relevé partait quand même — des ``EmotionalSummary`` pour ``anon_*``
        # et ``conscience_mika``, rechargés en RAM trente jours au boot.
        if not is_identifiable_person(person_id):
            return
        async with self._snapshot_lock:
            now = time.time()
            last = self._last_snapshot_time.get(person_id, 0)
            if now - last < self._snapshot_interval:
                return
            if await persistence.save_person_snapshot(self, person_id, declared):
                self._last_snapshot_time[person_id] = time.time()


    # ------------------------------------------------------------------
    # Person mood management
    # ------------------------------------------------------------------

    def _get_person_mood(self, person_id: str) -> PersonMood:
        """Get or create mood state for a person. New persons start AT REST.

        À l'origine, un oscillateur neuf mettait vingt minutes à rejoindre le
        repos : chaque socket anonyme montrait un visage neutre qui virait
        « joueuse » sur la première demi-heure — une dérive d'artefact, pas
        une émotion. Le repos commun est là où un inconnu commence, ce que
        ``ensure_person_loaded`` posait déjà pour un relevé illisible.
        """
        if person_id not in self.person_moods:
            mood = PersonMood(person_id=person_id)
            mood.dynamic.position = self._home_vector()
            self.person_moods[person_id] = mood
        return self.person_moods[person_id]

    def snapshot_moods(self) -> list[tuple[str, PersonMood]]:
        """Copie instantanée de ``person_moods`` pour un lecteur hors boucle.

        Les vues d'administration itèrent depuis un thread synchrone pendant
        que la boucle asyncio insère et évince : ``RuntimeError: dictionary
        changed size during iteration``. ``list(dict.items())`` s'exécute
        d'un seul tenant sous le GIL ; une boucle Python, non.
        """
        return list(self.person_moods.items())

    def _home_vector(self) -> Vec3:
        """Home position for all oscillators.

        Combines two contributions:
          - `default_mood` heavily dimmed (magnitude 0.15) — the character's
            stable baseline personality
          - `circadian phase bias` (magnitude ~0.35 per circadian.py) — a
            time-of-day tint that nudges the baseline toward hopeful/playful/
            relieved/dreamy through the day

        Both are small so that emotional impulses still dominate the
        short-term dynamics — but the persistent pull gives Mika a felt
        "daily rhythm" without the character losing its identity.
        """
        from emotion import circadian

        base = pad.label_to_pad(
            self.temperament.default_mood,
            cfg_float("emotion.home_default_mood_weight", HOME_DEFAULT_MOOD_WEIGHT,
                      mini=0.0),
        )

        try:
            from config.personality import personality
            profile = personality.circadian_profile
        except Exception as exc:
            degradations.record("emotion.engine._home_vector", exc)
            profile = None

        state = circadian.current_state(profile=profile)
        # ``phase_bias`` reste une fonction PURE : c'est ici, au site d'appel,
        # que la configuration est lue, et l'amplitude lui est passée. Faire
        # lire la base à ``emotion/circadian.py`` aurait rendu impur un module
        # dont toute la testabilité tient à ce qu'il ne l'est pas.
        bias = circadian.phase_bias(
            state.phase,
            profile=profile,
            magnitude=circadian.configured_bias_magnitude(),
        )

        return pad.add(base, bias)


    def _person_home(self, mood: PersonMood, base: Vec3 | None = None) -> Vec3:
        """Resting point of one person's oscillator.

        A stance has to come back *somewhere*, and coming back to the same
        circadian point for everybody made "envers cette personne" the same
        hourly boilerplate for a friend, a troll and a stranger. The anchor is
        a smoothed trace of what this person has already provoked.

        The loop closes (anchor ← snapshots ← position ← home ← anchor) and
        that is safe on purpose: its fixed point is `base` itself, since an
        anchor equal to the circadian home reproduces exactly that home. No
        runaway is possible.
        """
        if base is None:
            base = self._home_vector()
        if mood.anchor is None:
            return base
        poids = cfg_float(
            "emotion.person_anchor_weight", PERSON_ANCHOR_WEIGHT,
            mini=0.0, maxi=1.0,
        )
        return pad.add(
            pad.scale(mood.anchor, poids),
            pad.scale(base, 1.0 - poids),
        )


    # ------------------------------------------------------------------
    # Core: process a new emotion from Claude
    # ------------------------------------------------------------------

    def _global_impulse_params(self, intensity: float) -> OscillatorParams:
        """Les paramètres du global pour CETTE impulsion-ci.

        Identiques à ``_global_params`` sauf le gain, qui suit l'intensité
        déclarée : à 1.0 une émotion pleine traverse presque autant que sur
        l'oscillateur de la personne, à 0.2 elle ne fait qu'effleurer. Le
        plafond reste la garde contre un tempérament très perméable.
        """
        base = self._global_params
        if base.impulse_gain <= 0.0:
            return base
        force = max(0.0, min(1.0, intensity))
        # INVARIANT : plancher + pente == facteur maximal (0.4 + 1.6 = 2.0).
        # Les trois sont réglables séparément parce qu'ils décrivent trois
        # choses (le seuil d'effleurement, la sensibilité, le plafond), mais
        # les désaccorder fait mordre le plafond avant l'intensité 1.0 — ou le
        # rend inatteignable, ce qui revient à le supprimer.
        gain = min(
            physics.global_ratchet_max(),
            base.impulse_gain * cfg_float(
                "emotion.global_gain_max_factor", GLOBAL_GAIN_MAX_FACTOR, mini=0.0,
            ),
            base.impulse_gain * (
                cfg_float("emotion.global_gain_floor", GLOBAL_GAIN_FLOOR, mini=0.0)
                + cfg_float("emotion.global_gain_slope", GLOBAL_GAIN_SLOPE, mini=0.0)
                * force
            ),
        )
        return dataclasses.replace(base, impulse_gain=gain)

    def _person_impulse_params(self, target: Vec3) -> OscillatorParams:
        """Le gain de CETTE impulsion, accordé au fond du tempérament.

        cos entre la cible déclarée et l'ancre de ``default_mood`` : une
        mélancolique vibre plus fort à la tristesse, une explosive à
        l'exaltation. Retenu **seulement positif** — voir la note de
        ``RESONANCE_STRENGTH`` : la résistance au contraire existe déjà
        (rappel + point de repos), la redoubler ici blinderait le personnage.

        Un ``default_mood`` neutre a une ancre nulle : cos indéfini, gain
        inchangé — un tempérament sans fond marqué ne résonne avec rien, ce
        qui est la définition du stoïque. Le plafond est 1.0, l'invariant du
        cliquet lui-même, et non ``ratchet_max`` : celui-ci borne ce qu'un
        *tempérament* peut se déclarer, pas ce qu'un événement qui tombe
        juste dans son grain peut lui faire.
        """
        base = self._person_params
        k = cfg_float("emotion.resonance_strength", RESONANCE_STRENGTH, mini=0.0)
        if k <= 0.0 or base.impulse_gain <= 0.0:
            return base
        ancre = pad.label_to_pad(self.temperament.default_mood, 1.0)
        n_ancre, n_cible = pad.norm(ancre), pad.norm(target)
        if n_ancre <= 1e-9 or n_cible <= 1e-9:
            return base
        cos = pad.dot(ancre, target) / (n_ancre * n_cible)
        if cos <= 0.0:
            return base
        gain = min(1.0, base.impulse_gain * (1.0 + k * cos))
        return dataclasses.replace(base, impulse_gain=gain)

    def _feel_for_herself(
        self, emotion_data: EmotionData, *, declared: bool = False,
    ) -> None:
        """Une impulsion de sa propre vie intérieure, sur l'humeur de fond.

        L'ennui, la solitude, un chantier bloqué ou abouti, l'espoir, la
        surprise d'une croyance révisée arrivent sous ``conscience_mika`` :
        ce n'est pas une stance envers quelqu'un qui *déteint* sur le fond,
        c'est le fond lui-même qui bouge. Or elles passaient par le chemin de
        la diffusion, taillé pour l'autre cas — cible ``ancre × intensité``
        et gain global 0,135 × (0,4 + 1,6·I). Une impulsion ``bored 0.25``
        visait donc un point de norme 0,17, c'est-à-dire surtout le neutre,
        avec un gain de 0,11, et τ_global (23 min) en effaçait 73 % avant la
        suivante, une demi-heure plus tard. Mesuré : huit ``bored 0.25``
        demi-horaires laissaient l'humeur de fond ``hopeful 0.07`` ; un
        chantier bloqué (``frustrated 0.35``) déplaçait la valence de −0,04.
        Rien de la vie intérieure n'atteignait jamais
        ``--- TON ETAT EMOTIONNEL ACTUEL ---``.

        Ici l'intensité dose le PAS et non la cible : la position avance de
        ``gain × I`` vers l'ancre PLEINE de l'émotion, ``gain`` étant celui
        de la personne — résonance du tempérament comprise, comme pour
        n'importe quelle stance. Depuis le repos, c'est exactement le premier
        pas qu'une personne provoquerait (``gain × I × ancre``) ; ce qui
        change, c'est la direction, toujours celle de l'émotion nommée et
        jamais celle de l'origine, et l'asymptote, l'ancre pleine. Un pas
        « léger » (``anxious 0.1`` à l'échec d'un tour) reste léger : 5 % du
        chemin. Mesuré à repos fixe : ``frustrated 0.35`` parcourt 18 % du
        chemin vers son ancre (5 % avant) et fait −0,11 de valence. Ce que
        le pas fait ensuite LIRE dépend du libellé par écart au repos
        (``pad.label_from_home``) : dans l'absolu, un ``bored 0.4``
        demi-horaire restait masqué par la teinte de l'heure ; depuis le
        repos, l'ennui tenu (0,2 par dix minutes, un plateau à ~0,25
        d'écart) se lit « légèrement lasse ».

        Le gain est borné à 1 AVANT d'être dosé : ``apply_impulse`` le borne
        de toute façon, donc c'est bien la part du gain effectif qu'on veut,
        pas la part d'un gain hors d'échelle (une configuration aberrante
        ferait sinon sauter la position sur l'ancre pleine à I = 0,1).
        Réservé aux identifiants internes (``identity.trust.is_internal_person``) :
        pas un chiffre de la diffusion personne → fond ne bouge.

        **Sauf ce que le modèle DÉCLARE dans ses propres actes** (``declared``,
        la balise d'un monologue sans destinataire, passée par le processeur) :
        elle passe par la diffusion ordinaire, comme la balise d'un tour avec
        quelqu'un. Le pas dosé ci-dessus est taillé pour les impulsions
        PROGRAMMÉES (ennui, blocage, fierté, révision), calibrées une à une ;
        appliqué à ``[EMOTION:excited:0.8]`` écrit en se parlant à elle-même,
        il posait 0,73 de débordement d'un coup — la porte 0,7 franchie, et
        elle s'excitait avec ses propres actes.
        """
        ancre = pad.label_to_pad(emotion_data.emotion, 1.0)
        force = max(0.0, min(1.0, emotion_data.intensity))
        if force <= 0.0 or pad.norm(ancre) <= 1e-9:
            return
        if declared:
            if self.temperament.global_bleed > 0:
                self.global_mood.dynamic.impulse_toward(
                    pad.label_to_pad(emotion_data.emotion, force),
                    self._global_impulse_params(force),
                )
            return
        base = self._person_impulse_params(ancre)
        params = dataclasses.replace(
            base, impulse_gain=max(0.0, min(1.0, base.impulse_gain)) * force,
        )
        self.global_mood.dynamic.impulse_toward(ancre, params)

    def process_emotion(
        self, emotion_data: EmotionData, person_id: str, *,
        declared: bool = False,
    ) -> PersonMood:
        """Apply a new emotion as a ratchet toward its PAD anchor.

        Successive impulses of the same sign escalate (each covers a share of
        what is left to the target), an opposing one brings the position back
        toward the other side, and the spring governs how long any of it stays
        readable.

        ``declared`` : la balise ``[EMOTION:]`` d'un tour écrit par le modèle
        (le processeur), par opposition à une impulsion programmée par la
        vie intérieure. Ne change rien pour une personne ; pour un identifiant
        interne, voir ``_feel_for_herself``.
        """
        self._recompute_params()  # in case temperament changed at runtime

        now = time.time()
        person = self._get_person_mood(person_id)
        # Le repos courant, posé sur l'humeur de fond pour que ses lectures
        # par écart (``felt``, ``overflow_intensity``) parlent de maintenant.
        self.global_mood.home = self._home_vector()

        target = pad.label_to_pad(emotion_data.emotion, emotion_data.intensity)
        person.dynamic.impulse_toward(target, self._person_impulse_params(target))
        # Ce qu'elle vient de dire éprouver, gardé tel quel à côté de la
        # position. Le prompt du tour suivant le relit plutôt que de demander
        # à `pad_to_label` de renommer un vecteur mélangé.
        person.last_declared = (emotion_data.emotion, emotion_data.intensity)
        person.last_declared_at = now

        # Propagate into the global mood. The bleed reduces the *gain*, once —
        # reducing the target as well capped the global mood around 0.30, well
        # under the 0.7 that Factor 3 of conscience/scoring.py tests, so that
        # factor could never fire.
        #
        # Le gain est modulé par l'INTENSITÉ déclarée : une contrariété passe
        # au travers, une détresse traverse. À gain fixe (0.135 au défaut),
        # `--- TON ETAT EMOTIONNEL ACTUEL ---` — le dernier bloc affectif avant
        # la mémoire, donc en zone de récence maximale — annonçait encore « ton
        # humeur générale est contente, comme d'habitude » au sixième tour d'une
        # conversation où quelqu'un finit par écrire « je pleure, j'en peux
        # plus ». Le bloc censé porter son ressenti était le plus lent de tous
        # à bouger, exactement là où le modèle le lit le plus fort.
        if is_internal_person(person_id):
            self._feel_for_herself(emotion_data, declared=declared)
        elif self.temperament.global_bleed > 0:
            self.global_mood.dynamic.impulse_toward(
                target, self._global_impulse_params(emotion_data.intensity),
            )

        person.last_interaction = now
        person.last_update = now
        self.global_mood.last_update = now

        person.history.append(EmotionHistoryEntry(
            timestamp=now,
            emotion=emotion_data.emotion,
            intensity=emotion_data.intensity,
            source="impulse",
        ))

        logger.debug(
            "Emotion [%s]: impulse toward %s(%.2f)",
            person_id, emotion_data.emotion.value, emotion_data.intensity,
        )

        return person

    # ------------------------------------------------------------------
    # Compute message emotion (blend of person + global)
    # ------------------------------------------------------------------


    def compute_message_emotion(self, person_id: str) -> MessageEmotion:
        """Compute the final emotion for a message by blending PAD positions.

        Weights: 60% person position + 40% global position in PAD space.
        The blend is a weighted mean of the two 3D vectors, then projected
        back onto the top-2 nearest anchors so the output can express
        ambivalence (e.g. "mostly grateful, a touch nostalgic").
        """
        person = self._get_person_mood(person_id)
        default = self.temperament.default_mood

        p_label, p_intensity = pad.pad_to_label(person.dynamic.position)
        g_label, g_intensity = pad.pad_to_label(self.global_mood.dynamic.position)

        blended = pad.add(
            pad.scale(person.dynamic.position, 0.6),
            pad.scale(self.global_mood.dynamic.position, 0.4),
        )
        final_label, final_intensity = pad.pad_to_label(blended)
        blend_components = pad.pad_to_blend(blended, top_k=2)

        # If the blended vector is essentially zero, expose the default mood
        # as a weak background so the frontend doesn't get stuck on neutral.
        if final_intensity < 0.05:
            final_label = default
            final_intensity = 0.1
            if not blend_components:
                blend_components = [(default, 0.1)]

        return MessageEmotion(
            emotion=final_label,
            intensity=round(final_intensity, 2),
            person_emotion=p_label if p_intensity > 0.05 else default,
            person_intensity=round(p_intensity, 2),
            global_emotion=g_label if g_intensity > 0.05 else default,
            global_intensity=round(g_intensity, 2),
            blend=tuple(blend_components),
        )

    async def turn_emotion_view(
        self, person_id: str, declared: EmotionData | None,
    ) -> TurnEmotionView:
        """What the frame answering this turn should carry.

        Called after `process_emotion`, so the oscillator already holds the
        turn. When the reply declared a tag, that tag wins: it is what she
        chose while writing, where the oscillator only says how the relation
        stands. The blend is read on the projected position so the frame's
        `emotion` and its `blend[0]` can never disagree — the frontend's
        ambivalence gate reads exactly that pair.

        Never raises: a turn goes out with an emotion, or with the fallback.
        """
        try:
            return self._build_turn_view(person_id, declared)
        except Exception as exc:
            degradations.record("emotion: vue du tour", exc)
        return self._plain_turn_view(declared)

    def _build_turn_view(
        self, person_id: str, declared: EmotionData | None,
    ) -> TurnEmotionView:
        mood = self._get_person_mood(person_id)
        projected = dynamics.peak_projection(
            mood.dynamic.position,
            mood.dynamic.velocity,
            self._person_home(mood),
            self._person_params,
        )
        blend = [(e.value, w) for e, w in pad.pad_to_blend(projected, top_k=2)]
        state = self.get_state_dict(person_id)

        if declared is not None:
            name = declared.emotion.value
            if not blend or blend[0][0] != name:
                blend = [(name, declared.intensity), *blend][:2]
            return TurnEmotionView(
                emotion=name,
                intensity=declared.intensity,
                blend=blend,
                state=state,
                declared=True,
            )

        current = self.compute_message_emotion(person_id)
        if not blend:
            blend = [(e.value, w) for e, w in current.blend]
        return TurnEmotionView(
            emotion=current.emotion.value,
            intensity=current.intensity,
            blend=blend,
            state=state,
            declared=False,
        )

    def _plain_turn_view(self, declared: EmotionData | None) -> TurnEmotionView:
        """Fallback view — reads nothing, so it cannot fail in turn."""
        if declared is not None:
            name, intensity = declared.emotion.value, declared.intensity
        else:
            name, intensity = self.temperament.default_mood.value, 0.0
        return TurnEmotionView(
            emotion=name,
            intensity=intensity,
            blend=[(name, intensity)],
            state={},
            declared=declared is not None,
        )

    # ------------------------------------------------------------------
    # System prompt context
    # ------------------------------------------------------------------

    def get_global_mood_context(self) -> str:
        """French description of Mika's *standalone* emotional state.

        This is about Mika alone, independent of the interlocutor. The
        per-person affective stance belongs to `get_person_affect_context()`
        and is injected in the `person_context` block, not here.
        """
        default = self.temperament.default_mood
        return self.global_mood.to_prompt_description(
            default, home=self._home_vector(),
        )

    async def chaleur_envers(self, person_id: str) -> float:
        """La chaleur du fond affectif envers cette personne, dans [0, 1].

        L'ancre de ``PersonMood`` est le fond que les conversations ont
        installé (et que le temps guérit) : sa composante plaisir positive
        dit « penser à elle fait du bien ». Une ancre froide ou absente vaut
        0. ``ensure_person_loaded`` d'abord : lire ``person_moods`` à froid
        est le bug documenté de la fiche affect. Lue par deux bords — la
        divulgation graduée du tour (``pipeline``) et le manque de la
        conscience — qui ne doivent pas s'importer l'un l'autre.
        """
        await self.ensure_person_loaded(person_id)
        mood = self.person_moods.get(person_id)
        ancre = getattr(mood, "anchor", None)
        if not ancre:
            return 0.0
        return max(0.0, min(1.0, float(ancre[0])))

    def get_person_affect_context(self, person_id: str) -> str:
        """French description of how Mika feels *toward this specific person*.

        Covers both the current PersonMood (live PAD oscillator) and the
        "ancrage" marker when the stance was built rather than triggered
        once. Returned as a block ready to be concatenated into the
        person_context section.

        Returns "" when the state is effectively neutral — absence is
        more useful than boilerplate ("pas de sentiment particulier")
        for every unfamiliar person. The caller's context block stays
        empty in that case, which keeps the prompt lean.
        """
        person = self._get_person_mood(person_id)
        # The "or a fresh impulse" clause read the velocity, to catch an
        # impulse not yet integrated. An impulse now moves the position
        # itself, so there is nothing left in flight to catch.
        #
        # Une déclaration fraîche parle en revanche pour elle-même : un tour
        # qui vient de dire « [EMOTION:thinking:0.4] » a un ressenti, même si
        # le vecteur correspondant est court. Se taire dans ce cas, c'est
        # perdre précisément ce dont on est sûr.
        if person.fresh_declaration() is None and self._at_rest_toward(person):
            # Au repos propre, mais ce repos-là peut être marqué : une ancre
            # construite (brouille, chaleur) se dit même quand rien ne se
            # passe. Un repos confondu avec le repos commun reste muet.
            return self._fond_installe(person)

        commun = self._home_vector()
        lines: list[str] = [person.to_prompt_description(
            home=self._person_home(person, commun), common_home=commun,
        )]

        if self._is_anchored(person):
            lines.append(
                "Cette emotion envers cette personne est bien ancree, "
                "elle ne va pas s'estomper facilement."
            )

        return "\n".join(lines)

    def _fond_installe(self, mood: PersonMood) -> str:
        """La phrase du fond (``PersonMood._fond_description``), ou ``""``."""
        if mood.anchor is None:
            return ""
        commun = self._home_vector()
        return mood._fond_description(self._person_home(mood, commun), commun)

    def _at_rest_toward(self, mood: PersonMood) -> bool:
        """Rien à dire de cette stance : jamais provoquée, ou revenue au repos.

        Deux cas, et l'un ne se déduit pas de l'autre :

        - **jamais rien provoqué** — ni impulsion dans ce processus, ni ancre
          restaurée d'un relevé (le contrat de ``PersonMood.anchor`` :
          ``None`` tant qu'elle n'a rien provoqué). Une lecture crée
          l'oscillateur à l'origine et la boucle le laisse rejoindre le
          repos : la norme brute franchissait 0,1 en route et chaque inconnu
          recevait « tu te sens légèrement joueuse » — la teinte circadienne,
          pas un sentiment ;
        - **revenue au repos** — l'écart au repos PROPRE de la personne
          (``_person_home``) est sous ``REST_TOLERANCE``. Mesuré depuis
          l'origine, ce repos (norme 0,14 à 0,50) se lisait comme une
          stance permanente envers tout le monde.
        """
        if not mood.history and mood.anchor is None:
            return True
        return pad.distance(
            mood.dynamic.position, self._person_home(mood),
        ) < REST_TOLERANCE

    def _is_anchored(self, mood: PersonMood) -> bool:
        """Whether a stance was built by several agreeing turns, not just one."""
        position = mood.dynamic.position
        if pad.norm(position) < cfg_float(
            "emotion.anchored_min_norm", ANCHORED_MIN_NORM, mini=0.0,
        ):
            return False

        cutoff = time.time() - cfg_float(
            "emotion.anchored_window_seconds", ANCHORED_WINDOW_S, mini=0.0,
        )
        agreeing = 0
        for entry in mood.history:
            if entry.timestamp < cutoff:
                continue
            if pad.dot(pad.EMOTION_ANCHORS[entry.emotion], position) > 0:
                agreeing += 1

        return agreeing >= cfg_int(
            "emotion.anchored_min_impulses", ANCHORED_MIN_IMPULSES, mini=1,
        )

    # ------------------------------------------------------------------
    # State dict for WebSocket
    # ------------------------------------------------------------------

    def get_state_dict(self, person_id: str) -> dict:
        """Get full emotional state for WebSocket broadcast."""
        person = self._get_person_mood(person_id)
        msg = self.compute_message_emotion(person_id)

        return {
            "person": person.to_dict(),
            "global": self.global_mood.to_dict(),
            "message": msg.to_dict(),
        }


    # ------------------------------------------------------------------
    # Decay loop — pure physics integration
    # ------------------------------------------------------------------

    async def _decay_loop(self):
        """Background loop: advance all oscillators every second."""
        while True:
            try:
                await asyncio.sleep(_TICK_DT)
                self._apply_decay()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Emotion decay loop error")


    def _apply_decay(self):
        """Step the physics forward (``physics.advance``), heal anchors, evict."""
        now = time.time()
        home = self._home_vector()
        self.global_mood.home = home
        # Un seul plafond et un seul seuil d'éviction pour toute la passe.
        plafond = physics.max_advance_seconds()
        eviction = cfg_int(
            "emotion.idle_eviction_seconds", self._IDLE_EVICTION_SECONDS, mini=1,
        )

        expired_persons = []
        for pid, person in self.person_moods.items():
            dt = max(0.0, now - person.last_update)
            if dt <= 0.0:
                continue
            physics.heal_anchor(person, home, dt)
            person_home = self._person_home(person, home)
            physics.advance(
                person.dynamic, person_home, self._person_params, dt,
                max_advance=plafond,
            )
            person.last_update = now
            if (
                now - person.last_interaction > eviction
                and pad.distance(person.dynamic.position, person_home) < 0.05
            ):
                expired_persons.append(pid)

        if expired_persons:
            try:
                self._evict_persons(expired_persons)
            except Exception as exc:
                degradations.record("emotion.engine._apply_decay", exc)

        dt = max(0.0, now - self.global_mood.last_update)
        if dt > 0.0:
            physics.advance(
                self.global_mood.dynamic, home, self._global_params, dt,
                max_advance=plafond,
            )
            self.global_mood.last_update = now

        poussee = physics.nudged_position(
            self.global_mood.dynamic.position, home, self.temperament.volatility,
        )
        if poussee is not None:
            self.global_mood.dynamic.position = poussee

    def _evict_persons(self, person_ids: list[str]) -> None:
        """Sortir de la RAM les humeurs inactives — sauf celles encore lues.

        ``last_interaction`` ne date que le dernier *message*, jamais une
        lecture : quelqu'un qui laisse son onglet ouvert sans plus parler
        franchit le seuil d'inactivité alors qu'``emotion_sync`` lit son
        humeur toutes les quelques secondes. L'évincer là est doublement
        faux — la lecture suivante recrée l'oscillateur à l'origine (chute
        d'intensité visible à l'écran, une fois par heure de silence), et
        ``ensure_person_loaded`` redevenant un no-op, le ``EmotionSnapshot``
        qui portait le sentiment accumulé n'est plus jamais relu.

        Seules les connexions vivantes protègent : un handle de module
        (Telegram) est joignable à vie, l'oscillateur associé ne l'est pas.
        """
        from communication.presence import presence_registry
        from emotion.sync import emotion_sync

        connectes = {
            i.person_id for i in presence_registry.reachable() if i.is_consumer
        }
        for pid in person_ids:
            if pid in connectes:
                continue
            del self.person_moods[pid]
            # Deux caches indexés par person_id survivaient à l'oscillateur
            # qu'ils décrivent : ``_last_snapshot_time`` n'était purgé nulle
            # part, et ``emotion_sync._hydrated`` marque « déjà hydratée »
            # une personne dont l'humeur vient de quitter la RAM — la
            # prochaine lecture sauterait l'hydratation et repartirait de
            # l'origine.
            self._last_snapshot_time.pop(pid, None)
            emotion_sync.forget(pid)


    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_analytics(self) -> dict:
        """Compute emotion analytics across all persons."""
        all_entries = []
        for _pid, person in self.snapshot_moods():
            all_entries.extend(list(person.history))

        if not all_entries:
            return {
                "total_interactions": 0,
                "distribution": {},
                "dominant_emotion": self.temperament.default_mood.value,
                "persons_tracked": 0,
            }

        distribution: dict[str, float] = {}
        for entry in all_entries:
            key = entry.emotion.value
            distribution[key] = distribution.get(key, 0.0) + entry.intensity

        total = sum(distribution.values()) or 1.0
        distribution = {k: round(v / total, 3) for k, v in distribution.items()}
        dominant = max(distribution, key=distribution.get)

        return {
            "total_interactions": len(all_entries),
            "distribution": distribution,
            "dominant_emotion": dominant,
            "persons_tracked": len(self.person_moods),
        }


# Module-level singleton
emotion_engine = EmotionEngine()
