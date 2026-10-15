"""V3 : sa matrice en phrases — seulement les traits qui la distinguent, sans aucun pourcentage."""
from pathlib import Path

p = Path("src/mika/faculties/self/character.py")
s = p.read_text()
a = '''        out.append(f"- {_with(line, t.notes.get(key, ''))}")'''
assert a in s
s = s.replace(a, '''        if key in ("reaction", "defense") and not getattr(t, key) and not t.notes.get(key):
            continue
        if key not in ("background", "reaction", "defense"):
            if LOW + _EPS < float(getattr(t, key)) < HIGH - _EPS and not t.notes.get(key):
                continue
            line = sentence(key, float(getattr(t, key)))
        out.append(f"- {_with(line, t.notes.get(key, ''))}")''')
p.write_text(s)
v = Path("persona/voix.yaml")
t = v.read_text()
start = t.index("    lead: >-\n      Ton caractère, pour toi seule")
end = t.index("    tail:", start)
t = t[:start] + ('    lead: "Ton caractère, pour toi seule : il se sent dans ta façon de répondre, tu ne le décris jamais à '
                 'personne. Voici ce qui te distingue ; pour le reste, tu es comme la plupart des gens."\n') + t[end:]
v.write_text(t)
print("traits distinctifs en phrases, sans pourcentage")
