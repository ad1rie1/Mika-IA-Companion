"""Les réglages : modèles et clés, persona, tempérament et surcharges avancées,
canaux, sens, apps forgées, comptes.

Formulaires POST protégés par jeton ; un secret n'est jamais réaffiché (vide =
inchangé) ; un refus dit pourquoi et ne change rien.
"""

from __future__ import annotations

from typing import Any

import yaml
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.adapters.web.accounts import password_problems
from mika.contracts import forge as forge_c
from mika.contracts import self_ as self_c
from mika.contracts.self_ import PersonaDoc
from mika.inspector.ui import PREFIX, UI
from mika.vocab.affect import FR, Emotion
from mika.vocab.episodes import VOICE_ROLES, Role
from mika.vocab.temperament import Temperament

BAD_TOKEN = ("ko", "Jeton de formulaire invalide : recharge la page.")
SLIDERS = (
    ("reactivity", "Réactivité", "à quel point un mot la touche"),
    ("resilience", "Résilience", "le temps qu'il lui faut pour revenir au calme, pardonner"),
    ("contagion", "Contagion", "ce que ses relations font à son humeur générale"),
    ("optimism", "Optimisme", "la couleur de son repos, ses seuils d'ennui et de détresse"),
    ("sociability", "Sociabilité", "son besoin de compagnie, le rythme de ses relances"),
    ("curiosity", "Curiosité", "son envie d'apprendre, d'explorer"),
    ("perseverance", "Persévérance", "combien elle s'accroche à ce qu'elle entreprend"),
    ("chronotype", "Chronotype", "0 : lève-tôt · 1 : oiseau de nuit"),
)


def _dump(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)


def _ints(text: str) -> list[int]:
    out = []
    for part in text.replace(";", ",").replace("\n", ",").split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return out


def _done(path: str, what: str) -> Response:
    return RedirectResponse(f"{PREFIX}{path}?ok={what}", status_code=303)


def _ok_message(request: Request, labels: dict[str, str]) -> list[tuple[str, str]]:
    key = request.query_params.get("ok", "")
    return [("ok", labels[key])] if key in labels else []


