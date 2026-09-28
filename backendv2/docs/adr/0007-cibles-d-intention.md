# 0007 — Valider par des cibles d'intention, pas par parité avec la v1

**Contexte.** Le plan prévoyait de prouver l'affect de M1 « à parité avec les mesures de la v1 » et le protocole par des trames enregistrées sur une v1 en marche. Les mesures v1 venaient de tests unitaires au temps simulé à la main ; rien ne garantit que le système réel ait jamais produit ces comportements.

**Décision.** Chaque comportement se teste par une intention : ce qu'une personne ferait, pourquoi, avec une bande et un contre-exemple qui doit échouer (contrôle). Les chiffres de la v1 servent au plus d'ordre de grandeur, jamais d'assertion. Le contrat réseau se lit dans le code du frontend (ses types, son client WebSocket), pas dans des trames enregistrées.

**Conséquences.** Les tests d'affect disent « une tristesse soutenue déborde en quelques tours, à toute heure ; une joie ordinaire jamais ; résidu ≥ 50 % à 5 min, ≤ 10 % à 30 min » ; chaque bande est vérifiée non vide par mutation. Les politiques rédigées comme spécifications (divulgation graduée) et le contenu (persona) peuvent être repris : ce sont des décisions de produit, pas des mesures.
