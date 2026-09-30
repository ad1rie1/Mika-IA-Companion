"""Courrier de démonstration : deux comptes, des dossiers, HTML et textes longs."""

from mika.ports.mail import AccountInfo, Attachment, Mail, Sent
from mika.sim.outside import FakeMail

PERSO = AccountInfo("perso", "Personnel", "adrien@example.test", ready=True, can_send=True)
PRO = AccountInfo("pro", "Atelier", "atelier@example.test", ready=True, can_send=True)
NOW = 1_790_790_000_000_000


def mailbox(count=32):
    box = FakeMail(boxes=[PERSO, PRO], now=lambda: NOW)
    for i in range(count):
        box.deliver(Mail(f"<perso-{i}@example.test>", "Camille <camille@example.test>", "camille@example.test",
                         f"Personnel · message {i:03}", NOW - i * 60_000_000,
                         "Bonjour Adrien,\n\nVoici les nouvelles de la semaine. On en reparle jeudi ?\n\nÀ bientôt,\nCamille",
                         account="perso", to=PERSO.address, seen=i % 3 == 0))
    box.deliver(Mail("<projet@example.test>", "Léa Martin <lea@example.test>", "lea@example.test",
                     "Maquettes du projet · retour pour jeudi", NOW + 60_000_000,
                     "Bonjour,\n\nVoici les maquettes.\n\n" + "Un paragraphe du message à lire intégralement.\n" * 30 +
                     "\nFIN DU MESSAGE LONG\n\nLe dossier : https://example.test/projet",
                     account="pro", to=PRO.address, cc="equipe@example.test",
                     attachments=(Attachment("maquettes.pdf", "application/pdf", 153600),), has_html=True,
                     html='<h1>Les maquettes sont prêtes</h1><p>Bonjour Adrien,</p>'
                          '<p>Voici les deux pistes retenues pour le projet. <strong>Ton retour jeudi</strong> nous permettrait de lancer la suite.</p>'
                          '<ul><li>Accueil : une navigation plus courte</li><li>Catalogue : des fiches plus lisibles</li></ul>'
                          '<p><a href="https://example.test/projet">Consulter le dossier du projet</a></p>'
                          '<blockquote>Peut-on garder une version mobile aussi simple ?</blockquote>'
                          '<p>Oui, elle est incluse dans les maquettes.<br>À bientôt,<br>Léa</p>'
                          '<img src="https://tracker.example.test/pixel" alt="Logo Atelier">'
                          '<script>window.mailExecuted=true</script>'))
    box.deliver(Mail("<archive@example.test>", "Léa <lea@example.test>", "lea@example.test", "Ancien devis",
                     NOW - 86_400_000_000, "Le devis validé.", account="pro", folder="Archives"))
    box.outgoing = [Sent("<sent-pro@example.test>", "lea@example.test", "Envoyé depuis Atelier", "Bien reçu !", NOW,
                         account="pro"),
                    Sent("<sent-perso@example.test>", "camille@example.test", "Envoyé depuis Personnel", "À jeudi.", NOW,
                         account="perso")]
    return box
