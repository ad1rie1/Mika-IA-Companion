# Le protocole du monde — `mika.world/1`

Ce document est pour qui écrit un client du monde : le moteur de jeu (Unity), le client web en Three.js, un
outil de création. La décision et ses raisons sont dans l'[ADR 0050](adr/0050-le-monde.md) ; les types font foi
dans [`contracts/world.py`](../src/mika/contracts/world.py) (le monde) et
[`adapters/world/protocol.py`](../src/mika/adapters/world/protocol.py) (les trames). Chaque exemple JSON de ce
document est validé par les tests (`tests/protocol/test_world_wire.py`) : il ne peut pas vieillir sans qu'un
test le dise.

## 1. Qui fait quoi

```
            créateur (opératrice)                      joueuse(s)
                    │ edit / describe                       │ act / moved / address / answer / pose
                    ▼                                       ▼
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │  NOYAU (backendv2) — seule autorité                                           │
 │  valide → journalise → diffuse   ·   Mika décide (outils) · réflexes · issues │
 └──────────────────────────────────────────────────────────────────────────────┘
        │ definition · snapshot · delta · intent · intent_end · request · gesture
        ▼                                                    ▲
   tous les clients (ils montrent)            moteur HÔTE (un seul) : joue les actions,
                                              constate (report : finished, settled, npc, sound)
```

- **Le créateur** écrit le monde : pièces, lieux, sortes d'objets et ce qu'on peut en faire, objets,
  personnages. Il ne dessine pas : la géométrie, les modèles et les animations sont dans le projet du
  moteur, référencés par des clés (`asset`, `anchor`, `animation`).
- **Mika** fait vivre le monde : elle va quelque part, prend, pose, allume, lit, tend, fait signe — par ses
  outils, validés par le noyau. Certains gestes sont des réflexes (elle s'endort : elle va au lit).
- **Le moteur hôte** charge le monde, joue ce que le noyau a décidé et dit ce qu'il constate. Il ne décide
  jamais : il peut **refuser** (« je n'arrive pas à la faire passer ») et **constater** (« la tasse est
  tombée »), et le noyau valide ce constat comme n'importe quelle action.
- **Les joueuses** ont un corps dans le monde : elles s'y déplacent, agissent sur les objets, font des gestes,
  demandent (un câlin, un objet), répondent aux demandes de Mika.

## 2. Les règles de cohérence

1. **Un seul écrivain.** Tout changement du monde (définition ou état) est un événement du journal. Un client
   n'applique jamais un changement avant de l'avoir reçu du noyau, même le sien (`result` puis `delta`).
2. **La vérité est discrète.** Une pièce, un lieu, une surface et sa place, l'intérieur d'un contenant, une
   main. Aucune coordonnée n'est vraie ; seule la définition porte une position grossière par lieu (`pos`, en
   mètres), pour les distances et les durées de marche.
3. **La physique est un rendu.** Une tasse qui rebondit, des cheveux, un tissu : le moteur les fait comme il
   veut. Ce qui change l'état du monde passe par un constat (`report`) validé.
4. **Une chose est à un seul endroit.** Une main tient un objet (deux mains : un objet `arms`), un lieu
   reçoit au plus `capacity` personnes, une place de surface au plus un objet, un contenant au plus
   `container_slots` objets.
5. **On ne prend pas ce que l'autre tient.** On demande (`ask`), on tend (`offer`) : l'autre accepte ou non.
6. **Tout est validé par les mêmes règles**, qu'il vienne de Mika, d'une joueuse, de l'hôte ou du créateur ;
   un refus a un code (§ 9) et une phrase en français.
7. **L'ordre est celui du journal.** Chaque trame diffusée porte son `seq` ; un client applique dans l'ordre
   et redemande ce qui manque (`sync`). Les `seq` sont ceux du journal de sa vie entière : **croissants, pas
   contigus** — un écart n'est pas une perte (§ 5, « Rattraper »).
8. **Le monde existe sans spectateur.** Sans moteur hôte, une action se termine comme prévue à son échéance
   (`deadline`). Le premier client qui arrive reçoit l'état tel qu'il est, et le pose sans le rejouer.
