# Mirette

Des factures en une commande, sans tableur ni abonnement. Mirette lit une facture décrite dans un fichier JSON et
l'écrit en HTML ou en texte brut, prête à envoyer.

Version courante : **1.3.0** (voir `CHANGELOG.md`).

## Ce qu'elle fait

- calcule les totaux hors taxes, la TVA et le total à payer ;
- gère **plusieurs taux de TVA** sur une même facture (depuis la 1.3.0) ;
- numérote les factures à la suite, par année (`2026-0042`) ;
- exporte en **HTML** et en **texte brut**. Il n'y a pas d'export PDF : on imprime le HTML en PDF depuis le
  navigateur.

## Installer

    pip install mirette

Python 3.10 ou plus récent, aucune dépendance.

## S'en servir

    mirette facture exemple.json --format html > facture.html
    mirette facture exemple.json --format texte
    mirette nouvelle client.json        # prépare une facture vide pour ce client

Un fichier de facture :

    {"numero": "2026-0042", "client": "Atelier Bravard", "lignes": [
      {"libelle": "Pose d'une étagère", "quantite": 2, "prix": 45.0, "tva": 20},
      {"libelle": "Livre de comptes", "quantite": 1, "prix": 12.5, "tva": 5.5}]}

## Tarifs

Mirette est gratuite pour un usage personnel. Pour un usage professionnel, la licence coûte **29 € par an** et par
entreprise, quel que soit le nombre de postes.

## Développer

    python3 -m unittest discover -s tests

Le code est dans `mirette/` : `facture.py` (les calculs), `export.py` (les sorties), `cli.py` (la commande).
