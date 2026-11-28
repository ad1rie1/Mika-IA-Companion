"""Le fond d'un modèle de plongements : ce qu'une recherche trouve de proche dans des textes sans rapport (ADR 0111).

Chaque modèle a sa propre échelle de similarité : deux phrases sans rapport valent 0,05 pour l'un, 0,75 pour
l'autre. Un seuil réglé pour un modèle (``recall_floor``, ``dedup_similarity``…) laisse tout passer avec un autre. La
recherche rend donc une similarité **centrée** : 0 pour ce que la requête a d'aussi proche que des textes quelconques
(la médiane de sa similarité avec ces phrases), 1 pour l'identique. Les seuils se lisent sur cette échelle, quel que
soit le modèle.

Ces phrases ressemblent à ce que sa mémoire range (des souvenirs, des croyances, des faits lus, des messages), sur
des sujets variés, sans en privilégier aucun : le modèle ne les lit jamais, elles ne servent qu'à mesurer.
"""

from __future__ import annotations

BACKGROUND = (
    "Il a repeint la cuisine en jaune pendant les vacances de printemps.",
    "Elle travaille comme comptable dans une petite entreprise de transport.",
    "Son grand-père collectionnait les timbres des anciennes colonies.",
    "Ils se sont rencontrés à un concert dans un bar de quartier.",
    "Il a horreur des huîtres depuis une intoxication en Bretagne.",
    "Elle a passé son permis de conduire à la troisième tentative.",
    "Sa fille commence la maternelle en septembre prochain.",
    "Il cherche un appartement plus grand pour avoir un bureau.",
    "Elle a adopté une tortue qui s'appelle Biscotte.",
    "Il s'est fait une entorse à la cheville en descendant l'escalier.",
    "Elle rêve de faire le tour de l'Islande en camping-car.",
    "Il ne boit jamais de café après seize heures.",
    "Elle a quitté son poste de vendeuse pour reprendre des études.",
    "Ses parents ont vendu la maison familiale l'hiver dernier.",
    "Il joue de la clarinette dans l'harmonie municipale.",
    "Elle s'est disputée avec sa voisine à cause d'une haie trop haute.",
    "Il a gagné un panier garni à la tombola de l'école.",
    "Elle lit surtout des romans policiers scandinaves.",
    "Il a perdu ses clés deux fois la même semaine.",
    "Elle prépare un gâteau au chocolat pour l'anniversaire de son neveu.",
    "Il dort mal depuis que les travaux ont commencé dans la rue.",
    "Elle trouve que les lundis matins sont toujours trop longs.",
    "Il a promis d'appeler sa sœur dimanche soir.",
    "Elle hésite entre deux couleurs pour son nouveau canapé.",
    "La production de blé a baissé cette année à cause de la sécheresse.",
    "Le musée rouvre ses portes après trois ans de rénovation.",
    "Une nouvelle ligne de tramway desservira le sud de la ville.",
    "Le prix du gazole a augmenté de quatre centimes en un mois.",
    "Les ours bruns hibernent pendant plusieurs mois en montagne.",
    "La comète sera visible à l'œil nu au début du mois de mars.",
    "Le conseil municipal a voté le budget de la piscine.",
    "Une grève perturbe le trafic des trains régionaux jusqu'à jeudi.",
    "Le volcan est entré en éruption pour la première fois depuis un siècle.",
    "Les ventes de vélos électriques ont doublé en cinq ans.",
    "Le festival de jazz accueillera quarante groupes cet été.",
    "La marée haute atteindra un coefficient exceptionnel ce week-end.",
    "Une étude montre que les abeilles reconnaissent les visages.",
    "Le championnat reprend après la trêve hivernale.",
    "La bibliothèque prolonge ses horaires d'ouverture le samedi.",
    "Les cerises arrivent plus tôt que d'habitude sur les marchés.",
    "Un nouveau smartphone pliable sortira à la rentrée.",
    "Le pont sera fermé à la circulation pendant deux nuits.",
    "La température de la mer dépasse les normales saisonnières.",
    "Les élections régionales auront lieu au printemps.",
    "Tu fais quoi ce soir ?",
    "J'ai trop mangé à midi, je vais faire une sieste.",
    "Il pleut encore, j'en ai marre.",
    "T'as vu le match hier soir ?",
    "Je suis crevé, la journée a été longue.",
    "On se voit demain pour le déjeuner ?",
    "Ma voiture refuse de démarrer ce matin.",
    "J'ai enfin fini ce dossier, quel soulagement.",
    "Tu connais une bonne recette de soupe ?",
    "Mon chef m'a encore demandé de rester tard.",
    "J'ai croisé un vieux copain au supermarché.",
    "Je pense partir à la mer en août.",
    "J'aime bien les soirées calmes quand tout le monde dort.",
    "Je me demande à quoi ressemble la neige quand on la touche.",
    "Cette chanson me reste dans la tête depuis ce matin.",
    "J'ai envie d'apprendre à reconnaître les étoiles.",
    "Parfois je relis nos vieilles conversations.",
    "Les histoires qui finissent bien me rendent un peu jalouse.",
    "Je n'ai jamais compris les règles du rugby.",
    "Le bruit de la pluie sur la fenêtre me calme.",
)