9. **Ce qui est continu ne compte pas.** La pose d'un avatar (`pose`, 20 par seconde) est relayée aux autres
   clients sans passer par le journal ; Mika ne la voit jamais. Seules les arrivées (`moved`) comptent.

## 3. Le monde (la définition)

Un monde (`WorldDef`, fichier d'exemple : [`examples/monde/chambre.json`](../examples/monde/chambre.json))
contient :

| Élément | Ce que c'est | Champs qui comptent |
|---|---|---|
| `rooms` | une pièce | `label` (ce qu'elle lit : « ta chambre »), `exits` (passages : depuis le lieu `via` vers la pièce `to`, on arrive au lieu `arrives`) |
| `places` | un endroit où se tenir | `place_kind` (`spot` debout, `seat` assis, `bed` assis ou allongé), `capacity`, `pos` (le point d'approche : mètres, `x`/`z` de l'espace de la pièce, Y vers le haut), `facing` (lacet en radians, l'avant est `(sin φ, cos φ)` : 0 regarde vers +Z), `anchor` (ancre de la scène du moteur), `of_object` (le meuble qui le porte), `tags` (`sleep` : où elle dort, `work` : où elle travaille, `spawn` : où entre une personne) |
| `archetypes` | une sorte d'objet | `asset` (le prefab), `size` (`hand`, `arms`, `fixed`), `states` + `initial_state`, `affordances`, `surface_slots`, `container_slots`, `salience` |
| `objects` | un objet | `archetype`, `label`, `home` (où il est au départ), `state`, `owner`, `given_by`, `access` |
| `actors` | Mika et les personnages du monde | `asset`, `home` (un lieu), `controller` (`kernel` pour Mika seule, `host` pour un personnage que le moteur fait vivre) |

**Les identifiants** (`[a-z][a-z0-9_]*`, 48 caractères au plus) des pièces, des lieux et des objets
partagent un seul espace de noms : `go_to("desk")` ne peut pas être ambigu. Les archétypes ont le leur. Un
acteur est `mika`, `npc:<id>` ou `player:<adresse>`.

**Les noms** (`label`) vont dans son prompt : 60 caractères au plus, ni retour à la ligne ni caractère de
contrôle. La prose (« la plante qu'Adrien t'a offerte ») passe par `describe` : c'est un texte gardé qui dit qui
il concerne, et l'oubli d'une personne l'emporte.

**Les actions.** Toute chose permet les actions de base : `take`, `put`, `give`, `drop` pour ce qui se porte ;
`sit`, `lie`, `stand` sur un lieu. Le reste est déclaré par l'archétype (`affordances`) : un identifiant
libre (`allumer`, `arroser`, `lire`), un nom, et un **effet** pris dans une liste fermée :

| Effet | Ce qu'il fait | Champs |
|---|---|---|
| `state` | l'objet change d'état | `requires_state`, `to_state` |
| `activity` | l'acteur s'occupe avec l'objet (lire, jouer, regarder dehors) | `activity`, `duration_s` (`null` : jusqu'à ce qu'on l'interrompe) |
| `consume` | l'objet disparaît (manger un biscuit) | |

Communs : `held` (il faut tenir l'objet), `duration_s` (durée nominale), `access` (qui d'autre qu'elle a le
droit), `noise` (0 : s'entend dans la pièce, 1 : jusqu'aux pièces voisines), `animation` (clé d'animation du
moteur).

**L'accès** (`access` d'un objet ou d'une affordance) est gradué : `anyone`, `friends` (ses amies et ses
proches), `owners` (les personnes qui s'occupent d'elle), `mika` (elle seule). Elle-même peut toujours.

**Cohérent ou rien.** Un monde où un objet est posé sur un meuble sans surface, deux objets à la même place,
un état inconnu de l'archétype, un lieu dans une pièce inconnue, un objet de départ dans une main, un passage
vers nulle part, un objet posé sur lui-même d'objet en objet… ne se construit pas : la validation dit tout ce
qui ne va pas d'un coup. Une édition (`edit`) qui rendrait le monde incohérent est refusée en entier
(`incoherent`).

## 4. L'état vécu

```json serveur
{"type": "snapshot", "state": {"rev": 3, "seq": 1544,
  "actors": [
    {"id": "mika", "room": "bedroom", "place": "desk", "posture": "sit", "holding": ["mug"],
     "activity": {"name": "draw", "object": "sketchbook", "since": 1789999900000000}},
    {"id": "player:user_1", "room": "bedroom", "place": "door"},
    {"id": "npc:moka", "room": "living_room", "place": "sofa", "posture": "sit"}],
  "objects": [
    {"id": "mug", "location": {"kind": "held", "actor": "mika", "hand": "right"}, "state": "full",
     "since": 1789999000000000},
    {"id": "desk_lamp", "location": {"kind": "on", "object": "writing_desk", "slot": 0}, "state": "on"},
    {"id": "cookie_1", "location": {"kind": "in", "object": "cookie_jar"}},
    {"id": "guitar", "location": {"kind": "room", "room": "bedroom", "near": "bed"}}],
  "intents": [], "requests": []}}
```

- **Où est un objet** (`location`) : `room` (au sol ou meuble à sa place, `near` : le lieu le plus proche),
  `on` (sur la place `slot` d'une surface), `in` (dans un contenant), `held` (dans la main d'un acteur).
- **Un acteur** : sa pièce, son lieu, sa posture, ce qu'il tient, son occupation (`activity`, avec sa fin
  prévue `until` ou sans), et s'il est en chemin (`moving` : vers où, `started`, `eta` — un écran qui s'ouvre
  en route le place sur son trajet).