def routes(ui: UI) -> list[Route]:
    kernel = ui.kernel
    deps = ui.deps
    settings = deps.settings

    # ── modèles ──
    async def modeles(request: Request) -> Response:
        cfg: LLMConfig = settings.llm()
        messages = _ok_message(request, {"backend": "Fournisseur enregistré et rechargé.",
                                         "routes": "Rôles enregistrés et rechargés.",
                                         "remove": "Fournisseur retiré."})
        if request.method == "POST":
            data = await ui.form(request)
            if data is None:
                messages = [BAD_TOKEN]
            else:
                backends, model_routes, context = dict(cfg.backends), dict(cfg.routes), cfg.context_tokens
                action = data.get("action")
                try:
                    if action == "backend":
                        name = data["name"].strip()
                        if not name:
                            raise ValueError("Donne un nom au fournisseur.")
                        previous = backends.get(name)
                        key = data.get("api_key") or (previous.api_key if previous else "")
                        kind = data["kind"]
                        backends[name] = BackendSpec(kind=kind, model=data["model"].strip(), api_key=key,
                                                     host=data.get("host", "").strip() if kind.startswith("ollama") else "",
                                                     base_url=data.get("host", "").strip() if kind == "openai" else "",
                                                     slots=int(data.get("slots") or 0))
                    elif action == "remove":
                        name = data.get("name", "")
                        backends.pop(name, None)
                        model_routes = {r: b for r, b in model_routes.items() if b != name}
                    else:
                        action = "routes"
                        model_routes = {r: data[f"route_{r}"] for r in (str(x) for x in Role) if data.get(f"route_{r}")}
                        context = int(data.get("context") or context)
                    await settings.save_llm(LLMConfig(backends=backends, routes=model_routes, context_tokens=context))
                    problems = await deps.reload()
                    if not problems:
                        return _done("/modeles", action)
                    messages = [("ko", p) for p in problems]
                except (ValueError, KeyError) as exc:
                    messages = [("ko", str(exc))]
                cfg = settings.llm()
        return ui.page(request, "models.html", "Modèles", backends=sorted(cfg.backends.items()), routes=cfg.routes,
                       roles=[str(r) for r in Role], voice=sorted(str(r) for r in VOICE_ROLES),
                       context=cfg.context_tokens, messages=messages,
                       kinds=["claude", "openai", "ollama", "ollama_cloud"])

    # ── persona ──
    async def persona(request: Request) -> Response:
        messages = _ok_message(request, {"saved": "Persona enregistrée : une révision est journalisée.",
                                         "file": "Retour au fichier : la persona du fichier fait foi."})
        text = settings.persona_yaml()
        source = "l'inspecteur" if text else "le fichier persona/mika.yaml"
        if request.method == "POST":
            data = await ui.form(request)
            if data is None:
                messages = [BAD_TOKEN]
            elif data.get("action") == "file":
                await settings.save_persona(None)
                problems = await deps.reconfigure() if deps.reconfigure else []
                if not problems:
                    return _done("/persona", "file")
                messages = [("ko", p) for p in problems]
            else:
                text = data.get("persona", "")
                try:
                    doc = PersonaDoc.model_validate(yaml.safe_load(text) or {})
                    await settings.save_persona(_dump(doc.model_dump(mode="json")))
                    problems = await deps.reconfigure() if deps.reconfigure else []
                    if not problems:
                        return _done("/persona", "saved")
                    messages = [("ko", p) for p in problems]
                except yaml.YAMLError as exc:
                    messages = [("ko", f"YAML illisible : {exc}")]
                except ValueError as exc:
                    messages = [("ko", f"Persona refusée : {exc}")]
        if not text:
            text = _dump(kernel.mind.frame().get(self_c.PERSONA).model_dump(mode="json"))
        return ui.page(request, "persona.html", "Persona", text=text, source=source, messages=messages)

    # ── tempérament et surcharges ──
    def current_doc() -> PersonaDoc:
        text = settings.persona_yaml()
        if text:
            try:
                return PersonaDoc.model_validate(yaml.safe_load(text) or {})
            except (ValueError, yaml.YAMLError):
                pass
        return kernel.mind.frame().get(self_c.PERSONA)

    async def parametres(request: Request) -> Response:
        messages = _ok_message(request, {"temperament": "Tempérament enregistré : les paramètres sont re-dérivés.",
                                         "overrides": "Surcharges enregistrées."})
        overrides = settings.overrides()
        drafts: dict[str, str] = {}
        if request.method == "POST":
            data = await ui.form(request)
            if data is None:
                messages = [BAD_TOKEN]
            elif data.get("action") == "temperament":
                doc = current_doc()
                try:
                    values = {k: float(data.get(k, "0.5")) for k, _l, _h in SLIDERS}
                    temperament = Temperament(**values, background=Emotion(data.get("background", "happy")))
                    new = doc.model_copy(update={"temperament": temperament})
                    await settings.save_persona(_dump(new.model_dump(mode="json")))
                    problems = await deps.reconfigure() if deps.reconfigure else []
                    if not problems:
                        return _done("/parametres", "temperament")
                    messages = [("ko", p) for p in problems]
                except ValueError as exc:
                    messages = [("ko", f"Tempérament refusé : {exc}")]
            elif data.get("action") == "overrides":
                owner = data.get("faculty", "")
                fac = kernel.registry.faculties.get(owner)
                raw = data.get("values", "")
                drafts[owner] = raw
                try:
                    if fac is None or fac.derive is None:
                        raise ValueError("Cette faculté n'a pas de paramètres dérivés.")
                    values = yaml.safe_load(raw) or {}
                    if not isinstance(values, dict):
                        raise ValueError("Attendu : une table « nom: valeur ».")
                    fac.derive(current_doc().temperament, values)  # refuse une clé inconnue ou hors bornes
                    overrides = {**overrides, owner: values}
                    await settings.save_overrides(overrides)
                    problems = await deps.reconfigure() if deps.reconfigure else []
                    if not problems:
                        return _done("/parametres", "overrides")
                    messages = [("ko", p) for p in problems]
                except yaml.YAMLError as exc:
                    messages = [("ko", f"YAML illisible : {exc}")]
                except (ValueError, TypeError) as exc:
                    messages = [("ko", f"Surcharge refusée pour {owner} : {exc}")]
        doc = current_doc()
        frame = kernel.mind.frame()
        faculties = []
        for name, fac in sorted(kernel.registry.faculties.items()):
            if fac.derive is None:
                continue
            params = frame.env.params_of(name, frame.root)
            now = params.model_dump(mode="json") if params is not None else {}
            faculties.append({"name": name, "now": _dump(now),
                              "override": drafts.get(name) or (_dump(overrides[name]) if name in overrides else "")})
        return ui.page(request, "parameters.html", "Paramètres", sliders=[
            (k, label, hint, getattr(doc.temperament, k)) for k, label, hint in SLIDERS],
            background=doc.temperament.background.value,
            emotions=sorted(((e.value, FR[e]) for e in Emotion), key=lambda x: x[1]),
            faculties=faculties, messages=messages)

    # ── canaux ──
    async def canaux(request: Request) -> Response:
        messages = _ok_message(request, {"telegram": "Telegram enregistré ; le robot redémarre."})
        if request.method == "POST":
            data = await ui.form(request)
            if data is None:
                messages = [BAD_TOKEN]
            else:
                try:
                    token = data.get("token", "").strip() or None
                    await settings.save_telegram(token=token, allowed_chats=_ints(data.get("allowed", "")),
                                                 owners=_ints(data.get("owners", "")))
                    if deps.restart_telegram is not None:
                        await deps.restart_telegram()
                    return _done("/canaux", "telegram")
                except ValueError:
                    messages = [("ko", "Les identifiants Telegram sont des nombres, séparés par des virgules.")]
        tg = settings.telegram()
        return ui.page(request, "channels.html", "Canaux", configured=bool(tg["token"]),
                       allowed=", ".join(str(c) for c in tg["allowed_chats"]),
                       owners=", ".join(str(o) for o in tg["owners"]), messages=messages)

    # ── sens ──
    async def sens(request: Request) -> Response:
        messages = _ok_message(request, {"mail": "Boîte aux lettres enregistrée.", "feeds": "Flux enregistrés.",
                                         "stt": "Transcription enregistrée."})
        new_token = ""
        if request.method == "POST":
            data = await ui.form(request)
            action = data.get("action") if data else None
            try:
                if data is None:
                    messages = [BAD_TOKEN]
                elif action == "mail":
                    await settings.save_email(
                        address=data.get("address", "").strip(), imap_host=data.get("imap_host", "").strip(),
                        imap_port=int(data.get("imap_port") or 993), user=data.get("user", "").strip(),
                        password=data.get("password") or None, smtp_host=data.get("smtp_host", "").strip(),
                        smtp_port=int(data.get("smtp_port") or 587),
                        smtp_security=data.get("smtp_security", "starttls"))
                    return _done("/sens", "mail")
                elif action == "feeds":
                    await settings.save_feeds(data.get("feeds", "").splitlines())
                    return _done("/sens", "feeds")
                elif action == "stt":
                    current = settings.stt()
                    await settings.save_stt(data.get("base_url", ""), data.get("api_key") or current["api_key"],
                                            data.get("model", "whisper-1").strip() or "whisper-1")
                    return _done("/sens", "stt")
                elif action == "sensors":
                    new_token = await settings.new_sensors_token()
                    messages = [("ok", "Jeton neuf : l'ancien ne vaut plus. Il n'est montré qu'une fois.")]
            except ValueError as exc:
                messages = [("ko", f"Refusé : {exc}")]
        mail = settings.email()
        stt = settings.stt()
        return ui.page(request, "senses.html", "Sens", mail=mail, has_password=bool(mail.password),
                       feeds="\n".join(settings.feeds()), stt_url=stt["base_url"], stt_model=stt["model"],
                       stt_key=bool(stt["api_key"]), sensors=bool(settings.sensors_token()), new_token=new_token,
                       messages=messages)

    # ── apps forgées ──
    async def forge(request: Request) -> Response:
        messages = _ok_message(request, {"config": "Réglages de l'app enregistrés (lus au prochain appel).",
                                         "switch": "Décision enregistrée."})
        port = kernel.ports.get("forge")
        if request.method == "POST":
            data = await ui.form(request)
            app = (data or {}).get("app", "")
            known = port is not None and port.info(app) is not None
            if data is None:
                messages = [BAD_TOKEN]
            elif not known:
                messages = [("ko", "App inconnue.")]
            elif data.get("action") == "switch" and deps.forge_switch is not None:
                state = data.get("state", "")
                if state not in ("enabled", "disabled", "promoted", "demoted"):
                    messages = [("ko", "Décision inconnue.")]
                else:
                    await deps.forge_switch(app, state)
                    return _done("/forge", "switch")
            elif data.get("action") == "config":
                info = port.info(app)
                defaults = dict(getattr(info, "config", ()) or ())
                values: dict[str, Any] = {}
                for key, default in defaults.items():
                    raw = data.get(f"cfg_{key}")
                    if raw is None or raw == "":
                        continue
                    try:
                        values[key] = (raw == "on") if isinstance(default, bool) else type(default)(raw)
                    except ValueError:
                        messages = [("ko", f"« {key} » attend une valeur du type {type(default).__name__}.")]
                        break
                else:
                    await settings.save_forge_config(app, values)
                    return _done("/forge", "config")
        views = {a.name: a for a in kernel.mind.frame().get(forge_c.APPS)}
        apps = []
        for info in (port.apps() if port is not None else []):
            overrides = settings.forge_config(info.name)
            defaults = dict(getattr(info, "config", ()) or ())
            apps.append({"info": info, "view": views.get(info.name), "config": [
                (k, v, overrides.get(k, ""), isinstance(v, bool)) for k, v in defaults.items()]})
        return ui.page(request, "forge.html", "Apps forgées", apps=apps, available=port is not None,
                       messages=messages)

    # ── comptes ──
    async def comptes(request: Request) -> Response:
        messages = _ok_message(request, {"created": "Compte créé.", "updated": "Compte modifié."})
        if request.method == "POST":
            data = await ui.form(request)
            if data is None:
                messages = [BAD_TOKEN]
            elif data.get("action") == "create":
                username, password = data.get("username", "").strip(), data.get("password", "")
                problems = password_problems(password, username)
                if not username:
                    problems.insert(0, "Donne un identifiant.")
                elif deps.accounts.by_name(username) is not None:
                    problems.insert(0, "Cet identifiant existe déjà.")
                if problems:
                    messages = [("ko", p) for p in problems]
                else:
                    await deps.accounts.create(username, password, operator=data.get("operator") == "on",
                                               full_name=data.get("full_name", "").strip())
                    return _done("/comptes", "created")
            else:
                try:
                    account_id = int(data.get("account", "0"))
                except ValueError:
                    account_id = 0
                refused = await deps.accounts.update(
                    account_id, operator=data.get("operator") == "on", active=data.get("active") == "on",
                    password=data.get("password") or None)
                if refused:
                    messages = [("ko", refused)]
                else:
                    return _done("/comptes", "updated")
        return ui.page(request, "accounts.html", "Comptes", accounts=deps.accounts.all(), messages=messages)

    return [
        Route(PREFIX + "/modeles", ui.guarded(modeles), methods=["GET", "POST"]),
        Route(PREFIX + "/persona", ui.guarded(persona), methods=["GET", "POST"]),
        Route(PREFIX + "/parametres", ui.guarded(parametres), methods=["GET", "POST"]),
        Route(PREFIX + "/canaux", ui.guarded(canaux), methods=["GET", "POST"]),
        Route(PREFIX + "/sens", ui.guarded(sens), methods=["GET", "POST"]),
        Route(PREFIX + "/forge", ui.guarded(forge), methods=["GET", "POST"]),
        Route(PREFIX + "/comptes", ui.guarded(comptes), methods=["GET", "POST"]),
    ]

