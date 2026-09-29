# 0014 — Interprètes de perception ; salons ; Telegram

**Contexte.** « Moi c'est Alice » ou « je ne suis pas Alice » doivent peser sur la réponse au message même. Un processus d'arrière-plan arriverait trop tard (ou pas, selon la course) ; un réducteur ne peut pas lire un texte (effaçable par l'oubli).

**Décision.**
1. *Interprètes* (`@faculty.interpret(type)`) : fonctions synchrones, sans modèle, qui lisent un message à son arrivée et rendent des brouillons. Le noyau les journalise **juste après la perception et avant de demander la réponse** : un jugement enregistré, jamais recalculé au rejeu. Une reprise après arrêt les rejoue (idempotents par clé).
2. *Adressé ou entendu* : une perception porte `addressed`. Dans un salon elle entend tout, mais ne répond qu'à ce qui lui parle (son nom, une réponse à son message) ; une perception non adressée n'attend pas de réponse et ne compte pas comme un contact.
3. *Un salon a son fil* : dans un salon, l'historique du prompt est le fil du salon (tout le monde l'a lu) ; en privé, le fil privé de la personne, toutes ses poignées reliées confondues si sa fiche est ouverte. Les extraits d'échanges suivent la même règle.
4. *Telegram* (`adapters/telegram/`) : liste blanche avant toute écriture (refus dit, espacé), limite par compte, un groupe est un salon public, la réponse part dans le salon d'où vient la question, seules les conversations privées deviennent des adresses où lui écrire. La livraison est routée par canal (`app/delivery.py`). La bibliothèque n'est chargée que si un jeton est configuré (`mika telegram token`).