- **Les actions en cours** (`intents`) et **les demandes** qui attendent une réponse (`requests`).

Les instants sont en **microsecondes** depuis l'epoch, sur l'horloge du noyau (`welcome.now` permet au
client de calculer son décalage).

## 5. Se connecter

WebSocket sur **`/ws/world`**, trames JSON texte. Un navigateur s'authentifie par sa session (et l'en-tête
`Origin` est vérifié) ; un client natif par un **jeton** de son compte dans `hello.token` ou l'en-tête
`Authorization: Bearer …` (pas d'`Origin` : sans jeton, refusé ; avec une `Origin`, seule la session compte et
un jeton est refusé). Le jeton se crée sur le serveur, il n'est montré qu'une fois :

```bash
python -m mika token create adrien --label "Unity, PC du salon"   # {"token": "mw_…", "person_id": "user_1", …}
python -m mika token list            # jamais le secret : à qui, à quoi il sert, son dernier usage
python -m mika token revoke 1        # il ne vaut plus rien ; ses connexions se ferment (4401)
```

Un jeton parle sous l'adresse de son compte (`user_1`, l'acteur `player:user_1`) : l'identité reste
authentifiée, comme depuis le navigateur. Le même jeton ouvre `/ws` (la conversation), aux mêmes conditions.

```json client
{"type": "hello", "protocol": "mika.world/1", "roles": ["viewer", "host"],
 "client": {"name": "Mika Unity", "version": "0.1.0", "engine": "unity"},
 "rev": 3, "after": 1520, "token": "mw_8f3c2b1e", "avatar": "avatars/default"}
```

`rev` : la révision de la définition qu'il a en cache ; `after` : le dernier `seq` qu'il a appliqué. Le noyau
répond :

```json serveur
{"type": "welcome", "protocol": "mika.world/1", "session": "s-7f2a", "granted": ["viewer", "host"],
 "actor": "player:user_1", "world": "maison", "rev": 3, "seq": 1544, "now": 1790000123000000}
```

puis, dans cet ordre : `definition` si le client n'a pas la révision `rev` (la définition entière) ;
`snapshot` si `after` est absent ou trop loin (ou si la définition vient de partir : une autre révision, c'est
un autre état), sinon les trames manquées depuis `after` ; `host` si le client a demandé le rôle d'hôte ; enfin
`presence` de la personne qui vient d'entrer (son corps apparaît au lieu `spawn` de la pièce où Mika se trouve,
ou à défaut au premier lieu `spawn` — P4). `welcome.seq` est le dernier événement qui a changé le monde : un
client à jour (`after` égal) ne reçoit rien de plus.

**Les rôles.**

