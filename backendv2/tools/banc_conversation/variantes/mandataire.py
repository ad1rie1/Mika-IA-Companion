"""Variante d'audit : la CLI passe par le mandataire local (ANTHROPIC_BASE_URL transmis), pour enregistrer ce qu'elle
envoie vraiment au modèle."""
from pathlib import Path

p = Path("src/mika/adapters/llm/claude_code.py")
s = p.read_text()
a = 'INHERITED = ("HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "XDG_RUNTIME_DIR")'
assert a in s
p.write_text(s.replace(a, a[:-1] + ', "ANTHROPIC_BASE_URL")'))
print("ANTHROPIC_BASE_URL transmis à la CLI")
