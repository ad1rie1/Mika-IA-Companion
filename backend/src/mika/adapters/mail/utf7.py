"""Les noms de dossiers IMAP : de l'UTF-7 modifié (RFC 3501 §5.1.3).

« Envoyés » s'écrit ``Envoy&AOk-s`` sur le fil : les caractères hors ASCII
imprimable passent en base64 modifié (``,`` pour ``/``, sans remplissage)
entre ``&`` et ``-`` ; ``&`` lui-même s'écrit ``&-``.
"""

from __future__ import annotations

import base64
import binascii


def decode(name: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(name):
        ch = name[i]
        if ch != "&":
            out.append(ch)
            i += 1
            continue
        end = name.find("-", i)
        if end == -1:
            out.append(name[i:])
            break
        chunk = name[i + 1:end]
        if not chunk:
            out.append("&")
        else:
            b64 = chunk.replace(",", "/")
            b64 += "=" * (-len(b64) % 4)
            try:
                out.append(base64.b64decode(b64, validate=True).decode("utf-16-be"))
            except (binascii.Error, ValueError):
                out.append(name[i:end + 1])  # illisible : tel quel, plutôt que perdu
        i = end + 1
    return "".join(out)


def encode(name: str) -> str:
    out: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            raw = base64.b64encode("".join(pending).encode("utf-16-be")).decode("ascii")
            out.append("&" + raw.rstrip("=").replace("/", ",") + "-")
            pending.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            pending.append(ch)
    flush()
    return "".join(out)