| Rôle | Qui | Ce qu'il permet |
|---|---|---|
| `viewer` | tout compte autorisé à parler avec elle | montrer le monde ; `act`, `moved`, `address`, `answer`, `pose` pour le corps de la personne |
| `host` | un compte opérateur, un seul client à la fois | en plus : jouer les actions (`intent`), constater (`report`) |
| `creator` | un compte opérateur | `edit`, `describe` |

**Le bail d'hôte.** Accordé au premier client qui le demande et y a droit, pour `ttl_ms` (15 s), renouvelé
par chaque `ping` (toutes les 5 s). Un hôte qui se tait perd le bail ; le suivant qui le demande l'obtient.
Sans hôte, le monde continue : chaque action se termine à son `deadline`.

```json serveur
{"type": "host", "granted": true, "ttl_ms": 15000}
```

```json client
{"type": "ping", "t": 1790000128000000}
```

```json serveur
{"type": "pong", "t": 1790000128000000}
```

**Rattraper.** Les `seq` sont ceux du journal, qui porte toute sa vie (ses pensées, ses messages, ses nuits) :
d'une trame du monde à la suivante, ils **sautent**, et un écart ne dit rien. Sur une connexion ouverte, rien ne
se perd : un client trop lent est fermé (1013) plutôt que de sauter une trame. Un client qui revient (ou qui
doute) dit où il en est, par `hello.after` ou :

```json client
{"type": "sync", "after": 1544}
```

Au-delà de 500 événements du monde de retard, il reçoit un `snapshot` à la place — et aussi quand l'état a
changé sans action à rejouer entre-temps (elle s'est réveillée, une édition a déplacé ce qui n'avait plus sa
place), ou quand `after` est inconnu de ce journal (une sauvegarde restaurée). Un rattrapage peut redonner une
trame déjà en route : un client ignore ce dont le `seq` est déjà appliqué.

**Ce que la connexion garantit** (ADR 0051) :

- l'accusé d'abord : une commande acceptée reçoit son `result` (avec son `seq`), **puis** la trame qui l'applique ;
- un `snapshot` peut arriver à tout moment, sans qu'on l'ait demandé : il remplace tout l'état (le noyau en
  envoie un quand l'état change sans action à rejouer — le réveil au bord du lit, ce qu'une édition réconcilie) ;
- le bail attend : un opérateur qui demande `host` alors qu'il est pris reçoit `host` `granted: false`, puis
  `granted: true` dès que l'hôte le perd (silence, déconnexion) ; un hôte qui a perdu le bail le reprend par
  son prochain `ping`, s'il est libre ;
- pas encore : la `presence` de la personne qui entre, et son corps dans le monde (P4).

**Les erreurs de protocole** (`error`) : `bad_frame` (trame illisible : la phrase nomme le champ, et le `cmd`
s'il y en a un ; non fatale — fatale si ce n'est pas un objet JSON en texte, fermeture 1003), `hello_expected`
(la première trame, dans les 10 s ; fermeture 1008), `unauthorized` (pas d'identifiant valable, ou il a été
révoqué ; fermeture 4401, le client ne réessaie pas sans nouvel identifiant), `rate_limited` (un `sync` ou un
`ping` en trop ; une commande en trop reçoit son `result`), `too_slow` (fermeture 1013 : revenir par
`hello.after`), `shutdown` (le noyau s'arrête, fermeture 1001). Une `Origin` inconnue est refusée avant
l'ouverture (1008).

## 6. Mika agit

Elle décide en conversation ou d'elle-même (« attends, je vais chercher mon livre »). Le noyau valide (le livre
existe, il se porte, elle a une main libre, personne ne le tient), **planifie** les pas (se lever, marcher,
prendre) avec leurs durées nominales, réserve ce qu'elle va prendre ou occuper, et diffuse :

```json serveur
{"type": "intent", "seq": 1545, "intent": {"id": "i-1545", "actor": "mika",
  "started": 1790000124000000, "eta": 1790000131500000, "deadline": 1790000133500000,
  "cause": {"source": "mika", "actor": "mika", "episode": 1530},
  "steps": [
    {"kind": "posture", "posture": "stand", "duration_us": 1200000},
    {"kind": "walk", "to_room": "bedroom", "to_place": "bookshelf", "duration_us": 4800000},
    {"kind": "act", "object": "petit_prince", "action": "take", "duration_us": 1500000}]}}
```

