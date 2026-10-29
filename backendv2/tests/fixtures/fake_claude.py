"""Une fausse CLI ``claude -p`` : même drapeaux, même stream-json, vrai client MCP HTTP.

Le scénario voyage dans le prompt système (l'environnement du sous-processus
est filtré par l'adaptateur) : une ligne ``SCENARIO: {json}``. Clés :

- ``calls`` : liste de lots ; chaque lot, les ``[serveur, outil, arguments]``
  qu'un même message du modèle écrit, avec en quatrième place, au besoin,
  ``{"lag": s}`` (la requête au relais part s secondes après le bloc) ou
  ``{"local": true}`` (la CLI répond elle-même, en erreur, sans le relais) ;
- ``gap`` : le temps que le modèle met à écrire chaque bloc d'appel suivant ;
- ``nostream`` : ne pas diffuser le message (une CLI sans ``stream_event``) ;
- ``say`` : le texte final (``{results}`` y reçoit les résultats des outils) ;
- ``before`` : un texte que le modèle écrit d'abord, avant de chercher un outil (``ToolSearch``, que la CLI
  exécute elle-même) et de reprendre dans un second message — ``result`` ne porte que ce second message ;
- ``broken`` : ce que le modèle avait écrit quand son flux a cassé : la CLI le garde en un message, puis le modèle
  reprend dans un second, sans appel d'outil entre eux (« Continue from exactly where the quoted text leaves
  off », 2.1.296) — ``say`` est cette reprise, et ``result`` ne porte qu'elle ;
- ``fail`` : terminer par un résultat en erreur portant ce texte ;
- ``sleep`` : rester bloqué N secondes avant de répondre (annulation) ;
- ``quota`` : l'utilisation d'abonnement annoncée (``rate_limit_event``) ;
- ``resets`` : dans combien de secondes sa fenêtre se réinitialise (négatif :
  déjà passée ; défaut une heure) ;
- ``noise`` : des lignes brutes écrites avant tout le reste (JSON qui n'est
  pas un objet, formes inattendues, ligne géante) ;
- ``die`` : s'arrêter après le bruit, sans résultat (code de sortie donné) ;
- ``report`` : ajouter au texte final ce que la CLI a reçu (argv, clés
  d'environnement, outils de chaque serveur).

Comme la vraie CLI (2.1.282, mesuré) : un serveur MCP injoignable est annoncé
« failed » dans ``init`` (``mcp_servers``) et la session continue sans lui ;
chaque bloc ``tool_use`` sort sur sa propre ligne ``assistant`` ; avec
``--include-partial-messages``, le message est encadré de ``stream_event``
(``message_start`` … ``message_stop``) ; un outil marqué ``readOnlyHint`` part
dès que son bloc est écrit, en parallèle des autres, un outil sans la marque
attend la réponse du précédent.
"""

import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import Future

_WRITING = threading.Lock()


def out(obj):
    with _WRITING:  # les appels d'outils écrivent leur réponse depuis leur fil
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def arg(name):
    argv = sys.argv
    return argv[argv.index(name) + 1] if name in argv else None


