"""Le processus d'une app forgée (exécuté dans le bac à sable, bibliothèque
standard seulement ; jamais importé par Mika).

Protocole, une ligne JSON par message : l'hôte envoie ``{"call": méthode,
"args": {...}}`` ; l'app peut demander un service (``{"host": nom,
"params": {...}}``, réponse ``{"result": …}`` ou ``{"error": …}``) ; elle
conclut par ``{"result": …}`` ou ``{"error": …}``. ``print`` va au journal.
"""

import json
import sys
import traceback
import types

OUT = sys.stdout
IN = sys.stdin


def send(obj):
    OUT.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    OUT.flush()


def host(name, **params):
    send({"host": name, "params": params})
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

    def config(self, key, default=None):
        return host("config", key=key, default=default)

    def log(self, *parts):
        host("log", message=" ".join(str(p) for p in parts))

    def emit(self, type, data=None):
        host("emit", type=str(type), data=data)

    def signal(self, summary, pertinence=0.3, emotion=""):
        host("signal", summary=str(summary), pertinence=float(pertinence), emotion=str(emotion))

    def http_get(self, url):
        return host("http_get", url=str(url))


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


def main():
    api = Api()
    sys.stdout = Printer(api)
    module = types.ModuleType("app")
    module.__dict__["api"] = api
    try:
        with open("/app/main.py", encoding="utf-8") as f:
            code = f.read()
        exec(compile(code, "main.py", "exec"), module.__dict__)  # noqa: S102 — c'est le bac à sable
    except BaseException as exc:  # noqa: BLE001 — l'erreur de chargement est rendue à l'hôte
        send({"loaded": False, "error": f"{type(exc).__name__}: {exc}"[:2000]})
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
            if method == "action":
                value = fn(api, str(args.get("name") or ""), args.get("args") or {})
            elif method.startswith("tool_") or method == "on_event":
                value = fn(api, args)
            else:
                value = fn(api)
            send({"result": value})
        except BaseException as exc:  # noqa: BLE001 — y compris MemoryError : l'hôte décide
            send({"error": f"{type(exc).__name__}: {exc}"[:1000], "trace": traceback.format_exc()[-2000:]})


if __name__ == "__main__":
    main()