- **L'hôte la joue** et le dit, pas à pas puis à la fin :

```json client
{"type": "report", "cmd": "r-88", "report": {"kind": "progress", "intent": "i-1545", "step": 1}}
```

```json client
{"type": "report", "cmd": "r-89", "report": {"kind": "finished", "intent": "i-1545", "outcome": "done"}}
```

- **Les autres écrans l'animent** avec le même plan et les mêmes durées (ils ne disent rien).
- **Le noyau la termine** et diffuse ce qu'elle a changé :

```json serveur
{"type": "intent_end", "seq": 1547, "intent": "i-1545", "actor": "mika", "outcome": "done", "changes": [
  {"kind": "actor_moved", "actor": "mika", "room": "bedroom", "place": "bookshelf", "posture": "stand"},
  {"kind": "object_moved", "object": "petit_prince", "to": {"kind": "held", "actor": "mika", "hand": "right"}}]}
```

- **L'hôte n'y arrive pas** (un passage bloqué, une animation impossible) : il le dit, avec où elle est
  vraiment. Le noyau termine l'action en échec, ne change que ce qui est vrai, et elle **le sait** (un signal :
  « tu n'as pas pu… ») :

```json client
{"type": "report", "cmd": "r-90", "report": {"kind": "finished", "intent": "i-1550", "outcome": "failed",
  "reason": "unreachable", "at": {"actor": "mika", "room": "bedroom", "place": "center"}}}
```

- **Sans hôte**, l'action se termine comme prévu à `deadline` (`eta` plus une marge).
- **Une nouvelle action interrompt la précédente** (`outcome: interrupted`) et repart d'où elle est ; une
  action demandée pendant qu'elle dort attend son réveil, sauf aller au lit.

Les **réflexes** sont des actions du noyau (`cause.source: reflex`) : elle s'endort → elle va au lieu `sleep`
et s'allonge ; elle se réveille → elle s'assied au bord ; elle travaille sur un projet → elle va au lieu
`work`. Ils passent par les mêmes trames. Un réflexe naît **avec** ce qui le cause : l'`intent` du coucher
porte le même `seq` que l'endormissement, et un client qui les reçoit ensemble la fait marcher jusqu'au lit
les yeux ouverts, puis s'endormir allongée — il ne doit pas l'endormir avant la fin du trajet.

## 7. Les joueuses agissent

Le corps d'une personne est piloté par son client : il marche librement (et relaie sa pose), et dit au noyau
où il **arrive** :

```json client
{"type": "moved", "cmd": "m-7", "room": "bedroom", "near": "desk"}
```

```json client
{"type": "pose", "t": 1790000141000000, "pos": {"x": 1.2, "y": 0.0, "z": 2.1}, "yaw": 3.0, "anim": "walk"}
```

```json serveur
{"type": "pose", "actor": "player:user_1", "t": 1790000141000000, "pos": {"x": 1.2, "y": 0.0, "z": 2.1},
 "yaw": 3.0, "anim": "walk"}
```

**Agir sur un objet** — la personne doit être arrivée près de lui (`moved`), et l'objet le lui permettre
(`access`). Ses actions sont instantanées pour le noyau (son client anime) :

```json client
{"type": "act", "cmd": "a-12", "action": "allumer", "object": "desk_lamp", "expect": 1547}
```

```json serveur
{"type": "result", "cmd": "a-12", "status": "accepted", "seq": 1548}
```

```json serveur
{"type": "delta", "seq": 1548, "at": 1790000140000000,
 "cause": {"source": "player", "actor": "player:user_1", "handle": "user_1"},
 "changes": [{"kind": "object_state", "object": "desk_lamp", "state": "on"}]}
```

```json client
{"type": "act", "cmd": "a-14", "action": "sit", "place": "bed"}
```

```json client
{"type": "act", "cmd": "a-15", "action": "put", "object": "poems", "target": {"kind": "on", "object": "shelves", "slot": 1}}
```

