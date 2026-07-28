"""Dashboard API — personality.yaml read/write.

Unlike scalar config, personality is a nested YAML document. We expose
it as a single GET/PATCH pair; write is atomic (temp file + replace)
and reloads the ``personality`` singleton in-place so the prompt layer
sees the new values immediately.
"""
from __future__ import annotations

import io
import json
import logging
import os
import tempfile

import yaml
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


def _path():
    return settings.PERSONALITY_PATH


@require_http_methods(["GET"])
def personality_read(request):
    path = _path()
    if not os.path.exists(path):
        return JsonResponse({"exists": False, "path": str(path), "data": {}})
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        return JsonResponse({"error": f"parse failed: {e}"}, status=500)
    return JsonResponse({"exists": True, "path": str(path), "data": data})


@require_http_methods(["PATCH", "PUT"])
def personality_write(request):
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    data = body.get("data")
    if not isinstance(data, dict):
        return JsonResponse({"error": "'data' must be a dict"}, status=400)

    try:
        # Serialize first so we don't truncate the file if yaml.dump fails.
        serialized = yaml.safe_dump(
            data, sort_keys=False, allow_unicode=True, default_flow_style=False,
        )
    except Exception as e:
        return JsonResponse({"error": f"serialize failed: {e}"}, status=400)

    path = _path()
    try:
        # Atomic write: tempfile in same directory → os.replace
        dir_ = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(prefix=".personality.", suffix=".yaml.tmp", dir=dir_)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(serialized)
            os.replace(tmp, path)
        except Exception:
            try: os.unlink(tmp)
            except Exception: pass
            raise
    except Exception as e:
        logger.exception("Failed to write personality.yaml")
        return JsonResponse({"error": f"write failed: {e}"}, status=500)

    # Hot-reload the singleton — next prompt build picks up the new values
    try:
        from config.personality import personality
        personality.load()
        logger.info("personality.yaml reloaded")
    except Exception:
        logger.exception("personality reload failed")

    return JsonResponse({"ok": True, "bytes": len(serialized)})
