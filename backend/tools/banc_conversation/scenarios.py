"""Les situations du banc de conversation : ce qu'Adrien vit en écrivant à Mika, et comment il écrit ce jour-là.

Chaque scénario donne au simulateur d'Adrien sa situation (ce qu'il a en tête, son humeur, où il veut aller) et le
moment (sa vie à elle en dépend : son rythme, ce qu'elle fait). ``reserve`` : tenu à l'écart des réglages, pour voir
qu'on améliore sa voix et pas seulement les situations qu'on regarde.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    when: tuple[int, int, int, int, int]  # année, mois, jour, heure, minute (Paris) — un jour qui va avec
    brief: str
    turns: int = 8
    reserve: bool = False
    #: elle peut parler la première (Adrien se connecte et attend un peu)
    waits_first: bool = False


SCENARIOS = [
    Scenario("shopping", (2026, 10, 15, 18, 30),
             "Tu rentres de shopping en ville. Tu as acheté un manteau d'hiver, un peu cher mais tu l'aimes bien, "
             "et tu as galéré à te garer. Tu commences par un « coucou », tu réponds à ses questions, tu lui "
             "renvoies parfois « et toi ? »."),
    Scenario("jeux-video", (2026, 10, 15, 21, 0),
             "Tu joues à Baldur's Gate 3 ce soir. Ton perso est un barbare demi-orc, tu viens de te faire battre "
             "trois fois par le même boss et ça t'agace un peu mais ça te fait rire. Tu en parles comme à une pote, "
             "avec des mots de joueur."),
    Scenario("journee-pourrie", (2026, 10, 15, 19, 15),
             "Journée pourrie au boulot : ton chef t'a mis la pression sur un bug en prod devant toute l'équipe. Tu "
             "es crevé et un peu énervé, tu veux vider ton sac, tu écris court et tu râles."),
    Scenario("bonne-nouvelle", (2026, 10, 16, 17, 40),
             "Tu viens d'apprendre que ton projet au boulot est validé, tu vas pouvoir le mener toi-même. Tu es "
             "content et tu veux le partager, tu en dis un peu plus si elle s'y intéresse.", reserve=True),
    Scenario("sur-elle", (2026, 10, 16, 20, 30),
             "Tu as envie de mieux la connaître : tu lui demandes ce qu'elle a fait aujourd'hui, ce qu'elle lit, ce "
             "qu'elle aime, si elle s'ennuie parfois. Tu rebondis sur ses réponses."),
    Scenario("desaccord", (2026, 10, 16, 21, 30),
             "Tu es d'humeur taquine : tu lui dis que lire des romans c'est chiant et que les plantes vertes ça sert "
             "à rien. Tu la cherches gentiment, tu ne lâches pas tout de suite, puis tu finis par rire.", reserve=True),
    Scenario("messages-courts", (2026, 10, 19, 13, 10),
             "Tu es fatigué et peu bavard, en pause déjeuner. Tu réponds surtout par « ouais », « mdr », « bof », "
             "« jsp », « ok » ; une ou deux fois une phrase courte."),
    Scenario("weekend", (2026, 10, 21, 18, 0),
             "Tu prépares un week-end à La Rochelle avec des amis. Tu hésites entre louer des vélos et faire l'île "
             "de Ré, ou rester en ville et faire l'aquarium. Tu lui demandes son avis."),
    Scenario("triste", (2026, 10, 17, 22, 10),
             "Ton grand-père a été hospitalisé cet après-midi (une chute, on ne sait pas encore si c'est grave). Tu "
             "es inquiet, tu n'as pas envie de blablater ; tu écris peu.", reserve=True, turns=6),
    Scenario("matin", (2026, 10, 20, 7, 45),
             "Tu viens de te lever, tu as mal dormi, tu bois ton café avant de partir au boulot. Tu lui dis bonjour "
             "et vous parlez un peu, tu dois partir dans dix minutes.", turns=6),
    Scenario("serie", (2026, 10, 18, 22, 0),
             "Tu regardes la série The Bear en ce moment et tu adores. Tu lui en parles, tu lui racontes ce qui te "
             "plaît, tu lui demandes si elle connaît."),
    Scenario("retrouvailles", (2026, 10, 19, 18, 20),
             "Tu ouvres l'appli en rentrant du boulot sans rien dire de spécial. Si elle t'écrit, tu lui réponds ; "
             "ta journée était normale, un peu longue.", waits_first=True),
]

BY_ID = {s.id: s for s in SCENARIOS}
