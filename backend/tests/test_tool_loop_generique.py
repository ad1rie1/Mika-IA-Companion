"""REF-08 — une boucle d'outils, un Protocol, des adaptateurs.

Trois corps de boucle quasi identiques (Claude, OpenAI-compatibles, Ollama,
plus Gemini) et un routeur qui découvrait la forme par ``hasattr``. Ces tests
pinnent le résultat :

- aucun module provider ne contient plus sa propre itération d'outils —
  chacun branche un adaptateur sur ``_tool_loop.executer_la_boucle`` ;
- les correctifs transverses (rejeu d'une réponse coupée en plein appel,
  issue d'un handler rendue au modèle sans jamais lever, mémo de paramètres,
  relevé d'usage dans un ``finally``, texte de repli) sont testés UNE fois,
  sur la boucle, avec un adaptateur factice ;
- le routeur appelle la forme structurée sans sonder une capacité, et le
  paquet ``ai.providers`` n'expose qu'un Protocol.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.providers._tool_loop import (
    MAX_TURNS_MARKER,
    TOOL_CALL_CAP_CEILING,
    TRUNCATED_TOOL_CALL_MARKER,
    AdaptateurOutils,
    AppelOutil,
    Issue,
    Reponse,
    contenu_json,
    executer_la_boucle,
)

_BACKEND = Path(__file__).resolve().parent.parent
_PROVIDERS = _BACKEND / "ai" / "providers"
_MODULES_PROVIDERS = (
    "claude.py", "openai_provider.py", "glm_provider.py",
    "ollama_provider.py", "ollama_cloud_provider.py", "gemini_provider.py",
    "_openai_tools.py",
)


# ── L'adaptateur factice ─────────────────────────────────────────

class _Outil:
    def __init__(self, name="lire", result=None, raises=None):
        self.name = name
        self.description = "outil de test"
        self.calls: list = []
        self._result = {"ok": True} if result is None else result
        self._raises = raises

    def to_json_schema(self):
        return {"type": "object", "properties": {}}

    async def handler(self, args):
        self.calls.append(args)
        if self._raises is not None:
            raise self._raises
        return self._result


class _Adaptateur(AdaptateurOutils):
    """Rejoue un script de ``Reponse`` ; note tout ce que la boucle lui dit."""

    LABEL = "Factice"

    def __init__(self, script, *, echec_appel=None):
        self._script = list(script)
        self._echec_appel = echec_appel
        self.plafonds: list[int] = []
        self.tours_rejoues: list[Reponse] = []
        self.issues: list[list[Issue]] = []
        self.clos = 0

    async def appeler(self, max_tokens):
        self.plafonds.append(max_tokens)
        if self._echec_appel is not None:
            raise self._echec_appel
        if not self._script:
            raise AssertionError("appel au-delà du script")
        return self._script.pop(0)

    def lire(self, brut):
        return brut

    def rejouer_le_tour(self, brut, reponse):
        self.tours_rejoues.append(reponse)

    def rendre_les_resultats(self, issues):
        self.issues.append(issues)

    def clore(self):
        self.clos += 1


def _appel(name="lire", arguments=None, id="c1"):
    return AppelOutil(name=name, arguments={"q": 1} if arguments is None else arguments, id=id)


def _lance(adaptateur, tools, *, max_tokens=1000, max_turns=10):
    return asyncio.run(executer_la_boucle(
        adaptateur, tools=tools, max_tokens=max_tokens, max_turns=max_turns,
    ))


# =================================================================
# (a) Plus aucune boucle d'outils chez les providers
# =================================================================

def _boucles_qui_attendent_et_empilent(tree: ast.AST) -> list[int]:
    """Lignes des boucles contenant un ``await`` ET un ``.append``.

    C'est la signature d'une boucle d'outils : appeler le modèle et empiler
    dans le fil. La reprise de paramètres (``while True`` autour d'une seule
    requête) attend sans empiler ; un ``list_models`` empile sans attendre.
    """
    coupables = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
            continue
        attend = any(isinstance(n, ast.Await) for n in ast.walk(node))
        empile = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "append"
            for n in ast.walk(node)
        )
        if attend and empile:
            coupables.append(node.lineno)
    return coupables


class TestPlusDeBoucleChezLesProviders:

    def test_aucun_module_provider_n_itere_sur_des_outils(self):
        offenders = []
        for name in _MODULES_PROVIDERS:
            tree = ast.parse((_PROVIDERS / name).read_text(encoding="utf-8"))
            offenders += [f"{name}:{ligne}" for ligne in _boucles_qui_attendent_et_empilent(tree)]
        assert offenders == []

    def test_la_seule_boucle_est_dans_le_module_generique(self):
        """Le critère ci-dessus n'est pas vide : appliqué au module générique,
        il trouve la boucle."""
        tree = ast.parse((_PROVIDERS / "_tool_loop.py").read_text(encoding="utf-8"))
        assert _boucles_qui_attendent_et_empilent(tree)

    @pytest.mark.parametrize(
        "name", ["claude.py", "openai_provider.py", "glm_provider.py",
                 "ollama_provider.py", "gemini_provider.py"],
    )
    def test_chaque_tour_outille_passe_par_la_boucle_generique(self, name):
        tree = ast.parse((_PROVIDERS / name).read_text(encoding="utf-8"))
        fonction = next(
            f for f in ast.walk(tree)
            if isinstance(f, ast.AsyncFunctionDef) and f.name == "complete_chat_with_tools"
        )
        appels = {
            ast.unparse(n.func).rsplit(".", 1)[-1]
            for n in ast.walk(fonction) if isinstance(n, ast.Call)
        }
        assert "executer_la_boucle" in appels

    def test_chaque_famille_a_son_adaptateur(self):
        from ai.providers._openai_tools import AdaptateurOpenAI
        from ai.providers.claude import _AdaptateurClaude
        from ai.providers.gemini_provider import _AdaptateurGemini
        from ai.providers.ollama_provider import _AdaptateurOllama

        for cls in (AdaptateurOpenAI, _AdaptateurClaude, _AdaptateurGemini, _AdaptateurOllama):
            assert issubclass(cls, AdaptateurOutils), cls.__name__
            for methode in ("appeler", "lire", "rejouer_le_tour", "rendre_les_resultats"):
                assert getattr(cls, methode) is not getattr(AdaptateurOutils, methode), (
                    f"{cls.__name__}.{methode} hérite du socle abstrait"
                )

    def test_l_amorce_a_deux_chaines_a_disparu(self):
        """Ni ``complete_with_tools`` chez un provider, ni ``ai/tool_client``."""
        from ai.providers.claude import ClaudeProvider
        from ai.providers.gemini_provider import GeminiProvider
        from ai.providers.glm_provider import GLMProvider
        from ai.providers.ollama_provider import OllamaProvider
        from ai.providers.openai_provider import OpenAIProvider
        from ai.router import AIRouter

        for cls in (ClaudeProvider, GeminiProvider, GLMProvider, OllamaProvider, OpenAIProvider, AIRouter):
            assert not hasattr(cls, "complete_with_tools"), cls.__name__
        assert not (_BACKEND / "ai" / "tool_client.py").exists()


# =================================================================
# (b) Les correctifs transverses, une fois, sur la boucle
# =================================================================

class TestLaBoucle:

    def test_un_appel_execute_et_son_resultat_rendu(self):
        outil = _Outil("lire")
        adaptateur = _Adaptateur([
            Reponse(texte="je regarde", appels=[_appel("lire")]),
            Reponse(texte="fini", terminee=True),
        ])
        texte, appeles = _lance(adaptateur, [outil])

        assert texte == "je regarde\n\nfini"
        assert appeles == ["lire"]
        assert outil.calls == [{"q": 1}]
        assert len(adaptateur.tours_rejoues) == 1
        [issues] = adaptateur.issues
        assert issues[0].genre == "ok" and issues[0].resultat == {"ok": True}
        assert not issues[0].en_echec()

    def test_le_texte_vide_n_est_pas_empile(self):
        adaptateur = _Adaptateur([
            Reponse(texte="", appels=[_appel()]),
            Reponse(texte="fini"),
        ])
        texte, _ = _lance(adaptateur, [_Outil()])
        assert texte == "fini"

    def test_terminee_arrete_meme_avec_des_appels(self):
        """Un refus porte parfois un bloc d'appel : rien n'est exécuté."""
        outil = _Outil()
        adaptateur = _Adaptateur([Reponse(texte="non", appels=[_appel()], terminee=True)])
        texte, appeles = _lance(adaptateur, [outil])
        assert (texte, appeles) == ("non", [])
        assert outil.calls == [] and adaptateur.tours_rejoues == []

    def test_les_arguments_json_sont_decodes_une_seule_fois_ici(self):
        outil = _Outil()
        adaptateur = _Adaptateur([
            Reponse(appels=[_appel(arguments=json.dumps({"limite": 3}))]),
            Reponse(texte="ok"),
        ])
        _lance(adaptateur, [outil])
        assert outil.calls == [{"limite": 3}]

    def test_des_arguments_vides_valent_un_dict_vide(self):
        outil = _Outil()
        adaptateur = _Adaptateur([Reponse(appels=[_appel(arguments="")]), Reponse(texte="ok")])
        _lance(adaptateur, [outil])
        assert outil.calls == [{}]


class TestTroncatureEnPleinAppel:

    def test_rejouee_une_fois_avec_un_plafond_double(self):
        outil = _Outil()
        adaptateur = _Adaptateur([
            Reponse(texte="je vais", appels=[_appel()], coupee_en_plein_appel=True),
            Reponse(appels=[_appel()]),
            Reponse(texte="fini"),
        ])
        texte, appeles = _lance(adaptateur, [outil], max_tokens=1000)

        assert adaptateur.plafonds == [1000, 2000, 2000]
        assert (texte, appeles) == ("fini", ["lire"])
        # Le texte de l'essai tronqué n'est pas gardé.
        assert "je vais" not in texte

    def test_tronquee_deux_fois_finit_par_le_dire(self):
        outil = _Outil()
        adaptateur = _Adaptateur([
            Reponse(texte="je vais", appels=[_appel()], coupee_en_plein_appel=True),
            Reponse(texte="je vais encore", appels=[_appel()], coupee_en_plein_appel=True),
        ])
        texte, appeles = _lance(adaptateur, [outil], max_tokens=1000)

        assert appeles == [] and outil.calls == []
        assert len(adaptateur.plafonds) == 2
        assert texte == "je vais encore\n\n" + TRUNCATED_TOOL_CALL_MARKER

    def test_au_plafond_pas_de_second_essai(self):
        adaptateur = _Adaptateur([
            Reponse(appels=[_appel()], coupee_en_plein_appel=True),
        ])
        texte, _ = _lance(adaptateur, [_Outil()], max_tokens=TOOL_CALL_CAP_CEILING)
        assert adaptateur.plafonds == [TOOL_CALL_CAP_CEILING]
        assert TRUNCATED_TOOL_CALL_MARKER in texte

    def test_le_doublement_s_arrete_au_plafond(self):
        adaptateur = _Adaptateur([
            Reponse(appels=[_appel()], coupee_en_plein_appel=True),
            Reponse(texte="ok"),
        ])
        _lance(adaptateur, [_Outil()], max_tokens=TOOL_CALL_CAP_CEILING - 1)
        assert adaptateur.plafonds[1] == TOOL_CALL_CAP_CEILING

    def test_une_reponse_longue_sans_appel_n_est_pas_rejouee(self):
        adaptateur = _Adaptateur([Reponse(texte="long...", terminee=True)])
        texte, _ = _lance(adaptateur, [_Outil()])
        assert texte == "long..." and adaptateur.plafonds == [1000]


class TestIssuesDesHandlers:
    """Aucune issue ne lève : toutes reviennent au modèle, et seule une
    invocation réelle compte comme un outil appelé."""

    def _issue(self, tools, appel) -> tuple[Issue, list[str]]:
        adaptateur = _Adaptateur([Reponse(appels=[appel]), Reponse(texte="ok")])
        texte, appeles = _lance(adaptateur, tools)
        assert texte == "ok"
        [[issue]] = adaptateur.issues
        return issue, appeles

    def test_un_handler_qui_leve_devient_une_issue_en_echec(self):
        issue, appeles = self._issue([_Outil("t", raises=RuntimeError("boom"))], _appel("t"))
        assert issue.genre == "exception"
        assert issue.erreur == "boom" and issue.en_echec()
        # Le handler a été invoqué : l'outil compte comme appelé.
        assert appeles == ["t"]

    def test_un_outil_inconnu_n_est_pas_appele(self):
        issue, appeles = self._issue([_Outil("lire")], _appel("fantome"))
        assert issue.genre == "inconnu"
        assert issue.erreur == "unknown tool 'fantome'" and issue.en_echec()
        assert appeles == []

    def test_des_arguments_illisibles_ne_sont_pas_un_appel(self):
        outil = _Outil("lire")
        issue, appeles = self._issue([outil], _appel("lire", arguments="{pas du json"))
        assert issue.genre == "arguments"
        assert issue.erreur.startswith("invalid JSON arguments")
        assert outil.calls == [] and appeles == []

    def test_un_echec_mcp_est_en_echec_sans_avoir_leve(self):
        issue, appeles = self._issue(
            [_Outil("t", result={"content": [], "isError": True})], _appel("t"),
        )
        assert issue.genre == "ok" and issue.erreur is None
        assert issue.en_echec() and appeles == ["t"]

    def test_contenu_json_serialise_l_erreur_et_le_resultat(self):
        assert contenu_json(Issue(_appel(), genre="inconnu", erreur="unknown tool 'x'")) == (
            json.dumps({"error": "unknown tool 'x'"})
        )
        assert contenu_json(Issue(_appel(), resultat={"ok": True})) == '{"ok": true}'
        # Un résultat non sérialisable ne tue pas le tour.
        circulaire: dict = {}
        circulaire["moi"] = circulaire
        assert json.loads(contenu_json(Issue(_appel(), resultat=circulaire)))["result"]


class TestMemoDeParametres:
    """Le mémo vit dans la requête (``create_chat_completion``), et
    l'adaptateur OpenAI le porte : un refus au premier tour n'est pas
    re-payé à chaque itération."""

    def test_un_refus_memorise_vaut_pour_toutes_les_iterations(self):
        import httpx
        from openai import BadRequestError

        from ai.providers._openai_tools import AdaptateurOpenAI, ParamMemo

        def _refus():
            resp = httpx.Response(400, request=httpx.Request("POST", "http://test"))
            return BadRequestError(
                "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead.",
                response=resp, body=None,
            )

        def _reponse(text="", tool_calls=None):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content=text, tool_calls=tool_calls or [],
                ))],
                usage=None,
            )

        appel = SimpleNamespace(
            id="c1", function=SimpleNamespace(name="lire", arguments="{}"),
        )
        file = [_refus(), _reponse("", [appel]), _reponse("", [appel]), _reponse("fini")]
        requetes: list[dict] = []

        async def create(**kwargs):
            requetes.append(kwargs)
            item = file.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        adaptateur = AdaptateurOpenAI(
            client, ParamMemo(), label="OpenAI",
            messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
            model="o3", tools=[_Outil("lire")], temperature=0.7,
        )
        texte, appeles = _lance(adaptateur, [_Outil("lire")], max_tokens=64)

        assert (texte, appeles) == ("fini", ["lire", "lire"])
        assert [("max_completion_tokens" in r) for r in requetes] == [False, True, True, True]


class TestClotureEtRepli:

    def test_clore_est_appele_meme_quand_la_requete_leve(self):
        adaptateur = _Adaptateur([], echec_appel=RuntimeError("réseau"))
        with pytest.raises(RuntimeError):
            _lance(adaptateur, [_Outil()])
        assert adaptateur.clos == 1

    def test_clore_est_appele_a_l_annulation(self):
        """Une boucle annulée à l'itération six compte ses six itérations :
        le relevé d'usage passe par ``clore``, dans un ``finally``."""
        adaptateur = _Adaptateur([], echec_appel=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            _lance(adaptateur, [_Outil()])
        assert adaptateur.clos == 1

    def test_clore_une_seule_fois_en_succes(self):
        adaptateur = _Adaptateur([Reponse(texte="ok")])
        _lance(adaptateur, [])
        assert adaptateur.clos == 1

    def test_max_turns_epuise_sans_texte_rend_le_marqueur(self):
        adaptateur = _Adaptateur([Reponse(appels=[_appel()]) for _ in range(3)])
        texte, appeles = _lance(adaptateur, [_Outil()], max_turns=3)
        assert texte == MAX_TURNS_MARKER
        assert appeles == ["lire"] * 3
        assert len(adaptateur.plafonds) == 3

    def test_max_turns_epuise_avec_du_texte_le_garde(self):
        adaptateur = _Adaptateur([Reponse(texte="j'avance", appels=[_appel()]) for _ in range(2)])
        texte, _ = _lance(adaptateur, [_Outil()], max_turns=2)
        assert texte == "j'avance\n\nj'avance"

    def test_sans_outil_un_seul_appel(self):
        adaptateur = _Adaptateur([Reponse(texte="coucou")])
        assert _lance(adaptateur, []) == ("coucou", [])
        assert adaptateur.plafonds == [1000]


# =================================================================
# (c) Le routeur et le Protocol
# =================================================================

class TestRouteurEtProtocol:

    def test_le_routeur_ne_sonde_plus_de_capacite(self):
        tree = ast.parse((_BACKEND / "ai" / "router.py").read_text(encoding="utf-8"))
        sondes = [
            n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "hasattr"
        ]
        assert sondes == []

    def test_le_routeur_appelle_la_forme_structuree(self):
        tree = ast.parse((_BACKEND / "ai" / "router.py").read_text(encoding="utf-8"))
        attendus = {"chat": "complete_chat", "chat_with_tools": "complete_chat_with_tools"}
        for methode, cible in attendus.items():
            fonction = next(
                f for f in ast.walk(tree)
                if isinstance(f, ast.AsyncFunctionDef) and f.name == methode
            )
            attributs = {
                n.attr for n in ast.walk(fonction) if isinstance(n, ast.Attribute)
            }
            assert cible in attributs, (methode, attributs)
            # Et jamais l'ancienne forme à deux chaînes.
            assert "complete_with_tools" not in attributs

    def test_un_seul_protocol_dans_le_paquet(self):
        tree = ast.parse((_PROVIDERS / "__init__.py").read_text(encoding="utf-8"))
        protocols = [
            c.name for c in ast.walk(tree)
            if isinstance(c, ast.ClassDef)
            and any(ast.unparse(b) == "Protocol" for b in c.bases)
        ]
        assert protocols == ["AIProvider"]

    def test_le_protocol_est_verifiable_a_l_execution(self):
        from ai.providers import AIProvider

        class _Complet:
            async def complete(self, *a, **k): return ""
            async def complete_chat(self, *a, **k): return ""
            async def complete_chat_with_tools(self, *a, **k): return "", []
            async def list_models(self): return []
            async def test(self): return {"ok": True, "model_count": 0}

        class _SansOutils:
            async def complete(self, *a, **k): return ""
            async def complete_chat(self, *a, **k): return ""
            async def list_models(self): return []
            async def test(self): return {"ok": True, "model_count": 0}

        assert isinstance(_Complet(), AIProvider)
        # Un membre absent invalide le provider : plus de capacité optionnelle.
        assert not isinstance(_SansOutils(), AIProvider)
