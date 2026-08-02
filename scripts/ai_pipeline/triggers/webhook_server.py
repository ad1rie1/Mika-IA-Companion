"""
Micro-serveur webhook pour déclencher le pipeline AI.

Écoute les webhooks GitHub (issues) et les commandes externes.

Usage:
    python webhook_server.py
    python webhook_server.py --port 9090 --secret "mon_secret"

Endpoints:
    POST /webhook/github   - Webhook GitHub (issues avec label "ai-review")
    POST /webhook/trigger  - Déclenchement manuel via API
    GET  /health           - Health check
"""
import argparse
import hashlib
import hmac
import json
import logging
import subprocess
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
ORCHESTRATOR = SCRIPT_DIR / "orchestrator.sh"
LOG_DIR = SCRIPT_DIR / "logs"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "webhook.log"),
    ],
)
logger = logging.getLogger("ai-webhook")

# Configuré via args
WEBHOOK_SECRET = ""


def verify_github_signature(payload_body: bytes, signature: str) -> bool:
    """Vérifie la signature HMAC du webhook GitHub."""
    if not WEBHOOK_SECRET:
        return True  # pas de secret configuré = pas de vérification

    if not signature or not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        WEBHOOK_SECRET.encode(), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


def run_pipeline(args: list[str], context: str = ""):
    """Lance le pipeline dans un thread séparé."""
    def _run():
        logger.info(f"Pipeline lancé: {' '.join(args)} ({context})")
        try:
            result = subprocess.run(
                [str(ORCHESTRATOR)] + args,
                capture_output=True,
                text=True,
                timeout=900,
                cwd=str(SCRIPT_DIR.parent.parent),
            )
            if result.returncode == 0:
                logger.info(f"Pipeline terminé avec succès ({context})")
            else:
                logger.error(
                    f"Pipeline échoué (exit {result.returncode}): "
                    f"{result.stderr[-500:]}"
                )
        except subprocess.TimeoutExpired:
            logger.error(f"Pipeline timeout après 15min ({context})")
        except Exception as e:
            logger.error(f"Pipeline erreur: {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


class WebhookHandler(BaseHTTPRequestHandler):
    """Handler HTTP pour les webhooks."""

    def _send_json(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "ai-pipeline-webhook"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        if self.path == "/webhook/github":
            self._handle_github(body)
        elif self.path == "/webhook/trigger":
            self._handle_trigger(body)
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_github(self, body: bytes):
        """Traite un webhook GitHub."""
        # Vérifier la signature
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

        # Traiter les issues avec label "ai-review"
        if event == "issues":
            action = payload.get("action", "")
            issue = payload.get("issue", {})
            labels = [l.get("name", "") for l in issue.get("labels", [])]

            if action in ("opened", "labeled") and "ai-review" in labels:
                issue_number = issue.get("number")
                logger.info(f"Issue #{issue_number} avec label ai-review détectée")

                # Déduire le profil depuis les labels
                profile = "bugs"  # défaut
                if "security" in labels:
                    profile = "security"
                elif "quality" in labels:
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

            # Traiter les issues avec label "Propose_AI_PR" -> lancer le worker
            if action == "labeled" and "Propose_AI_PR" in labels:
                issue_number = issue.get("number")
                logger.info(
                    f"Issue #{issue_number} taggée Propose_AI_PR - lancement worker"
                )
                run_pipeline(
                    ["--worker"],
                    context=f"worker-propose-{issue_number}",
                )
                self._send_json(202, {
                    "status": "accepted",
                    "action": "worker",
                    "trigger_issue": issue_number,
                })
                return

        self._send_json(200, {"status": "ignored", "event": event})

    def _handle_trigger(self, body: bytes):
        """Traite un déclenchement manuel via API."""
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        profile = payload.get("profile", "")
        modules = payload.get("modules", "all")
        issue = payload.get("issue")

        if not profile and not issue:
            self._send_json(400, {"error": "profile or issue required"})
            return

        args = []
        if profile:
            args += ["--profile", profile]
        if modules:
            args += ["--modules", modules]
        if issue:
            args += ["--issue", str(issue)]

        run_pipeline(args, context=f"api-trigger-{profile or f'issue-{issue}'}")

        self._send_json(202, {
            "status": "accepted",
            "profile": profile,
            "modules": modules,
        })

    def log_message(self, format, *args):
        """Override pour utiliser notre logger."""
        logger.debug(f"{self.client_address[0]} - {format % args}")


def main():
    global WEBHOOK_SECRET

    parser = argparse.ArgumentParser(description="AI Pipeline Webhook Server")
    parser.add_argument("--port", type=int, default=9090, help="Port d'écoute")
    parser.add_argument("--host", default="127.0.0.1", help="Adresse d'écoute")
    parser.add_argument("--secret", default="", help="Secret webhook GitHub")
    args = parser.parse_args()

    WEBHOOK_SECRET = args.secret

    server = HTTPServer((args.host, args.port), WebhookHandler)
    logger.info(f"Webhook server démarré sur {args.host}:{args.port}")
    logger.info(f"Endpoints:")
    logger.info(f"  POST /webhook/github  - Webhook GitHub")
    logger.info(f"  POST /webhook/trigger - Déclenchement API")
    logger.info(f"  GET  /health          - Health check")

    if not WEBHOOK_SECRET:
        logger.warning("Pas de secret webhook configuré - signatures non vérifiées")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Arrêt du serveur")
        server.shutdown()


if __name__ == "__main__":
    main()
