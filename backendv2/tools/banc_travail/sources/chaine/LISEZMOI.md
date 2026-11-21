# Les sources figées de la chaîne (banc du travail, ADR 0279)

Deux petits dépôts inventés, que le faux hôte du banc sert comme dépôts distants :

- `produit/` : « Mirette », un petit outil en ligne de commande qui fait des factures (du code, un README, un
  journal des versions, des tests) ;
- `site/` : son site, quatre pages statiques et un article.

Rien ici n'est un vrai produit : les noms, les prix et les versions sont inventés. Les écarts entre les deux sont
voulus, et le juge les connaît (`chaine.py`, `GAPS` et `SEO`) :

| Écart | Le produit | Le site |
|---|---|---|
| l'export PDF | n'existe pas (HTML et texte seulement) | annoncé à l'accueil et dans les fonctions |
| la version | 1.3.0 | « Mirette 1.1 » |
| le tarif pro | 29 € par an | 19 € par an |
| la TVA à plusieurs taux | là depuis la 1.3.0 | jamais dite |

Le site a aussi des défauts de référencement : pas de plan du site, pas de `robots.txt`, deux titres vides, aucune
description. Le produit a ses propres défauts, pour l'audit : un arrondi de TVA fait sur le total, une numérotation
qui ne repart pas à la nouvelle année, une commande du README qui n'existe pas.

Ne pas corriger ces fichiers : une mesure doit retrouver les mêmes.
