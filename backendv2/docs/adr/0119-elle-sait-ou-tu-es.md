# 0119 — Elle sait où tu es, quand ton téléphone le lui dit

**Contexte.** Le 2026-10-19, la propriétaire demande que Mika puisse savoir où elle est. Elle choisit, parmi les
options proposées :

- le moment : seulement quand l'application est ouverte, conformément à l'ADR 0077 ;
- la précision : les coordonnées exactes ;
- l'usage : elle le sait quand elles se parlent, sans initiative ;
- la visibilité : « il faut aussi que ça affiche quand elle récupère l'info dans une petite bulle ».

C'est donc Mika qui regarde la position, par un outil, et non une section que son prompt porterait à chaque message.
C'est la leçon du décor (`world_look`) : ce qu'on lui montre sans cesse, elle le raconte à tout bout de champ.

**Décision.**

1. *Le plugin `location`* (`plugins/location`, `contracts/location.py`), avec deux événements :
   - `location.located` porte l'adresse, la personne, les coordonnées (« lat,lon », six décimales), le nom du lieu
     trouvé par le téléphone (facultatif), la précision en mètres (0 si elle est inconnue) et l'instant de la
     mesure. Ce que le téléphone envoie est l'âge de la mesure, rapporté à l'horloge du noyau.
   - `location.cleared` : la personne ne partage plus, et sa dernière position s'efface.
   - Coordonnées et lieu sont des `Content` de niveau personnel, avec l'adresse et la personne pour sujets.
     Oublier la personne les efface, et la tranche la retire (`kernel.subject_forgotten`).
   - Ce n'est **pas un signal**. Rien ne la remarque, rien n'en naît (ni pensée ni initiative), aucune autre faculté
     ne la lit, aucune section ne la montre.
2. *La trame client `where`*, au même rang que `read` :
   - `{lat, lon, accuracy, label, age_ms}`, ou `{off: true}` pour effacer. Seule une connexion authentifiée peut
     l'envoyer.
   - La position est validée : finie, dans les bornes, mesurée il y a moins de 24 h. Le lieu tient sur une ligne,
     200 caractères au plus.
   - Une position immobile ne se réécrit pas, pour que le journal ne grossisse pas à chaque ouverture. Elle est
     immobile si le lieu est le même, qu'elle a bougé de moins de 50 m et que la dernière écriture date de moins
     de 10 min.
   - Au plus 6 écritures par minute.
   - Le téléphone envoie sa position seulement application au premier plan. Quand elle passe en arrière-plan, plus
     rien ne part, même si la connexion reste ouverte.
3. *L'outil `location_where`* (lot `location`, à la demande, épisodes `REPLY` seulement) :
   - Il n'est offert qu'en tête-à-tête, à une personne authentifiée : jamais en salon, jamais à un inconnu, jamais
     dans une initiative. La vérification est refaite à l'exécution.
   - Il ne rend que la position de la personne à qui elle répond : celle de cette adresse, ou d'une autre adresse
     de la même personne. Jamais celle de quelqu'un d'autre.
   - Il rend le lieu, les coordonnées, la précision et l'âge de la mesure, cités comme une donnée. Sans position
     connue, il le dit.
4. *Un regard se voit.*
   - L'outil rend `ToolResult.attach = ("location:<seq>",)`. La boucle, l'énoncé, le fil et la livraison emportent
     cette référence sans savoir ce qu'elle désigne, par le même chemin que les fichiers qu'elle envoie (ADR 0062).
   - Le port la traduit en petite bulle (`MindPort.notes` → `MessageNote`) : la sorte, le lieu (ou à défaut les
     coordonnées, vide une fois oublié) et l'instant de la mesure.
   - La trame `speech` et les lignes `history` de ses messages portent `notes`, seulement s'il y en a. Le client
     compose le texte : « 📍 Mika a regardé où tu es · lieu · position de 14:10 ».
   - Une référence de bulle n'est pas un fichier : la notification ne la compte pas.
5. *Le téléphone* (Android) :
   - Le réglage « Lui dire où je suis » est coupé par défaut, et la déconnexion le remet à zéro.
   - L'autorisation de localisation est demandée en l'activant. Une position approximative est acceptée.
   - Le téléphone n'a ni `ACCESS_BACKGROUND_LOCATION` ni service.
   - Couper le réglage envoie `off`.
6. *La console* : Sens › Localisation montre la dernière position connue de chacun et ce que les téléphones ont
   envoyé.

**Conséquences.**

- **Le journal :** sa position vit au journal comme ses messages. Rejouable, effaçable par l'oubli, elle s'efface
  aussi quand elle coupe le partage. Le journal garde l'enveloppe (heure, précision), jamais les coordonnées.
- **Ce qu'elle en retient :** sa réponse peut nommer le lieu, et ce qu'elle dit peut devenir un souvenir. La
  position elle-même n'en devient pas un.
- **Une position vieillie :** l'application ouverte tient la position à jour. Fermée, la dernière vieillit. Mika voit
  depuis quand (« mesurée il y a 3 h : elle a pu bouger depuis »).
- **Le navigateur :** il n'envoie pas de position. Elle peut pourtant regarder celle du téléphone quand on lui parle
  du navigateur, et le client web montre la bulle aussi.