Un refus dit pourquoi, en français :

```json serveur
{"type": "result", "cmd": "a-13", "status": "refused", "code": "held_by_other",
 "message": "Mika tient « Le Petit Prince » : demande-le-lui."}
```

**Un geste** vers elle (ou vers quelqu'un) se fait sans accord ; elle le remarque, et le ressent selon qui le
fait (une tape sur la tête d'une proche ou d'une inconnue) :

```json client
{"type": "address", "cmd": "g-3", "to": "mika", "gesture": "wave"}
```

```json serveur
{"type": "gesture", "seq": 1549, "actor": "player:user_1", "gesture": "wave", "to_actor": "mika"}
```

**Une demande** attend l'accord de l'autre : tendre un objet (`offer`, ou `act` `give`), en demander un
(`ask`), un câlin, un « tope là », prendre la main, inviter à un lieu (`invite`) :

```json client
{"type": "address", "cmd": "q-4", "to": "mika", "request": "offer", "object": "cookie_1"}
```

```json serveur
{"type": "request", "seq": 1551, "request": {"id": "q-1551", "kind": "offer", "from_actor": "player:user_1",
  "to_actor": "mika", "object": "cookie_1", "expires": 1790000200000000}}
```

Une demande qui la vise est pour elle **une parole adressée** : elle y répond comme à un message (et accepte ou
non par son outil) ; une demande qui ne reçoit pas de réponse expire.

```json serveur
{"type": "request_end", "seq": 1553, "request": "q-1551", "answer": "accepted", "changes": [
  {"kind": "object_moved", "object": "cookie_1", "to": {"kind": "held", "actor": "mika", "hand": "left"}}]}
```

Quand c'est **elle** qui demande (elle te tend sa tasse, t'invite à t'asseoir), la personne répond :

```json client
{"type": "answer", "cmd": "y-1", "request": "q-1560", "accept": true}
```

**Entrer, sortir.** Une personne entre dans le monde quand son client s'y connecte, et en sort quand il se
déconnecte (ou ne se manifeste plus pendant 60 s) :

```json serveur
{"type": "presence", "seq": 1540, "actor": "player:user_1", "joined": true, "room": "bedroom", "place": "door",
 "asset": "avatars/default", "label": "Adrien"}
```

**Parler** passe par le protocole de conversation (`/ws`, inchangé) : dans le monde, une pièce où plusieurs
personnes se tiennent est un **salon** (ADR 0014) — elle entend tout ce qui s'y dit et ne dit rien de privé
devant qui ne doit pas l'entendre.

## 8. Le moteur constate, le créateur édite

**Constater** (hôte seulement). Un objet qui tombe, un personnage du moteur qui se déplace, un bruit, une
définition chargée :

```json client
{"type": "report", "cmd": "r-91", "report": {"kind": "settled", "object": "mug",
  "to": {"kind": "room", "room": "bedroom", "near": "desk"}}}
```

```json client
{"type": "report", "cmd": "r-92", "report": {"kind": "npc", "actor": "npc:moka", "room": "bedroom", "near": "bed",
  "activity": "nap"}}
```

```json client
{"type": "report", "cmd": "r-93", "report": {"kind": "sound", "sound": "rain", "room": "bedroom", "loudness": 0.3}}
```

```json client
{"type": "report", "cmd": "r-1", "report": {"kind": "loaded", "rev": 3, "missing_assets": ["props/guitar"]}}
```

Un constat est validé comme une action : un objet ne « tombe » que dans la pièce où il était, un objet tenu
par quelqu'un ne se pose pas tout seul, un personnage ne traverse pas un mur sans passage. Sinon :
`implausible`, et rien ne change.

**Éditer** (créateur). Un lot de changements sur la révision qu'on a lue (`base`) ; tout le lot passe ou rien :

```json client
{"type": "edit", "cmd": "e-5", "base": 3, "changes": [
  {"op": "put", "item": {"kind": "object", "id": "cactus", "archetype": "plant", "label": "un cactus",
   "home": {"kind": "room", "room": "bedroom", "near": "window"}, "state": "watered"}},
  {"op": "remove", "of": "object", "id": "cookie_2"}]}
```

```json client
{"type": "describe", "cmd": "e-6", "of": "object", "id": "plant",
 "text": "La plante qu'Adrien t'a offerte pour ton anniversaire.", "about": ["user_2"]}
```

```json serveur
{"type": "definition_delta", "seq": 1560, "base": 3, "rev": 4, "changes": [
  {"op": "remove", "of": "object", "id": "cookie_2"}]}
```

Elle **remarque** ce qui change chez elle : une plante qui apparaît, son lit déplacé, sa guitare qui n'est
plus là — comme elle remarquerait qu'on a touché à ses affaires.

## 9. Refus et erreurs

| Code | Sens |
|---|---|
| `unknown` | cet identifiant n'existe pas, ou plus |
| `unreachable` | pas de chemin jusque-là |
| `hands_full` / `not_holding` / `not_portable` | les mains, ce qu'on tient, ce qui se porte |
| `occupied` | le lieu est plein, la place est prise |
| `held_by_other` | quelqu'un d'autre le tient : on demande |
| `forbidden` | l'accès de l'objet ne le permet pas à cette personne |
| `wrong_state` / `wrong_posture` | déjà allumée, pas ouverte ; il faut être debout |
| `asleep` | elle dort : ce qu'on lui demande attend son réveil |
| `stale` | décidé sur un état ou une révision qui a changé depuis |
| `incoherent` | l'édition rendrait le monde incohérent |
| `implausible` | un constat que les règles du monde n'admettent pas |
| `not_host` / `not_creator` | le rôle manque |
| `rate_limited` | trop de commandes |
| `unsupported` | ce noyau ne sait pas encore faire ça (une commande d'une version plus récente du protocole) |

Une trame illisible ou interdite reçoit une erreur de protocole (`fatal` : la connexion se ferme) :

```json serveur
{"type": "error", "code": "bad_frame", "message": "trame illisible : champ inconnu « foo »", "fatal": false}
```

**Débits par connexion** (par seconde) : `act`, `moved`, `answer` 4 ; `address` 2 ; `report` 30 ; `edit`,
`describe`, `sync`, `ping` 1 ; `pose` 20 (une pose en trop est jetée sans réponse).

## 10. Côté moteur

**Les types.** Le schéma JSON du protocole (trames dans les deux sens, et la définition) se génère :

```bash
.venv/bin/python -c "import json; from mika.adapters.world.protocol import json_schema; \
print(json.dumps(json_schema(), ensure_ascii=False, indent=1))" > mika-world.schema.json
```

et donne les classes C# (NJsonSchema, quicktype) ou TypeScript.

**Un hôte Unity, dans l'ordre :**

1. Charger la définition : à chaque `asset` son prefab, à chaque `anchor` (ou identifiant d'objet) sa place
   dans la scène ; dire ce qui manque (`report` `loaded`).
2. Poser l'état (`snapshot`) sans rien jouer : chaque acteur à son lieu et dans sa posture, chaque objet à son
   emplacement, chaque action en cours à l'instant de son trajet.
3. Jouer chaque `intent` : navmesh pour `walk`, animations de posture, IK pour prendre et poser (la main va à
   l'objet, l'objet va à la main, puis à sa place de surface), `progress` à chaque pas, `finished` à la fin.
4. Appliquer `delta`, `intent_end`, `request_end` dans l'ordre des `seq` : ils font foi, même s'ils
   contredisent ce que la physique montrait.
5. Constater (`settled`, `npc`, `sound`) seulement ce qui change l'état discret, jamais une trajectoire.
6. Renouveler le bail (`ping` toutes les 5 s).

Un écran simple (le client web) n'a que le rôle `viewer` : il montre ce qu'il sait montrer et **ignore sans
planter** ce qu'il ne connaît pas (un objet sans modèle, une autre pièce) — sinon chaque nouveauté du monde se
paierait deux fois.

## Annexe — la définition complète

Le noyau envoie la définition entière dans une trame `definition` (`{"type": "definition", "world": …}`, le
contenu de [`examples/monde/chambre.json`](../examples/monde/chambre.json) pour l'exemple). Un client la garde
en cache par `rev`.
