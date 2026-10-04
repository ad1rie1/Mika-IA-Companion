"""Outils MCP de la Forge — l'interface de Mika pour gérer ses modules.

Six outils : lister, lire (code+manifest+logs), écrire (créer/mettre à
jour, validation + archivage + hot reload), commander (enable/disable/
reload/rollback/erase/reset_storage), tester un handler, lire les logs.

Le contrat d'écriture d'un module est documenté dans la description de
``forge_write_module`` — c'est la seule « doc » que Mika voit en
permanence, elle doit suffire à écrire un module valide du premier coup.
"""

from __future__ import annotations

import json

import yaml
from asgiref.sync import sync_to_async

from old.backend.modules.types import ModuleTool, ToolParameter, ToolParameterType

WRITE_CONTRACT = """Crée ou met à jour un de TES modules forgés (espace sandboxé, hot-reload immédiat, version précédente archivée — rollback possible).

CONTRAT DU CODE (module.py) — fonctions top-level optionnelles, toutes synchrones:
  def on_start(api): ...                # au chargement
  def on_tick(api): ...                 # selon 'schedule'
  def on_event(api, event): ...         # event = {type, source, data} selon 'events'
  def get_context(api): return "..."    # injecté dans ton propre prompt (si context=true)
  def view_<key>(api, params): return {"version": 2, "blocks": [...]}
  def action_<vue>_<action>(api, data): return {"ok": True, "message": "Enregistré"}

INTERFACE v2 (un seul contrat, pas de HTML/JS/template):
- prose/code/note: {type, title, text, tone?}; stats: {type:"stats", items:[{label,value,sub?,tone?}]}
- fields: {type:"fields", title, items:[{label,value}]}; value peut être une cellule {kind:"badge"|"link"|"meter"|"num"|"bool"|"emotion"|"text",text,href?,ratio?,tone?}.
- grid/section/disclosure: {type,items:[blocs],columns?:2,title?,description?,open?}.
- timeline: {type:"timeline",items:[{title,text,meta?,tone?}]}.
- table: {type:"table",columns:[{key,label}],rows:[{cells:{clé:valeur},detail?:bloc,href?}],pagination?:{page,per_page,total,param?:"page"},filters?:[{key,label,kind:"search"|"select",choices?:[{value,label}]}]}.
- form: {type:"form",action:"clé déclarée",initial:{champ:valeur},title?} pour agir depuis une fiche/ligne.
Pagination: params['page'] commence à 1, params['per_page'] vaut 25 par défaut (max 200); renvoie seulement cette tranche. Les filtres sont dans params; ton handler filtre et trie les données.
Pour plusieurs tableaux, déclare page_params:["p_logs","p_notes"] sur la vue du manifeste et utilise pagination.param sur chaque tableau. Ces paramètres arrivent en entiers >=1, défaut 1 (y compris si la saisie est invalide). Les paramètres non déclarés restent des chaînes.
Déclare les actions dans views: [{key:"liste",label:"Liste",description:"...",actions:[{key:"ajouter",label:"Ajouter",fields:[{key:"titre",type:"text",required:true}],confirm?:"...",danger?:true}]}].
Champs: text, textarea, integer, number, boolean, select (choices), email, url, hidden; minimum, maximum, max_length, initial, help. Les actions sont POST+CSRF; data contient seulement les champs déclarés et validés. Par défaut required:false pour boolean (décoché = false), true pour les autres types. required:true exige de cocher une case.
Une action renvoie ok/message (500 caractères affichés au plus); jamais du HTML. Les liens sont HTTP(S) ou chemins /, ? et #. Au plus 200 blocs, 200 lignes/table, 8 niveaux. Schéma: /gestion/api/panneaux/schema.

L'objet api: api.storage.set/get/delete/find/keys/count/clear(collection, ...) (BDD clé-valeur JSON, quotas),
api.config.get(key) / api.config.rows(key) (valeurs éditées par l'utilisateur dans le dashboard),
api.log/warn/error(msg), api.notify_ai(summary, details, urgency) (rate-limité),
api.emit(event_type, data) (bus: 'forge.<module>.<event_type>'), api.http_get(url) (domaines de allowed_domains uniquement),
api.state (dict RAM), api.now(), print() → journal.

INTERDIT (validé à l'écriture): import (math/json/re/datetime/random/statistics/collections/itertools/functools/hashlib/base64/uuid/copy/string sont déjà dispo), async, attributs préfixés '_', eval/exec/open/getattr/setattr/type, .format (utilise les f-strings).

Un handler a ~10s max. 5 échecs consécutifs = disjoncteur (module auto-désactivé, tu es prévenue).
Itère: forge_test_module pour exécuter un handler tout de suite et voir logs+résultat."""


from old.backend.utils.tool_results import texte as _text


