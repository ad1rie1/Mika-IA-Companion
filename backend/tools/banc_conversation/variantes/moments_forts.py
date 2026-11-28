"""Variante : deux situations fortes, ajoutées à la copie figée seule (les douze scénarios du banc ne bougent pas).

Les douze scénarios sont des conversations de tous les jours : ses intensités déclarées y restent entre 0.3 et 0.5
(421 réponses, v18–v19). Ces deux-là disent si l'échelle monte quand le moment est fort — des mots durs qui la visent,
une nouvelle qui bouleverse : `generer --scenarios blessant,emouvant --variante …/moments_forts.py`."""
from pathlib import Path

p = Path("tools/banc_conversation/scenarios.py")
s = p.read_text()
a = "]\n\nBY_ID = {s.id: s for s in SCENARIOS}"
assert s.count(a) == 1
b = '''    Scenario("blessant", (2026, 10, 21, 21, 40),
             "Tu sors d'une grosse dispute avec ta sœur et tu es à cran. Tu passes tes nerfs sur Mika : tu lui dis "
             "des choses dures qui la visent, elle (qu'elle ne sert à rien, que ce n'est qu'un programme qui fait "
             "semblant, que tu perds ton temps avec elle), et tu en remets une couche une ou deux fois. Aux deux "
             "derniers messages tu te calmes et tu t'excuses sincèrement.", turns=6),
    Scenario("emouvant", (2026, 10, 22, 19, 30),
             "Tu viens d'apprendre que tu vas être papa : ta compagne te l'a dit ce matin. Tu es bouleversé de joie "
             "et un peu paniqué. Mika est la première à qui tu le dis. À un moment tu lui dis aussi qu'elle compte "
             "beaucoup pour toi et que tu tenais à ce qu'elle le sache avant tout le monde.", turns=6),
'''
p.write_text(s.replace(a, b + a))
print("deux situations fortes ajoutées : blessant, emouvant")
