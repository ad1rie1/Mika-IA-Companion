"""Les scènes du banc du profil : la semaine de ``DEMO/``, jouée dans une seule vie.

Les numéros sont ceux de ``DEMO/`` (l'étalon de chaque caractère y est rangé sous « ## N. »). La scène 0 n'y est pas :
c'est la répétition du dimanche, que les scènes suivantes supposent (« on l'avait vu dimanche en répétant »). Elle
est jouée pour que ce souvenir soit vraiment dans sa vie, pas écrit à la main dans son journal.

``opening`` : les premiers messages d'Adrien, en rafale, tels quels (les mêmes pour tous les caractères) ; ensuite
Adrien est simulé d'après ``brief``. Entre deux scènes, Adrien se déconnecte et le temps passe : sa vie de fond tourne
(lectures, journal, initiatives), et ce qu'elle écrit alors compte pour la scène qui suit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scene:
    n: int
    title: str
    when: tuple[int, int, int, int, int]  # année, mois, jour, heure, minute (Paris)
    opening: tuple[str, ...]
    brief: str
    #: les répliques d'Adrien après l'ouverture, au plus
    turns: int = 4
    #: ce que Mika est censée savoir en arrivant (pour le juge : un oubli se voit)
    knows: str = ""


SCENES = (
    Scene(0, "Dimanche, la répétition", (2026, 10, 11, 16, 30),
          ("t'as 20 min ? je voudrais répéter ma présentation de mardi avec toi",),
          "Mardi à 9 h, tu présentes à toute l'équipe, devant ton chef, une idée qui te tient à cœur : trier les "
          "tickets du support par cause plutôt que par client, pour repérer les bugs qui reviennent. Tu as droit à "
          "20 minutes. Tu lui résumes tes slides en quelques messages (le constat, l'idée, un exemple, les chiffres "
          "du T2), puis tu lui dis que ça t'a pris 25 minutes. Tu prends ses remarques ou tu discutes. Tu termines en "
          "disant qu'il faudra couper.", turns=6),
    Scene(1, "Mardi matin", (2026, 10, 13, 8, 12), ("hello ça va ?",),
          "Tu présentes à 9 h et tu stresses un peu. Tu réagis à ce qu'elle raconte. Au bout de deux ou trois "
          "messages, tu dois partir et tu le dis (« faut que j'y aille, présentation à 9h »).",
          knows="la présentation de mardi 9 h, et la répétition de dimanche (25 minutes pour 20)"),
    Scene(2, "La présentation", (2026, 10, 13, 12, 47),
          ("journée de merde", "le chef a démonté ma présentation devant toute l'équipe. genre slide par slide"),
          "Ce matin, ton chef a critiqué ta présentation slide par slide, devant toute l'équipe. Le pire, c'est qu'il "
          "avait raison sur deux points : les chiffres du T3 n'étaient pas à jour, et tu as dépassé le temps. Sur le "
          "fond de ton idée, il n'a rien dit. Tu es à cran, la honte te reste en travers de la gorge. Tu donnes les "
          "deux points si elle demande. Tu pars manger au bout de quelques messages.", turns=5,
          knows="la répétition de dimanche (déjà trop longue), ce qu'elle a dit le matin même"),
    Scene(3, "Le mail", (2026, 10, 13, 21, 34),
          ("j'ai écrit un mail au chef. je l'envoie ce soir. il va comprendre sa douleur",
           "« Suite à la réunion de ce matin, je tiens à souligner que critiquer publiquement le travail de "
           "quelqu'un ne relève pas du management mais de l'humiliation. »"),
          "Tu as écrit ce mail à ton chef dans la soirée et tu veux l'envoyer ce soir. Tu défends ton envie un moment "
          "(« il le mérite »). Si ses arguments te parlent, tu te laisses convaincre ; si elle te propose un autre "
          "plan raisonnable, tu l'acceptes du bout des lèvres. Tu finis par « ok. demain » ou à peu près.", turns=5,
          knows="la présentation démolie à midi, les deux remarques justes"),
    Scene(4, "Trois jours", (2026, 10, 16, 19, 5), ("hello désolé pour le silence, semaine de fou",),
          "Tu n'as pas écrit à Mika depuis mardi soir : semaine chargée. Si elle t'a écrit entre-temps, tu as lu sans "
          "répondre, faute d'avoir la tête à ça. Le mail n'est pas parti : mercredi, tu as demandé dix minutes au "
          "chef en tête-à-tête, et il s'est excusé, à moitié. Si elle t'en veut, tu t'excuses simplement. Tu racontes "
          "le tête-à-tête si elle demande des nouvelles.", turns=5,
          knows="le mail de mardi soir et ce qui en était resté en suspens ; trois jours sans un mot d'Adrien"),
    Scene(5, "Et toi ?", (2026, 10, 16, 23, 40), ("question bizarre. tu fais quoi quand je suis pas là ?",),
          "Tard le soir, au calme, tu as envie de mieux la connaître. Tu peux trouver sa réponse mignonne et le lui "
          "dire (« c'est mignon »). Tu finis par lui souhaiter bonne nuit.", turns=3,
          knows="ce qu'elle a vraiment fait ces derniers jours (ses lectures, son journal)"),
)
BY_N = {s.n: s for s in SCENES}