def rpc(server, method, params=None, mid=1):
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if mid is not None:
        body["id"] = mid
    req = urllib.request.Request(server["url"], data=json.dumps(body).encode(), method="POST",
                                 headers={**server.get("headers", {}), "content-type": "application/json",
                                          "accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def main():
    system = open(arg("--system-prompt-file"), encoding="utf-8").read()
    scenario = {}
    for line in system.splitlines():
        if line.startswith("SCENARIO: "):
            scenario = json.loads(line[len("SCENARIO: "):])
    user = json.loads(sys.stdin.readline())
    servers = {}
    if arg("--mcp-config"):
        servers = json.load(open(arg("--mcp-config"), encoding="utf-8"))["mcpServers"]
    listed, readonly, states = {}, {}, []
    for name, server in servers.items():
        # comme la vraie CLI : un serveur qu'elle ne joint pas est « failed », et elle continue sans lui
        try:
            rpc(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "fake", "version": "0"}})
            rpc(server, "notifications/initialized", mid=None)
            tools = rpc(server, "tools/list")["result"]["tools"]
            listed[name] = [t["name"] for t in tools]
            readonly[name] = [t["name"] for t in tools if (t.get("annotations") or {}).get("readOnlyHint")]
            states.append({"name": name, "status": "connected"})
        except (OSError, ValueError, KeyError):
            states.append({"name": name, "status": "failed"})
    out({"type": "system", "subtype": "init", "tools": [f"mcp__{s}__{t}" for s, ts in listed.items() for t in ts],
         "mcp_servers": states, "apiKeySource": "none"})
    for raw in scenario.get("noise", []):
        sys.stdout.write((raw if isinstance(raw, str) else json.dumps(raw)) + "\n")
        sys.stdout.flush()
    if "die" in scenario:
        return int(scenario["die"])
    if "quota" in scenario:
        resets = int(time.time() + scenario.get("resets", 3600))
        out({"type": "rate_limit_event", "rate_limit_info": {
            "status": "allowed", "unifiedWindows": {"five_hour": {"utilization": scenario["quota"],
                                                                  "resetsAt": resets}}}})
    if scenario.get("sleep"):
        time.sleep(scenario["sleep"])
    stream = "--include-partial-messages" in sys.argv and not scenario.get("nostream")

    def event(kind, **extra):
        if stream:
            out({"type": "stream_event", "event": {"type": kind, **extra}, "parent_tool_use_id": None})

    def call(c, tid, after=None):
        """Un appel parti du bloc ``c`` : au relais (après ``after``, l'appel précédent, s'il n'est pas en
        lecture seule), ou répondu par la CLI elle-même ; sa réponse sort sur stdout dès qu'elle est là."""
        done = Future()

        def go():
            opts = c[3] if len(c) > 3 else {}
            if after is not None:
                after.result()
            if opts.get("local"):
                res = {"content": [{"type": "text", "text": "refusé par la CLI"}], "isError": True}
            else:
                time.sleep(opts.get("lag", 0))
                res = rpc(servers[c[0]], "tools/call", {"name": c[1], "arguments": c[2]})["result"]
            text = "".join(b.get("text", "") for b in res["content"])
            out({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": bool(res.get("isError"))}]}})
            done.set_result(("ERREUR:" if res.get("isError") else "") + f"{c[1]}={text}")

        threading.Thread(target=go, daemon=True).start()
        return done

    def usage(m, final=False):
        """L'usage d'un message (``usage`` du scénario) : à son début (entrée, cache), puis à sa fin (sortie)."""
        return {"input_tokens": 4 + m, "cache_read_input_tokens": 40} if not final else {"output_tokens": 10 + m}

    results, n, m = [], 0, 0
    for batch in ([] if len(listed) < len(servers) else scenario.get("calls", [])):  # sans ses outils : rien à appeler
        m += 1
        event("message_start", message={"model": "fake-cc", **(
            {"id": f"msg_{m}", "usage": usage(m)} if scenario.get("usage") else {})})
        out({"type": "assistant", "message": {"model": "fake-cc", "content": [{"type": "text", "text": "Je regarde."}]}})
        futures, ids, previous = [], [], None
        for i, c in enumerate(batch):
            if i and scenario.get("gap"):
                time.sleep(scenario["gap"])  # le modèle écrit encore le bloc suivant
            n += 1
            ids.append(f"toolu_{n}")
            out({"type": "assistant", "message": {"model": "fake-cc", "content": [
                {"type": "tool_use", "id": ids[-1], "name": f"mcp__{c[0]}__{c[1]}", "input": c[2]}]}})
            parallel = c[1] in readonly.get(c[0], ())
            futures.append(call(c, ids[-1], after=None if parallel else previous))
            previous = futures[-1]
        event("message_delta", delta={"stop_reason": "tool_use"},
              **({"usage": usage(m, final=True)} if scenario.get("usage") else {}))
        event("message_stop")
        results += [f.result() for f in futures]
    if scenario.get("fail"):
        out({"type": "result", "subtype": "success", "is_error": True, "result": scenario["fail"]})
        return 1
    if scenario.get("before"):  # il écrit, cherche un outil (la CLI répond elle-même), puis reprend
        n += 1
        event("message_start", message={"model": "fake-cc"})
        out({"type": "assistant", "message": {"model": "fake-cc", "content": [
            {"type": "text", "text": scenario["before"]}]}})
        out({"type": "assistant", "message": {"model": "fake-cc", "content": [
            {"type": "tool_use", "id": f"toolu_{n}", "name": "ToolSearch", "input": {"query": "souvenirs"}}]}})
        event("message_delta", delta={"stop_reason": "tool_use"})
        event("message_stop")
        out({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"toolu_{n}", "content": "aucun outil de ce nom"}]}})
    text = scenario.get("say", "fini").replace("{results}", " | ".join(results))
    if scenario.get("report"):
        text += "\nREPORT " + json.dumps({"argv": sys.argv[1:], "env": sorted(os.environ), "listed": listed,
                                         "readonly": readonly,
                                         "user": user["message"]["content"][-1]["text"],
                                         "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
                                         "max_output": os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS", ""),
                                         "flags": {k: os.environ.get(k, "") for k in (
                                             "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CODE_HARBOR_KITE")},
                                         "cwd": os.getcwd()})
    if scenario.get("broken"):  # le flux a cassé : la CLI garde ce qui est écrit, le modèle reprend dans un second message
        event("message_start", message={"model": "fake-cc"})
        out({"type": "assistant", "message": {"model": "fake-cc", "content": [
            {"type": "text", "text": scenario["broken"]}]}})
    m += 1
    event("message_start", message={"model": "fake-cc", **(
        {"id": f"msg_{m}", "usage": usage(m)} if scenario.get("usage") else {})})
    out({"type": "assistant", "message": {"model": "fake-cc", "content": [{"type": "text", "text": text}]}})
    event("message_delta", delta={"stop_reason": "end_turn"},
          **({"usage": usage(m, final=True)} if scenario.get("usage") else {}))
    event("message_stop")
    out({"type": "result", "subtype": "success", "is_error": False, "result": text, "stop_reason": "end_turn",
         "usage": {"input_tokens": 7, "output_tokens": 3, "cache_read_input_tokens": 100,
                   "cache_creation_input_tokens": 20},
         "modelUsage": {"fake-cc": {}}, "total_cost_usd": 0.01})
    return 0


if __name__ == "__main__":
    sys.exit(main())
