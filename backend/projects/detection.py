"""Detect which active Project (if any) a user message concerns.

Pure Python + keyword heuristic — no LLM. Three signals combine:
  1. Explicit mention in the message of the project title (substring match
     on any word of title, length >= 3)
  2. Keyword overlap with `project.keywords`
  3. Owner mention — if the message talks about a specific person who
     owns a project, bias toward that project

Returns the best-matching active project or None. A confidence score
lets downstream code decide whether the project bloc is strong enough
to inject into the system prompt.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


# Below this confidence we don't surface the project in the prompt — too
# much risk of false match. The project still runs on its own schedule.
MATCH_CONFIDENCE_THRESHOLD = 0.4


@dataclass
class ProjectMatch:
    project_id: int
    title: str
    confidence: float  # 0..1
    reason: str


_WORD_SPLIT = re.compile(r"[^\wàâäçéèêëïîôöùûüÿœæ]+", re.IGNORECASE | re.UNICODE)


def _normalize(text: str) -> set[str]:
    """Lowercase + split + drop short tokens. Returns a set for O(1) lookup."""
    words = _WORD_SPLIT.split(text.lower())
    return {w for w in words if len(w) >= 3}


async def detect_project_for_message(
    message: str, person_id: str | None = None
) -> ProjectMatch | None:
    """Find the active project most likely concerned by this message.

    Safe to call on empty / internal messages — returns None.
    """
    if not message or len(message.strip()) < 2:
        return None

    from projects.models import Project

    try:
        projects = await sync_to_async(
            lambda: list(
                Project.objects.filter(status=Project.Status.ACTIVE)
                .select_related("owner")
                .only(
                    "id", "title", "keywords", "owner__name",
                )
            )
        )()
    except Exception:
        logger.debug("Project query failed", exc_info=True)
        return None

    if not projects:
        return None

    tokens = _normalize(message)
    if not tokens:
        return None

    best: ProjectMatch | None = None

    for p in projects:
        score = 0.0
        reasons: list[str] = []

        title_tokens = _normalize(p.title)
        title_hits = title_tokens & tokens
        if title_hits:
            # Strong signal. Weight by how much of the title was hit.
            ratio = len(title_hits) / max(1, len(title_tokens))
            score += 0.55 * min(1.0, ratio + 0.3)
            reasons.append(f"title[{','.join(list(title_hits)[:3])}]")

        keyword_hits = set()
        for kw in p.keywords or []:
            kw_tokens = _normalize(str(kw))
            hit = kw_tokens & tokens
            if hit:
                keyword_hits |= hit
        if keyword_hits:
            # 1 keyword = weak signal, 2+ = strong. Scaling so 2 hits
            # passes the match threshold by itself.
            score += min(0.55, 0.2 * len(keyword_hits))
            reasons.append(f"kw[{','.join(list(keyword_hits)[:3])}]")

        # Owner mention — only bumps confidence, doesn't create match alone
        if p.owner and p.owner.name:
            owner_tokens = _normalize(p.owner.name)
            if owner_tokens & tokens and score > 0:
                score += 0.1
                reasons.append("owner")

        # Active person_id talking directly to owner's project gets a small
        # bump when there's any title or keyword signal at all.
        if person_id and p.owner and person_id == p.owner.name and score > 0:
            score += 0.1

        if score > 0 and (best is None or score > best.confidence):
            best = ProjectMatch(
                project_id=p.id,
                title=p.title,
                confidence=min(1.0, score),
                reason=" ".join(reasons) or "generic",
            )

    if best is None:
        return None
    if best.confidence < MATCH_CONFIDENCE_THRESHOLD:
        logger.debug(
            "Project match below threshold: %s (%.2f)",
            best.title, best.confidence,
        )
        return None
    logger.debug(
        "Project matched: %s (%.2f, %s)",
        best.title, best.confidence, best.reason,
    )
    return best


async def load_project_for_prompt(project_id: int) -> dict | None:
    """Shape the project fields needed for prompt injection + emotion
    policy decisions. Returned dict is JSON-serializable so callers can
    log it. Returns None if the project was deleted/archived since match.
    """
    from projects.models import Project, ProjectTask

    try:
        p = await sync_to_async(
            lambda: Project.objects.filter(
                id=project_id, status=Project.Status.ACTIVE,
            ).first()
        )()
    except Exception:
        return None
    if not p:
        return None

    todo_tasks = await sync_to_async(
        lambda: list(
            ProjectTask.objects.filter(
                project=p, status__in=[
                    ProjectTask.Status.TODO, ProjectTask.Status.IN_PROGRESS,
                ],
            ).order_by("order", "created_at")[:5]
            .values_list("description", flat=True)
        )
    )()

    return {
        "id": p.id,
        "title": p.title,
        "description": p.description,
        "tone_directive": p.tone_directive,
        "emotion_policy": p.emotion_policy,
        "instructions": list(p.instructions or []),
        "out_of_scope": list(p.out_of_scope or []),
        "requires_approval": p.requires_approval,
        "todo_tasks": list(todo_tasks),
    }
