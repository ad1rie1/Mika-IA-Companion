"""Courrier fictif de l'aperçu ; uniquement le port simulé, aucun serveur distant."""

from collections.abc import Callable

from mika.kernel.clock import HOUR, MINUTE
from mika.ports.mail import AccountInfo, Attachment, Draft, Mail, Sent
from mika.sim.outside import FakeMail


def mailbox(clock: Callable[[], int]) -> FakeMail:
    box = FakeMail(now=clock, boxes=[
        AccountInfo("perso", "Personnel", "mika@example.net", ready=True, can_send=True),
        AccountInfo("atelier", "Atelier", "atelier@example.net", ready=True, can_send=True),
    ])
    now = clock()
    messages = [
        ("stream", "Béa", "bea", "Le programme du prochain stream", "perso",
         "Salut,\n\nOn pourrait présenter le projet, puis prendre les questions du chat. Tu me prépares un petit programme ?\n\nÀ bientôt !\nBéa"),
        ("maquettes", "Léa Martin", "lea", "Maquettes du projet : ton retour pour jeudi", "atelier",
         "Bonjour,\n\nVoici les deux pistes retenues : une navigation plus courte et des fiches plus lisibles. Ton retour jeudi nous permettrait de lancer la suite.\n\nLa version mobile est incluse.\nÀ bientôt,\nLéa"),
        ("atelier", "Camille", "camille", "Un moment pour préparer l’atelier ?", "atelier",
         "Bonjour,\n\nJe suis disponible vendredi après-midi pour préparer les supports. On peut commencer par les exemples.\n\nCamille"),
        ("lecture", "Béa", "bea", "Quelques idées de lecture", "perso",
         "Coucou,\n\nJ’ai retrouvé les références dont on parlait hier. Je te les montrerai pendant notre prochain échange.\n\nBonne journée !"),
        ("bilan", "Léa Martin", "lea", "Bilan de la semaine", "atelier",
         "Bonjour,\n\nLes premières maquettes sont validées. Il reste à relire les textes et à vérifier les petits écrans.\n\nLéa"),
        ("archive", "Camille", "camille", "Notes de notre dernier échange", "perso",
         "Les notes du dernier atelier, pour les retrouver facilement."),
    ]
    for i, (key, name, address, subject, account, body) in enumerate(messages):
        html = ("<h2>Les maquettes sont prêtes</h2><p>Bonjour,</p>"
                "<p>Voici les deux pistes retenues. <strong>Ton retour jeudi</strong> nous permettra de lancer la suite.</p>"
                "<ul><li>Une navigation plus courte</li><li>Des fiches plus lisibles</li></ul>"
                "<p>La version mobile est incluse.<br>À bientôt,<br>Léa</p>") if key == "maquettes" else ""
        box.deliver(Mail(f"<{key}@example.net>", f"{name} <{address}@example.net>", f"{address}@example.net",
                         subject, now - (i * 32 + 5) * MINUTE, body, account=account,
                         to="atelier@example.net" if account == "atelier" else "mika@example.net",
                         folder="Archives" if key == "archive" else "INBOX", seen=i >= 3, flagged=key == "maquettes",
                         html=html, has_html=bool(html),
                         attachments=(Attachment("maquettes.pdf", "application/pdf", 153600),) if html else ()))
    box.outgoing.append(Sent("<envoye@example.net>", "lea@example.net", "Re: Bilan de la semaine",
                             "Merci Léa, je relirai les textes avant jeudi.", now - HOUR, account="atelier"))
    box.save_draft(Draft("stream", "perso", "bea@example.net", "Le programme du prochain stream",
                        "Salut Béa,\n\nJ’ai préparé les idées pour le prochain stream : une courte présentation du projet, puis un échange avec le chat.\n\nDis-moi si tu veux ajouter un sujet.\nÀ bientôt !",
                        reply_to="perso:<stream@example.net>", quote=False))
    return box
