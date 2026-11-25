"""Les fiches dessinées des objets (ADR 0121), une par module, comme ``inspector/pages/subjects.py`` les sert : un
service branché (``server``), un moyen de communication (``handle``), un projet (``project``, son dépôt git dans
``project_git``), un but (``goal``), un réveil (``wakeup``), une conversation et une réponse Teams (``teams``), une
boîte, un mail et un brouillon (``mail``), une fiche de l'annuaire — une personne connue de loin, une organisation
(ADR 0298 : elle a rejoint son domaine, ``app/domains/contacts/console/subject.py``), un agenda (``agenda``,
ADR 0309). Chacune est une ``Overview`` ; la composition les reçoit toutes, par sorte d'objet, dans
``app/handmade/pages.py`` (``OVERVIEWS``) — pas ici : la fiche d'un domaine importe ce paquet (``parts.py``), qui ne
réunit donc rien. La fiche d'une personne a son paquet (``person/``) ; les apps de la Forge gardent le rendu de la
console (``plain_owners``).

Chaque fiche dessine son en-tête et son onglet principal (ses formulaires sont ceux que la console a préparés) ; ses
autres onglets se dessinent à leur façon, ou bloc par bloc. Ce que la vue de sa faculté montre déjà, une fiche le lit
dans ses blocs ou dans l'en-tête qu'elle déclare ; le reste, par des fonctions de la faculté qu'elle déclare
(ADR 0218). Ce qu'elles partagent est dans ``parts.py``.
"""