def _parse_json_list(value, what: str) -> tuple[list | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None, f"{what} doit être un tableau JSON"
    if not isinstance(value, list):
        return None, f"{what} doit être un tableau"
    return value, None


def build_tools(host) -> list[ModuleTool]:

    async def list_modules(args: dict) -> dict:
        infos = await sync_to_async(host.module_infos,
                                    thread_sensitive=False)()
        if not infos:
            return _text("Aucun module forgé. Crée-en un avec forge_write_module.")
        lines = []
        for i in infos:
            line = f"- {i['name']} [{i['status']}]"
            if i.get("title") and i["title"] != i["name"]:
                line += f" « {i['title']} »"
            if i.get("schedule"):
                line += f" schedule={i['schedule']}"
            if i.get("events"):
                line += f" events={','.join(i['events'])}"
            if i.get("failures"):
                line += f" échecs={i['failures']}"
            if i.get("status_detail"):
                line += f"\n    ⚠ {i['status_detail'][:200]}"
            lines.append(line)
        return _text("\n".join(lines))

    async def read_module(args: dict) -> dict:
        from old.backend.modules.plugins.forge import store
        name = str(args.get("name") or "")
        try:
            data = await sync_to_async(store.read_module,
                                       thread_sensitive=False)(name)
        except store.StoreError as exc:
            return _text(f"Erreur: {exc}", erreur=True)
        manifest_yaml = yaml.safe_dump(
            data["manifest_raw"], allow_unicode=True, sort_keys=False,
        )
        logs = await sync_to_async(host._logs_since_all,
                                   thread_sensitive=False)(name, 15)
        state = data["state"]
        state_txt = ("activé" if state.get("enabled", True)
                     else f"DÉSACTIVÉ ({state.get('disabled_reason')})")
        return _text(
            f"=== {name} ({state_txt}) ===\n"
            f"--- manifest.yaml ---\n{manifest_yaml}\n"
            f"--- module.py ---\n{data['code']}\n"
            f"--- derniers logs ---\n" + ("\n".join(logs) or "(vide)")
        )

    async def write_module(args: dict) -> dict:
        name = str(args.get("name") or "").strip()
        patch: dict = {}
        for key in ("title", "description", "schedule"):
            if args.get(key) is not None:
                patch[key] = str(args[key])
        for key in ("events", "views", "config", "allowed_domains"):
            value, error = _parse_json_list(args.get(key), key)
            if error:
                return _text(f"Erreur: {error}", erreur=True)
            if value is not None:
                patch[key] = value
        if args.get("context_enabled") is not None:
            patch["context"] = bool(args["context_enabled"])

        result = await host.write_module(
            name,
            code=args.get("code"),
            manifest_patch=patch,
            reason=str(args.get("reason") or ""),
        )
        if not result["ok"]:
            return _text(
                "Refusé — corrige et renvoie:\n- "
                + "\n- ".join(result["errors"]), erreur=True
            )
        handlers = ", ".join(result.get("handlers") or []) or "aucun handler détecté"
        note = f"\n{result['note']}" if result.get("note") else ""
        return _text(
            f"OK — {name} v{result['version']} écrite et rechargée.\n"
            f"Handlers actifs: {handlers}{note}\n"
            "Astuce: forge_test_module pour vérifier tout de suite."
        )

    async def command(args: dict) -> dict:
        name = str(args.get("name") or "")
        cmd = str(args.get("command") or "")
        result = await host.command(name, cmd)
        prefix = "OK — " if result["ok"] else "Échec — "
        return _text(prefix + result["message"], erreur=not result["ok"])

    async def test_module(args: dict) -> dict:
        name = str(args.get("name") or "")
        handler = str(args.get("handler") or "on_tick")
        payload = None
        raw = args.get("payload")
        if raw:
            try:
                payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except (ValueError, TypeError):
                return _text("Erreur: payload doit être un objet JSON", erreur=True)
        result = await host.test_module(name, handler, payload)
        lines = [f"test {name}.{handler}: "
                 + ("SUCCÈS" if result["ok"] else "ÉCHEC")]
        if result.get("error"):
            lines.append(f"Erreur:\n{result['error']}")
        if "result" in result:
            preview = json.dumps(result["result"], ensure_ascii=False,
                                 default=str)
            lines.append(f"Résultat: {preview[:1500]}")
        logs = result.get("logs") or []
        if logs:
            lines.append("Logs produits:\n" + "\n".join(logs))
        return _text("\n".join(lines), erreur=not result["ok"])

    async def read_logs(args: dict) -> dict:
        name = str(args.get("name") or "") or None
        limit = min(int(args.get("limit") or 30), 100)
        logs = await sync_to_async(host._logs_since_all,
                                   thread_sensitive=False)(name, limit)
        return _text("\n".join(logs) or "(journal vide)")

    return [
        ModuleTool(
            name="forge_list_modules",
            description=(
                "Liste tes modules forgés (mini-modules que TU as créés) "
                "avec leur statut: actif / désactivé / cassé, schedule, "
                "abonnements, échecs."
            ),
            parameters=[],
            handler=list_modules,
        ),
        ModuleTool(
            name="forge_read_module",
            description=(
                "Lit un module forgé en entier: manifest.yaml, code "
                "module.py, état, derniers logs. Toujours lire avant de "
                "modifier."
            ),
            parameters=[
                ToolParameter(name="name", type=ToolParameterType.STRING,
                              description="Nom (slug) du module"),
            ],
            handler=read_module,
        ),
        ModuleTool(
            name="forge_write_module",
            description=WRITE_CONTRACT,
            parameters=[
                ToolParameter(
                    name="name", type=ToolParameterType.STRING,
                    description="Slug du module (minuscules/chiffres/_, "
                                "3-32 car.) — ex: veille_meteo",
                ),
                ToolParameter(
                    name="code", type=ToolParameterType.STRING,
                    description="Contenu complet de module.py (requis à la "
                                "création; omis = code conservé)",
                    required=False,
                ),
                ToolParameter(
                    name="title", type=ToolParameterType.STRING,
                    description="Titre lisible (requis à la création)",
                    required=False,
                ),
                ToolParameter(
                    name="description", type=ToolParameterType.STRING,
                    description="Ce que fait le module, pour toi plus tard",
                    required=False,
                ),
                ToolParameter(
                    name="schedule", type=ToolParameterType.STRING,
                    description="'' | manual | interval:30s/5m/2h | idle:15m "
                                "| cron:0 9 * * MON-FRI — déclenche on_tick",
                    required=False,
                ),
                ToolParameter(
                    name="events", type=ToolParameterType.ARRAY,
                    description="Motifs d'événements écoutés par on_event — "
                                "ex: [\"rss.new_entry\", \"chat.*\", "
                                "\"forge.autre_module.*\"]",
                    required=False,
                ),
                ToolParameter(
                    name="views", type=ToolParameterType.ARRAY,
                    description="Pages dashboard: [{key, label, icon?}] — "
                                "chaque key exige une fonction "
                                "view_<key>(api, params) dans le code",
                    required=False,
                ),
                ToolParameter(
                    name="config", type=ToolParameterType.ARRAY,
                    description="Champs de config éditables par l'utilisateur "
                                "dans le dashboard: [{key, label, type: "
                                "str|text|int|float|bool|secret|select|list|"
                                "record_list, default?, choices?, fields? "
                                "(pour record_list), sensitive?}] — lus via "
                                "api.config.get(key)",
                    required=False,
                ),
                ToolParameter(
                    name="allowed_domains", type=ToolParameterType.ARRAY,
                    description="Hôtes autorisés pour api.http_get — ex: "
                                "[\"wttr.in\"]",
                    required=False,
                ),
                ToolParameter(
                    name="context_enabled", type=ToolParameterType.BOOLEAN,
                    description="true pour injecter get_context(api) dans "
                                "ton prompt système",
                    required=False,
                ),
                ToolParameter(
                    name="reason", type=ToolParameterType.STRING,
                    description="Pourquoi cette écriture (journalisé)",
                    required=False,
                ),
            ],
            handler=write_module,
        ),
        ModuleTool(
            name="forge_command",
            description=(
                "Commande de gestion d'un module forgé: enable (réactive + "
                "recharge), disable (stoppe, garde tout), reload (recharge "
                "depuis le disque), rollback (restaure la version "
                "précédente), erase (efface — archivé dans _trash, stockage "
                "et journal supprimés), reset_storage (vide les données). "
                "À utiliser "
                "sans hésiter si un module te bloque."
            ),
            parameters=[
                ToolParameter(name="name", type=ToolParameterType.STRING,
                              description="Nom du module"),
                ToolParameter(
                    name="command", type=ToolParameterType.STRING,
                    description="Commande",
                    enum=["enable", "disable", "reload", "rollback",
                          "erase", "reset_storage"],
                ),
            ],
            handler=command,
        ),
        ModuleTool(
            name="forge_test_module",
            description=(
                "Exécute un handler d'un module forgé MAINTENANT (sans "
                "attendre le schedule, sans compter d'échec) et retourne "
                "résultat + logs. Parfait pour itérer après "
                "forge_write_module."
            ),
            parameters=[
                ToolParameter(name="name", type=ToolParameterType.STRING,
                              description="Nom du module"),
                ToolParameter(
                    name="handler", type=ToolParameterType.STRING,
                    description="Handler à lancer (défaut: on_tick) — ex: "
                                "on_start, on_event, get_context, view_stats",
                    required=False,
                ),
                ToolParameter(
                    name="payload", type=ToolParameterType.STRING,
                    description="JSON optionnel: data de l'événement pour "
                                "on_event, params pour view_*",
                    required=False,
                ),
            ],
            handler=test_module,
        ),
        ModuleTool(
            name="forge_read_logs",
            description="Journal des modules forgés (erreurs, prints, "
                        "événements système). Sans nom: tous les modules.",
            parameters=[
                ToolParameter(name="name", type=ToolParameterType.STRING,
                              description="Filtrer sur un module",
                              required=False),
                ToolParameter(name="limit", type=ToolParameterType.INTEGER,
                              description="Nb de lignes (défaut 30, max 100)",
                              required=False),
            ],
            handler=read_logs,
        ),
    ]
