"""Le murmure, branché — ce que `test_murmure_conscience.py` ne peut pas voir.

Celui-là couvre le module et ses six gardes. Ici on vérifie le CÂBLAGE, et
surtout la seule chose qui ne se lit pas dans le module : **la position de
l'appel**. Elle est prise entre deux bornes, et chacune casse quelque chose de
différent si on la franchit.

Les assertions de position passent par l'AST, jamais par une recherche de
chaîne dans le source : les commentaires du moteur citent les fonctions à ne
pas appeler, et une recherche textuelle prend la mise en garde pour
l'infraction. Ce piège s'est produit deux fois dans ce chantier.
"""

import ast
import inspect
import textwrap

import pytest


def _corps(fonction) -> ast.AST:
    return ast.parse(textwrap.dedent(inspect.getsource(fonction)))


def _appels(arbre) -> list[ast.Call]:
    return [n for n in ast.walk(arbre) if isinstance(n, ast.Call)]


def _nom_appele(noeud: ast.Call) -> str:
    fn = noeud.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return ""


# ===========================================================================
# 1. La position, prouvée à la ligne
# ===========================================================================

class TestPosition:

    def test_le_murmure_est_entre_le_reveil_et_l_acte(self):
        """Les deux bornes sont chargées.

        AVANT `note_interaction()` : elle pose la phase à AWAKE de façon
        *synchrone*, et la garde de sommeil du murmure lit cette phase. Un
        appel une ligne plus haut se tairait sur `deep_sleep` chaque nuit —
        soit exactement les cycles où une pensée à voix haute rend la nuit
        habitée plutôt que muette.

        APRÈS `_act` : `_select_recipient` vit à l'intérieur de `_act`. Au
        point d'appel, aucun destinataire n'existe dans la portée, ce qui rend
        le piège du `person_id` — bascule en persona SPEAKING, donc note
        vocale Telegram — structurellement impossible.
        """
        from conscience.engine import ConscienceEngine

        arbre = _corps(ConscienceEngine._decide_inner)
        lignes = {}
        for noeud in _appels(arbre):
            nom = _nom_appele(noeud)
            if nom in ("note_interaction", "murmurer", "_act"):
                lignes.setdefault(nom, noeud.lineno)

        assert set(lignes) == {"note_interaction", "murmurer", "_act"}, lignes
        assert lignes["note_interaction"] < lignes["murmurer"] < lignes["_act"], (
            f"ordre trouvé : {lignes}"
        )

    def test_le_murmure_est_attendu_et_non_detache(self):
        """L'ordre EST le propos.

        Détaché, il courrait contre l'appel de `_act` sur le même sémaphore de
        provider — un seul créneau par défaut sur Ollama — et sortirait après
        la phrase qu'il devait précéder, de façon non déterministe. Il
        exigerait en outre un jeu de références fortes que `shutdown()`
        n'attend pas, reproduisant une fuite connue.
        """
        from conscience.engine import ConscienceEngine

        arbre = _corps(ConscienceEngine._decide_inner)
        attendus = [
            n for n in ast.walk(arbre)
            if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
            and _nom_appele(n.value) == "murmurer"
        ]
        assert len(attendus) == 1
        detaches = [
            n for n in _appels(arbre)
            if _nom_appele(n) in ("create_task", "_detach", "_spawn_decision")
        ]
        assert not detaches, "le murmure ne doit pas être détaché"


# ===========================================================================
# 2. Aucun person_id ne part jamais
# ===========================================================================

class TestJamaisDeDestinataire:

    def test_murmurer_n_accepte_pas_de_person_id(self):
        """Garanti par le MODULE et non par la vigilance de l'appelant."""
        from conscience.murmure import murmurer

        assert "person_id" not in inspect.signature(murmurer).parameters

    @pytest.mark.parametrize("site", ["conscience", "runner"])
    def test_aucun_site_ne_passe_de_destinataire(self, site):
        if site == "conscience":
            from conscience.engine import ConscienceEngine
            arbre = _corps(ConscienceEngine._decide_inner)
        else:
            from projects.runner import ProjectRunner
            arbre = _corps(ProjectRunner._murmur)

        for noeud in _appels(arbre):
            if _nom_appele(noeud) != "murmurer":
                continue
            kwargs = {k.arg for k in noeud.keywords}
            assert "person_id" not in kwargs


# ===========================================================================
# 3. L'intention ne dérive pas d'un flottant
# ===========================================================================

class TestIntentionStable:

    def _ctx(self, **kw):
        from conscience.types import DecisionContext
        base = dict(
            pending_observations=[], global_mood="curious", global_intensity=0.4,
            idle_seconds=7200, in_cooldown=False, max_pertinence=0.0,
            weighted_urgency=0.0,
        )
        base.update(kw)
        return DecisionContext(**base)

    def _engine(self):
        from conscience.engine import ConscienceEngine
        e = ConscienceEngine.__new__(ConscienceEngine)
        e._salutation_en_attente = None
        return e

    def test_deux_cycles_au_resume_de_pulsion_different_rendent_la_meme_intention(self):
        """La sixième garde compare l'intention normalisée d'un tour à l'autre.

        `reason` et `ctx.drive_summary` embarquent des flottants — « curiosity:
        0.87 » — qui bougent à chaque cycle : bâtir l'intention dessus
        dépenserait le quota du jour en huit variantes d'une seule pensée.
        """
        e = self._engine()
        a = e._intention_de_lacte(self._ctx(drive_summary="curiosity:0.87"))
        b = e._intention_de_lacte(self._ctx(drive_summary="curiosity:0.91"))
        assert a == b

    def test_sans_motif_l_intention_est_vide(self):
        """Sortie valide : la garde « pas d'intention » coupe avant la dépense."""
        e = self._engine()
        ctx = self._ctx(idle_seconds=0.0, global_intensity=0.0)
        import drives.engine as de
        from unittest.mock import patch
        with patch.object(de.drive_engine, "pulsion_saillante", lambda: None):
            assert e._intention_de_lacte(ctx) == ""

    def test_une_action_programmee_nomme_son_objet(self):
        from types import SimpleNamespace

        e = self._engine()
        ctx = self._ctx(
            scheduled_actions=[SimpleNamespace(prompt="relire le brouillon")],
        )
        assert e._intention_de_lacte(ctx) == "relire le brouillon"

    def test_le_prompt_et_le_murmure_lisent_les_memes_declencheurs(self):
        """Sans source commune, elle murmurerait une intention que le prompt
        ne mentionne pas."""
        from conscience.engine import ConscienceEngine

        for fonction in (
            ConscienceEngine._intention_de_lacte,
            ConscienceEngine._composer_vecu,
        ):
            noms = {_nom_appele(n) for n in _appels(_corps(fonction))}
            assert "_declencheurs" in noms, fonction.__name__


