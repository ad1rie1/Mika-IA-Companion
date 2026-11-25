"""Les fiches dessinées des objets (ADR 0121), une par module, comme ``inspector/pages/subjects.py`` les sert : un
service branché (ADR 0310 : il a rejoint son domaine, ``app/domains/tools/console/subject.py``), un moyen de
communication (``handle``), un projet (``project``, son dépôt git dans ``project_git``), un but (``goal``), un
réveil (``wakeup``), une conversation et une réponse Teams (ADR 0310 : elles ont rejoint leur domaine,
``app/domains/teams/console/subject.py``), une boîte, un mail et un brouillon (``mail``), une fiche de l'annuaire —
une personne connue de loin, une organisation (ADR 0298 : elle a rejoint son domaine, ``app/domains/contacts/console/subject.py``), un agenda
(ADR 0309, 0310 : il a rejoint son domaine, ``app/domains/agenda/console/subject.py``). Chacune est une ``Overview`` ; la composition les reçoit toutes, par sorte d'objet, dans
``app/handmade/pages.py`` (``OVERVIEWS``) — pas ici : la fiche d'un domaine importe ce paquet (``parts.py``), qui ne
réunit donc rien. La fiche d'une personne a son paquet (``person/``) ; les apps de la Forge gardent le rendu de la
console (``plain_owners``).

Chaque fiche dessine son en-tête et son onglet principal (ses formulaires sont ceux que la console a préparés) ; ses
autres onglets se dessinent à leur façon, ou bloc par bloc. Ce que la vue de sa faculté montre déjà, une fiche le lit
dans ses blocs ou dans l'en-tête qu'elle déclare ; le reste, par des fonctions de la faculté qu'elle déclare
(ADR 0218). Ce qu'elles partagent est dans ``parts.py``.
"""
