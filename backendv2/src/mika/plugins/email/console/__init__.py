"""La console du courrier : un vrai client, avec sa place dans la barre latérale.

- **Boîte** : ses comptes et leurs dossiers (des puces, les non-lus à côté),
  ce qui y est — filtré par état, expéditeur, recherche ; des gestes rapides
  (lu, suivi, archiver, corbeille, sur le serveur) ; ce qu'elle en a remarqué.
- **Brouillons** : ce qu'elle a préparé et qui attend ton accord — l'ouvrir
  montre exactement ce qui partira ; l'envoyer, le retoucher, le refuser.
- **Envoyés**, **Contacts**.
- **Comptes** : chaque boîte, son état, ses dossiers, sa voix ; les réglages
  (Réglages › Sens › Courrier) à un clic, et retour ici.
- **Les fiches** d'un mail, d'un brouillon, d'un compte, avec leurs actions.

Un mail est un texte venu d'ailleurs : il ne s'affiche qu'en texte (cellules,
``Prose``), jamais en balisage ni dans la clé d'un lien.
"""

from __future__ import annotations

from mika.plugins.email.console import accounts as accounts
from mika.plugins.email.console import actions as actions
from mika.plugins.email.console import box as box
from mika.plugins.email.console import drafts as drafts
from mika.plugins.email.console import mail as mail
from mika.plugins.email.console import outbox as outbox
from mika.plugins.email.console.actions import ReplyArgs, WriteArgs
from mika.plugins.email.console.common import mail_key

__all__ = ["ReplyArgs", "WriteArgs", "mail_key"]
