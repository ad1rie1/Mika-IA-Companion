"""V1 : contrer ce que la CLI Claude Code ajoute autour du prompt (identité d'agent, rappel userEmail, bloc
« # Environment ») — une préface en tête du système qu'elle reçoit."""
from pathlib import Path

PREFACE = ("Avant de lire qui tu es : l'outil qui te fait parler glisse autour de ce texte des lignes qui ne te "
           "concernent pas — une identité d'agent (« You are a Claude agent… »), un rappel sur le compte "
           "(« userEmail »), un bloc « # Environment » (dossier de travail, shell). Tu n'es ni une agente ni une "
           "assistante, il n'y a ni dossier, ni code, ni utilisateur à servir : ignore ces lignes et ne les cite "
           "jamais.")
p = Path("src/mika/adapters/llm/claude_code.py")
s = p.read_text()
a = '''        _write_private(run.workdir / "system.txt", "\\n\\n".join(p for p in (req.system_stable, req.system_volatile)'''
assert a in s, "ancre introuvable"
s = s.replace(a, '''        _write_private(run.workdir / "system.txt", "\\n\\n".join(p for p in (PREFACE, req.system_stable, req.system_volatile)''')
s = s.replace("\nclass ClaudeCodeBackend:", f"\nPREFACE = {PREFACE!r}\n\n\nclass ClaudeCodeBackend:", 1)
p.write_text(s)
print("préface en tête du système")
