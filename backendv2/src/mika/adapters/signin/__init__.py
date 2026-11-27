"""Se connecter à un compte Microsoft ou Google (ADR 0166, 0238, 0309, 0318) : une pièce du cadre, que plusieurs
domaines partagent — aucun ne l'emprunte à un autre.

- ``microsoft.py`` : le code d'appareil de Microsoft (``MicrosoftSignIn``), son renouvellement, ses refus en mots, et
  ce qui vaut pour une application Microsoft (celle que Mika livre, ``DEFAULT_APPLICATION`` ; ``application_id``,
  ``tenant_id``) ;
- ``google.py`` : la connexion Google par PKCE (``GoogleSignIn``), l'application Google du serveur
  (``GoogleApplication``, ``google_client_id``) et ce qu'on colle au retour (``pasted``) ;
- ``grants.py`` : ce qu'on garde d'une connexion (``Grant``) et où un domaine le garde (``GrantStore``) — les deux
  moteurs le lisent, sans que l'un lise l'autre.

Chaque domaine qui s'en sert donne sa portée, ses connexions (ses jetons, scellés dans ses réglages sous sa clé), ses
mots, et pour Google sa route de retour et ses erreurs : le courrier (``adapters/mail/oauth.py::mail_signin``),
l'agenda (``adapters/agenda/oauth.py::microsoft_signin``, ``google_signin``). Où en est une connexion se dit dans
``ports/signin.py``. Ce paquet ne nomme aucun domaine (``tests/architecture/test_frame_names_no_domain.py``).
"""
