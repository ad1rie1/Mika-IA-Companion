"""
Micro-serveur webhook pour déclencher le pipeline AI.

Écoute les webhooks GitHub (issues) et les commandes externes.

Usage:
    AI_PIPELINE_WEBHOOK_SECRET=... python webhook_server.py
    python webhook_server.py --port 9090

Le secret se passe par l'environnement : sur la ligne de commande, il était
lisible par n'importe quel utilisateur de la machine dans `ps`.

Endpoints:
    POST /webhook/github   - Webhook GitHub (signature X-Hub-Signature-256)
    POST /webhook/trigger  - Déclenchement manuel (en-tête X-Pipeline-Secret)
    GET  /health           - Health check
"""
import argparse
import hashlib
import hmac
import json
import logging
import os
import re
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent
ORCHESTRATOR = PIPELINE_DIR / "orchestrator.sh"
PROFILES_DIR = PIPELINE_DIR / "profiles"
LOG_DIR = PIPELINE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Un webhook GitHub pèse quelques dizaines de Ko ; au-delà, on ne lit pas.
MAX_BODY_BYTES = 1_000_000

# L'orchestrateur borne déjà l'agent (AI_AGENT_TIMEOUT, 4 h 20). Ce délai-ci
# n'est qu'un filet au-dessus : l'ancien plafond de 15 min tuait le pipeline
# en pleine tâche, d'un SIGKILL qui ne laissait pas tourner son nettoyage.
PIPELINE_TIMEOUT_S = 5 * 3600
TERM_GRACE_S = 30

# Code de sortie de l'orchestrateur quand une autre instance tient le verrou.
EXIT_BUSY = 75

# Chaque chemin commence par une lettre ou un chiffre : « --dry-run » passé
# comme module deviendrait une option de l'orchestrateur.
MODULE_RE = re.compile(r"^(all|[A-Za-z0-9][A-Za-z0-9_./-]*(,[A-Za-z0-9][A-Za-z0-9_./-]*)*)$")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "webhook.log"),
    ],
)
logger = logging.getLogger("ai-webhook")

# Configuré au démarrage
WEBHOOK_SECRET = ""


def known_profiles(mode: str) -> set[str]:
    """Profils présents sur disque pour un mode (audit, small_fix)."""
    return {p.stem for p in (PROFILES_DIR / mode).glob("*.md")}


def verify_github_signature(payload_body: bytes, signature: str) -> bool:
    """Vérifie la signature HMAC du webhook GitHub."""
    if not WEBHOOK_SECRET:
        return True  # pas de secret configuré = pas de vérification (loopback)

    if not signature or not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        WEBHOOK_SECRET.encode(), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


def verify_trigger_secret(header_value: str) -> bool:
    """Le déclenchement manuel lance un agent qui écrit du code : avec un
    secret configuré, il l'exige comme le webhook GitHub."""
    if not WEBHOOK_SECRET:
        return True
    return hmac.compare_digest(WEBHOOK_SECRET, header_value or "")


