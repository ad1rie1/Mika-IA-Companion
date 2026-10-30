"""Le processus d'une app forgée (exécuté dans le bac à sable, bibliothèque
standard seulement ; jamais importé par Mika).

Protocole, une ligne JSON par message : l'hôte envoie ``{"call": méthode,
"args": {...}}`` ; l'app peut demander un service (``{"host": nom,
"params": {...}}``, réponse ``{"result": …}`` ou ``{"error": …}``) ; elle
conclut par ``{"result": …}`` ou ``{"error": …}``. ``print`` va au journal.

``tick(api)``, ``context(api)``, ``view(api)`` ; ``view_<vue>(api, params)``,
``action_<vue>_<action>(api, data)``, ``tool_<nom>(api, args)``,
``on_event(api, événement)`` ; l'ancienne ``action(api, nom, args)``. L'hôte
ne demande que les fonctions déclarées. Sa base (``api.query``,
``api.execute``), c'est l'hôte qui l'interroge pour elle.
"""

import json
import sys
import traceback
import types

OUT = sys.stdout
IN = sys.stdin
#: une ligne envoyée à l'hôte au plus (octets, fin de ligne comprise) : le ``MAX_LINE`` de l'hôte, qui tue au-delà
MAX_LINE = 2_000_000
#: une ligne de journal au plus (caractères) : l'hôte n'en garde pas davantage
LOG_MAX = 1000


def send(obj):
    OUT.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    OUT.flush()


def host(name, **params):
    line = json.dumps({"host": name, "params": params}, ensure_ascii=False, default=str) + "\n"
    size = len(line.encode("utf-8", "replace"))
    if size > MAX_LINE:  # refusée ici, comme un refus de l'hôte : l'app peut la rattraper, son processus survit
        raise RuntimeError(f"{name} : demande trop grosse ({size // 1000} Ko ; au plus {MAX_LINE // 1000} Ko)")
    OUT.write(line)
    OUT.flush()
    line = IN.readline()
    if not line:
        raise SystemExit(0)
    reply = json.loads(line)
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply.get("result")


class Api:
    """Ce que l'hôte lui offre — rien d'autre ne sort du bac à sable."""

    def kv_get(self, key, default=None):
        return host("kv_get", key=key, default=default)

    def kv_set(self, key, value):
        return host("kv_set", key=key, value=value)

    def kv_delete(self, key):
        return host("kv_delete", key=key)

    def kv_keys(self, prefix=""):
        return host("kv_keys", prefix=prefix)

    def query(self, sql, params=None):
        """Lire sa base : une instruction (SELECT, WITH), des paramètres nommés (:nom) ; ses lignes en dictionnaires."""
        return host("sql_query", sql=str(sql), params=dict(params or {}))

    def execute(self, sql, params=None):
        """Écrire dans sa base : une instruction ; {"rows": lignes touchées, "id": identifiant inséré ou None}."""
        return host("sql_execute", sql=str(sql), params=dict(params or {}))

    def config(self, key, default=None):
        return host("config", key=key, default=default)

    def log(self, *parts):
        host("log", message=" ".join(str(p) for p in parts)[:LOG_MAX])

    def emit(self, type, data=None):
        host("emit", type=str(type), data=data)

    def signal(self, summary, pertinence=0.3, emotion=""):
        host("signal", summary=str(summary), pertinence=float(pertinence), emotion=str(emotion))

    def http_get(self, url, headers=None):
        """Le texte d'une page ou d'une API ; une erreur HTTP lève une exception."""
        return host("http_get", url=str(url), headers=dict(headers or {}))

    def http(self, url, method="GET", headers=None, json=None, form=None, body=None, binary=False, timeout=None):
        """Une requête entière : toute méthode, un corps (json, form ou body), ses en-têtes ; rend
        {status, ok, url, headers, text (ou base64 avec binary=True), truncated} — une erreur HTTP est une réponse."""
        return host("http", url=str(url), method=str(method), headers=dict(headers or {}), json=json,
                    form=dict(form) if form is not None else None, body=None if body is None else str(body),
                    binary=bool(binary), timeout=timeout)


class Printer:
    def __init__(self, api):
        self.api = api
        self.buf = ""

    def write(self, text):
        self.buf += text
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.api.log(line)
        return len(text)

    def flush(self):
        pass


#: le code de l'app, ligne par ligne : ce qu'une erreur montre de l'endroit où elle est née
SOURCE: list[str] = []


def where(exc):
    """L'endroit de main.py où l'erreur est née (le plus profond), sa ligne et son code : sans lui, « KeyError:
    'rates' » ne dit pas quoi corriger (ADR 0161)."""
    if isinstance(exc, SyntaxError) and exc.filename == "main.py" and exc.lineno:
        return f" (main.py, ligne {exc.lineno} : {(exc.text or '').strip()[:160]})"
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == "main.py"]
    if not frames:
        return ""
    n = frames[-1].lineno or 0
    line = SOURCE[n - 1].strip() if 0 < n <= len(SOURCE) else ""
    return f" (main.py, ligne {n}{' : ' + line[:160] if line else ''})"


def main():
    api = Api()
    sys.stdout = Printer(api)
    module = types.ModuleType("app")
    module.__dict__["api"] = api
    try:
        with open("/app/main.py", encoding="utf-8") as f:
            code = f.read()
        SOURCE[:] = code.splitlines()
        exec(compile(code, "main.py", "exec"), module.__dict__)  # noqa: S102 — c'est le bac à sable
    except BaseException as exc:  # noqa: BLE001 — l'erreur de chargement est rendue à l'hôte
        send({"loaded": False, "error": f"{type(exc).__name__}: {str(exc)[:1600]}{where(exc)}"[:2000]})
        return
    send({"loaded": True})
    for line in IN:
        try:
            request = json.loads(line)
        except ValueError:
            continue
        method = str(request.get("call") or "")
        fn = getattr(module, method, None)
        if not callable(fn):
            send({"error": f"pas de fonction « {method} » dans main.py"})
            continue
        args = request.get("args") or {}
        try:
            if method == "action":  # l'ancienne forme : action(api, nom, args)
                value = fn(api, str(args.get("name") or ""), args.get("args") or {})
            elif method.startswith(("tool_", "view_", "action_")) or method == "on_event":
                value = fn(api, args)
            else:
                value = fn(api)
            send({"result": value})
        except BaseException as exc:  # noqa: BLE001 — y compris MemoryError : l'hôte décide
            send({"error": f"{type(exc).__name__}: {str(exc)[:700]}{where(exc)}"[:1000],
                  "trace": traceback.format_exc()[-2000:]})


if __name__ == "__main__":
    main()
