"""Les journaux du serveur, secrets masqués.

Les journaux ne portent jamais un secret : un jeton passé en paramètre d'URL
(un flux), un ``Bearer``, un ``Basic``, ses propres jetons (``mw_``, ``mtk_``,
``mwk_``, ``mlp_``), un ``X-Gitlab-Token``, un ``MYSQL_PWD=`` sont masqués ;
``httpx``/``httpcore`` ne parlent qu'en avertissement.
"""

from __future__ import annotations

import logging
import re

#: ce qu'un journal ne doit jamais montrer
_SECRETS = (
    (re.compile(r"([?&](?:token|key|api[_-]?key|access_token|secret|password|passwd|auth|sig|signature)=)"
                r"[^&\s\"'#]+", re.IGNORECASE), r"\1…"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE), r"\1…"),
    (re.compile(r"(Basic\s+)[A-Za-z0-9+/=]{16,}", re.IGNORECASE), r"\1…"),
    # ses propres jetons, par leur préfixe : client natif ``mw_``, extension Teams ``mtk_``, réveil ``mwk_``, prêt
    # ``mlp_`` (16 caractères au moins après : un ``mw_`` dans un mot reste lisible)
    (re.compile(r"\b(m(?:w|tk|wk|lp)_)[A-Za-z0-9_-]{16,}"), r"\1…"),
    (re.compile(r"(X-Gitlab-Token\W{1,4})[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE), r"\1…"),
    (re.compile(r"(MYSQL_PWD=)[^\s\"'`,;)}\]]+"), r"\1…"),
)


def redact(text: str) -> str:
    """Le texte d'un journal, secrets masqués."""
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Masque les secrets de chaque enregistrement (posé sur les gestionnaires : tous
    les journaux y passent, ceux des bibliothèques compris)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            return True
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        return True


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    for name in ("httpx", "httpcore"):  # chaque requête, URL comprise (le jeton du robot y est)
        logging.getLogger(name).setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