def run_pipeline(args: list[str], context: str = "") -> threading.Thread:
    """Lance le pipeline dans un thread séparé.

    L'orchestrateur tourne dans son propre groupe de processus : à
    l'expiration, on envoie SIGTERM au groupe (son trap arrête l'agent et
    remet le worktree à zéro), puis SIGKILL s'il traîne.
    """

    def _run():
        logger.info(f"Pipeline lancé: {' '.join(args)} ({context})")
        try:
            proc = subprocess.Popen(
                [str(ORCHESTRATOR), *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                cwd=str(PIPELINE_DIR.parent.parent),
                start_new_session=True,
            )
        except OSError as e:
            logger.error(f"Pipeline non lancé ({context}): {e}")
            return

        try:
            _, stderr = proc.communicate(timeout=PIPELINE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            logger.error(f"Pipeline au-delà de {PIPELINE_TIMEOUT_S}s ({context}) - arrêt")
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                _, stderr = proc.communicate(timeout=TERM_GRACE_S)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                _, stderr = proc.communicate()

        if proc.returncode in (0, 10, 11):
            logger.info(f"Pipeline terminé (exit {proc.returncode}) ({context})")
        elif proc.returncode == EXIT_BUSY:
            logger.warning(f"Pipeline déjà occupé - déclenchement ignoré ({context})")
        else:
            logger.error(
                f"Pipeline échoué (exit {proc.returncode}) ({context}): "
                f"{(stderr or '')[-500:]}"
            )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


class WebhookHandler(BaseHTTPRequestHandler):
    """Handler HTTP pour les webhooks."""

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "ai-pipeline-webhook"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json(400, {"error": "invalid Content-Length"})
            return
        if content_length < 0 or content_length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "payload too large"})
            return
        body = self.rfile.read(content_length)

        if self.path == "/webhook/github":
            self._handle_github(body)
        elif self.path == "/webhook/trigger":
            self._handle_trigger(body)
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_github(self, body: bytes):
        """Traite un webhook GitHub."""
        signature = self.headers.get("X-Hub-Signature-256", "")
        if not verify_github_signature(body, signature):
            logger.warning("Signature webhook invalide")
            self._send_json(403, {"error": "invalid signature"})
            return

        event = self.headers.get("X-GitHub-Event", "")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        if event == "issues":
            action = payload.get("action", "")
            issue = payload.get("issue", {}) or {}
            labels = [l.get("name", "") for l in issue.get("labels", [])]
            issue_number = issue.get("number")
            # Pour « labeled », seul le label QUI VIENT d'être posé compte :
            # n'importe quel label ajouté à une issue déjà taguée relançait
            # le pipeline.
            added = (payload.get("label") or {}).get("name", "")

            if not isinstance(issue_number, int):
                self._send_json(400, {"error": "issue number missing"})
                return

            triggered_review = (
                (action == "opened" and "ai-review" in labels)
                or (action == "labeled" and added == "ai-review")
            )
            if triggered_review:
                logger.info(f"Issue #{issue_number} avec label ai-review détectée")

                # Déduire le profil depuis les labels (ceux du pipeline sont préfixés ai-)
                profile = "bugs"
                if {"security", "ai-security"} & set(labels):
                    profile = "security"
                elif {"quality", "ai-quality"} & set(labels):
                    profile = "quality"

                run_pipeline(
                    ["--issue", str(issue_number), "--profile", profile],
                    context=f"github-issue-{issue_number}",
                )
                self._send_json(202, {
                    "status": "accepted",
                    "issue": issue_number,
                    "profile": profile,
                })
                return

            # Issue taggée Propose_AI_PR -> lancer le worker
            if action == "labeled" and added == "Propose_AI_PR":
                logger.info(f"Issue #{issue_number} taggée Propose_AI_PR - lancement worker")
                run_pipeline(["--worker"], context=f"worker-propose-{issue_number}")
                self._send_json(202, {
                    "status": "accepted",
                    "action": "worker",
                    "trigger_issue": issue_number,
                })
                return

        self._send_json(200, {"status": "ignored", "event": event})

    def _handle_trigger(self, body: bytes):
        """Traite un déclenchement manuel via API."""
        if not verify_trigger_secret(self.headers.get("X-Pipeline-Secret", "")):
            logger.warning("Déclenchement refusé : secret absent ou invalide")
            self._send_json(403, {"error": "invalid secret"})
            return

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "JSON object expected"})
            return

        profile = payload.get("profile") or ""
        modules = payload.get("modules") or "all"
        issue = payload.get("issue")
        audit = bool(payload.get("audit", False))

        if not profile and issue is None:
            self._send_json(400, {"error": "profile or issue required"})
            return

        # Tout ce qui suit devient un argument de l'orchestrateur : on n'accepte
        # que des valeurs connues ou de forme sûre.
        if profile and profile not in known_profiles("audit" if audit else "small_fix"):
            self._send_json(400, {"error": f"unknown profile: {profile}"})
            return
        if not isinstance(modules, str) or not MODULE_RE.match(modules) or ".." in modules:
            self._send_json(400, {"error": "invalid modules"})
            return
        if issue is not None and not (isinstance(issue, int) or str(issue).isdigit()):
            self._send_json(400, {"error": "issue must be a number"})
            return

        args: list[str] = []
        if audit:
            args.append("--audit")
        if profile:
            args += ["--profile", profile]
        if issue is not None:
            args += ["--issue", str(issue)]
        else:
            args += ["--modules", modules]

        run_pipeline(args, context=f"api-trigger-{profile or f'issue-{issue}'}")

        self._send_json(202, {
            "status": "accepted",
            "profile": profile,
            "modules": modules,
            "issue": issue,
            "audit": audit,
        })

    def log_message(self, format, *args):
        """Override pour utiliser notre logger."""
        logger.debug(f"{self.client_address[0]} - {format % args}")


def main():
    global WEBHOOK_SECRET

    parser = argparse.ArgumentParser(description="AI Pipeline Webhook Server")
    parser.add_argument("--port", type=int, default=9090, help="Port d'écoute")
    parser.add_argument("--host", default="127.0.0.1", help="Adresse d'écoute")
    parser.add_argument(
        "--secret",
        default=None,
        help="Secret webhook (préférer la variable AI_PIPELINE_WEBHOOK_SECRET)",
    )
    args = parser.parse_args()

    WEBHOOK_SECRET = args.secret or os.environ.get("AI_PIPELINE_WEBHOOK_SECRET", "")

    if not WEBHOOK_SECRET and args.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error(
            "écoute hors loopback sans secret : n'importe qui sur le réseau "
            "pourrait lancer un agent qui écrit du code. Définir "
            "AI_PIPELINE_WEBHOOK_SECRET."
        )

    server = ThreadingHTTPServer((args.host, args.port), WebhookHandler)
    logger.info(f"Webhook server démarré sur {args.host}:{args.port}")
    logger.info("Endpoints:")
    logger.info("  POST /webhook/github  - Webhook GitHub")
    logger.info("  POST /webhook/trigger - Déclenchement API")
    logger.info("  GET  /health          - Health check")

    if not WEBHOOK_SECRET:
        logger.warning("Pas de secret configuré - signatures non vérifiées (loopback uniquement)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        # `shutdown()` attend la fin de `serve_forever()` : appelé depuis son
        # propre fil, il ne rendait jamais la main.
        logger.info("Arrêt du serveur")
        server.server_close()


if __name__ == "__main__":
    main()
