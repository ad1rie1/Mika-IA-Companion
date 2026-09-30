"""Une fausse CLI ``claude -p`` : même drapeaux, même stream-json, vrai client MCP HTTP.

Le scénario voyage dans le prompt système (l'environnement du sous-processus
est filtré par l'adaptateur) : une ligne ``SCENARIO: {json}``. Clés :

- ``calls`` : liste de lots ; chaque lot, des ``[serveur, outil, arguments]``
  appelés en parallèle ;
- ``say`` : le texte final (``{results}`` y reçoit les résultats des outils) ;
- ``fail`` : terminer par un résultat en erreur portant ce texte ;
- ``sleep`` : rester bloqué N secondes avant de répondre (annulation) ;
- ``quota`` : l'utilisation d'abonnement annoncée (``rate_limit_event``) ;
- ``report`` : ajouter au texte final ce que la CLI a reçu (argv, clés
  d'environnement, outils de chaque serveur).

Comme la vraie CLI, un serveur MCP injoignable est annoncé « failed » dans
``init`` (``mcp_servers``) et la session continue sans lui.
"""

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def out(obj):
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
    listed, states = {}, []
    for name, server in servers.items():
        # comme la vraie CLI : un serveur qu'elle ne joint pas est « failed », et elle continue sans lui
        try:
            rpc(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "fake", "version": "0"}})
            rpc(server, "notifications/initialized", mid=None)
            listed[name] = [t["name"] for t in rpc(server, "tools/list")["result"]["tools"]]
            states.append({"name": name, "status": "connected"})
        except (OSError, ValueError, KeyError):
            states.append({"name": name, "status": "failed"})
    out({"type": "system", "subtype": "init", "tools": [f"mcp__{s}__{t}" for s, ts in listed.items() for t in ts],
         "mcp_servers": states, "apiKeySource": "none"})
    if "quota" in scenario:
        out({"type": "rate_limit_event", "rate_limit_info": {
            "status": "allowed", "unifiedWindows": {"five_hour": {"utilization": scenario["quota"], "resetsAt": 1}}}})
    if scenario.get("sleep"):
        time.sleep(scenario["sleep"])
    results = []
    for batch in ([] if len(listed) < len(servers) else scenario.get("calls", [])):  # sans ses outils : rien à appeler
        out({"type": "assistant", "message": {"model": "fake-cc", "content": [{"type": "text", "text": "Je regarde."}]}})
        with ThreadPoolExecutor(len(batch)) as pool:
            replies = list(pool.map(
                lambda c: rpc(servers[c[0]], "tools/call", {"name": c[1], "arguments": c[2]}), batch))
        for (server, tool, _args), reply in zip(batch, replies):
            res = reply["result"]
            text = "".join(b.get("text", "") for b in res["content"])
            results.append(("ERREUR:" if res.get("isError") else "") + f"{tool}={text}")
    if scenario.get("fail"):
        out({"type": "result", "subtype": "success", "is_error": True, "result": scenario["fail"]})
        return 1
    text = scenario.get("say", "fini").replace("{results}", " | ".join(results))
    if scenario.get("report"):
        text += "\nREPORT " + json.dumps({"argv": sys.argv[1:], "env": sorted(os.environ), "listed": listed,
                                         "user": user["message"]["content"][-1]["text"],
                                         "api_key": os.environ.get("ANTHROPIC_API_KEY", "")})
    out({"type": "assistant", "message": {"model": "fake-cc", "content": [{"type": "text", "text": text}]}})
    out({"type": "result", "subtype": "success", "is_error": False, "result": text, "stop_reason": "end_turn",
         "usage": {"input_tokens": 7, "output_tokens": 3, "cache_read_input_tokens": 100,
                   "cache_creation_input_tokens": 20},
         "modelUsage": {"fake-cc": {}}, "total_cost_usd": 0.01})
    return 0


if __name__ == "__main__":
    sys.exit(main())
