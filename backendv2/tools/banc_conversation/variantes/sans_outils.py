"""V4 : aucun outil ni catalogue d'outils en conversation (réponses et initiatives) — mesurer ce que le cadre
d'agent coûte à son naturel (« désactiver le MCP »)."""
from pathlib import Path

p = Path("src/mika/runtime/pipeline.py")
s = p.read_text()
a = '''                tools = self._tools(policy, req.kind, audience,'''
assert a in s
s = s.replace(a, '''                tools = {} if req.kind in self.reviewed else self._tools(policy, req.kind, audience,''')
p.write_text(s)
print("pas d'outils en conversation")
