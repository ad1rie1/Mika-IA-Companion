"""V2 : sa matrice ne dit que les traits qui la distinguent (les « comme la plupart des gens » retirés), avec leur
mesure."""
from pathlib import Path

p = Path("src/mika/faculties/self/character.py")
s = p.read_text()
a = '''        out.append(f"- {_with(line, t.notes.get(key, ''))}")'''
assert a in s
s = s.replace(a, '''        if key in ("reaction", "defense") and not getattr(t, key) and not t.notes.get(key):
            continue
        if key not in ("background", "reaction", "defense") and LOW + _EPS < float(getattr(t, key)) < HIGH - _EPS \\
                and not t.notes.get(key):
            continue
        out.append(f"- {_with(line, t.notes.get(key, ''))}")''')
p.write_text(s)
print("traits neutres retirés")