# ===========================================================================
# 4. Le réglage configuré atteint bien le module pur
# ===========================================================================

class TestReglage:

    def test_le_resolveur_ne_vit_pas_dans_le_module_pur(self):
        """`murmure.py` doit rester sans lecture de registre : ses tests
        mesurent la calibration déclarée, pas la base de la machine.

        Sur l'AST, et pas sur le texte : le module explique dans un commentaire
        où la résolution DOIT vivre, en citant l'appel — une recherche de
        chaîne prend l'explication pour l'infraction. C'est la troisième fois
        que ce piège se referme dans ce chantier.
        """
        import conscience.murmure as m

        arbre = ast.parse(inspect.getsource(m))
        lecteurs = {"cfg_int", "cfg_float", "cfg_bool", "cfg_str", "cfg_list"}
        trouves = {
            _nom_appele(n) for n in _appels(arbre)
        } & lecteurs
        assert not trouves, trouves
        importes = {
            alias.name
            for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)
            for alias in n.names
        } | {
            n.module or "" for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)
        }
        assert "configs.service" not in importes
        assert "config_service" not in importes

    def test_les_deux_appelants_passent_un_tuning(self):
        """Sans lui, chacun tournerait sur les défauts du module et l'écran de
        configuration ne piloterait rien."""
        from conscience.engine import ConscienceEngine
        from projects.runner import ProjectRunner

        for fonction in (ConscienceEngine._decide_inner, ProjectRunner._murmur):
            for noeud in _appels(_corps(fonction)):
                if _nom_appele(noeud) == "murmurer":
                    assert "tuning" in {k.arg for k in noeud.keywords}, fonction

    def test_le_resolveur_rend_les_defauts_quand_le_registre_est_muet(self):
        from conscience.murmure import DEFAULT_TUNING
        from conscience.murmure_reglage import tuning

        assert tuning() == DEFAULT_TUNING


# ===========================================================================
# 5. Le runner délègue, et ne garde pas de second chemin
# ===========================================================================

class TestRunner:

    def test_le_second_chemin_de_diffusion_a_disparu(self):
        """`_broadcast_inner_thought` diffusait sans aucune garde devant."""
        from projects.runner import ProjectRunner

        assert not hasattr(ProjectRunner, "_broadcast_inner_thought")

    def test_le_mode_professionnel_devient_une_garde_journalisee(self):
        """La porte n'est pas supprimée : elle change de main.

        Le `return` sec ne disait rien ; en garde, elle apparaît dans
        `etat_murmure()`, ce qui distingue « rien à dire » de « projet pro ».
        """
        from projects.runner import ProjectRunner

        arbre = _corps(ProjectRunner._murmur)
        assert "emotion_policy" not in {
            n.attr for n in ast.walk(arbre) if isinstance(n, ast.Attribute)
        } - {"emotion_policy"}  # présent, mais…
        appels = [n for n in _appels(arbre) if _nom_appele(n) == "murmurer"]
        assert len(appels) == 1
        assert "mode_professionnel" in {k.arg for k in appels[0].keywords}

    def test_le_contextvar_de_projet_est_conserve(self):
        """Il facture l'appel au budget mensuel du projet."""
        from projects.runner import ProjectRunner

        noms = {_nom_appele(n) for n in _appels(_corps(ProjectRunner._murmur))}
        assert {"set", "reset"} <= noms


# ===========================================================================
# 6. Le tick ne murmure jamais
# ===========================================================================

class TestCout:

    def test_seule_la_branche_act_murmure(self):
        """2 880 tours par jour : un appel LLM au tick est un coût permanent.

        L'appel doit être sous le `if decision == "act"`, pas au niveau du
        corps de `_decide_inner`.
        """
        from conscience.engine import ConscienceEngine

        arbre = _corps(ConscienceEngine._decide_inner)
        dans_un_if = False
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.If):
                continue
            for interne in ast.walk(noeud):
                if isinstance(interne, ast.Call) and _nom_appele(interne) == "murmurer":
                    dans_un_if = True
        assert dans_un_if, "le murmure doit être conditionné, pas inconditionnel"

    def test_un_role_non_mappe_est_compte(self):
        """Le dépôt démarre non configuré exprès : sans cette trace, l'état du
        murmure dirait « ok » pendant que rien ne sort jamais."""
        import pipeline.inner_voice as iv

        arbre = ast.parse(textwrap.dedent(inspect.getsource(iv.generate_inner_thought)))
        records = [
            n for n in _appels(arbre)
            if _nom_appele(n) == "record"
        ]
        assert records, "un échec de génération doit entrer au registre"
