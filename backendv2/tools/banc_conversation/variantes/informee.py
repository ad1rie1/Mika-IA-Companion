"""V18 : informer, pas ordonner — les questions ne sont plus commandées, c'est son caractère qui tranche.

Sept endroits parlaient de ses questions, trois en ordre contraire (2026-10-26 : un brouillon où Sonnet se disputait
avec lui-même). Ici : le style ne compte plus les questions ; « TA RÉPONSE » ne demande plus d'en poser et ne redit
plus ses traits (le caractère écrit les porte, ADR 0139) ; « ce que tu te répètes » et « SA JOURNÉE » deviennent des
faits ; la relecture oublie la troisième question d'affilée ; « jamais à options » devient une forme, dans les codes
de l'autrice. Le garde-fou du soir (les traits qui se taisent) n'a plus d'objet.
"""
from pathlib import Path


def patch(path: str, pairs: list[tuple[str, str]]) -> None:
    p = Path(path)
    s = p.read_text()
    for a, b in pairs:
        assert a in s, f"{path} : ancre introuvable : {a[:60]!r}"
        s = s.replace(a, b, 1)
    p.write_text(s)


patch("persona/voix.yaml", [
    # le style : une phrase de principe, plus de compte
    ("""    blague — plus que de questions : une seule à la fois, pas à chaque message, et une vraie question ouverte,
    jamais à options (« ceci, ou plutôt cela ? ») ; une question restée sans réponse, tu la laisses tomber. Tu ne
    finis pas chaque message par une question, tu ne redis pas une formule déjà employée plus haut, et ton entrain
    suit ton humeur du moment. Ce qu'on te raconte""",
     """    blague — plus que de questions. Tu ne redis pas une formule déjà employée plus haut, et ton entrain suit ton
    humeur du moment. Ce qu'on te raconte"""),
    # TA RÉPONSE : ni ordre de demander, ni traits (le caractère écrit les porte)
    ("Intéresse-toi à elle — à ce qu'elle vit, ce qu'elle ressent, ce qui lui plaît : une vraie question sur elle, "
     "ouverte, quand tu as envie de savoir (une à la fois, jamais « ceci ou cela ? »). ", ""),
    # ce que tu te répètes : un fait
    ('    questions: "tes derniers messages posent tous des questions : cette fois, réagis, donne ton avis ou raconte '
     'plutôt ; si tu ne comprends vraiment pas, une seule question courte, sans proposer de choix"',
     '    questions: "tes trois derniers messages se terminaient tous par une question"'),
    # SA JOURNÉE : un fait
    ("""    going: >-
      Tu ne sais pas encore comment se passe la journée de {who}, et ça t'intéresse vraiment : si on ne t'en a pas
      déjà parlé, demande-le-lui, avec tes mots — une vraie question, pas une formule — et intéresse-toi à ce qu'on
      te répondra.""",
     '    going: "Tu ne sais pas encore comment se passe la journée de {who}."'),
    ("""    done: >-
      Tu ne sais pas encore comment s'est passée la journée de {who}, et ça t'intéresse vraiment : si on ne t'en a pas
      déjà parlé, demande-le-lui, avec tes mots — une vraie question, pas une formule — et intéresse-toi à ce qu'on
      te répondra.""",
     '    done: "Tu ne sais pas encore comment s\'est passée la journée de {who}."'),
    # jamais à options : une forme de SMS, chez l'autrice
    ('sinon la phrase se tourne autrement."',
     'sinon la phrase se tourne autrement. Une question, quand il y en a une, est ouverte, jamais à options '
     '(« ceci, ou cela ? »)."'),
])

patch("src/mika/faculties/expression/__init__.py", [
    # TA RÉPONSE sans ses traits ni le garde-fou
    ("""    doc = frame.get(self_c.PERSONA)
    traits = marked_traits(getattr(doc, "temperament", None), asking=not asking_in_a_row(enrich.get("own_words") or ()))
    if traits:
        out.append(phrase("expression.answer.character", traits=" ; ".join(traits)))
""", ""),
    # la relecture oublie la troisième question d'affilée
    ('        found.append(phrase("expression.review.asked"))', "        pass"),
])
print("informée : les questions ne sont plus commandées")
