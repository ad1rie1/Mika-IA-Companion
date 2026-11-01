"""Le courrier au quotidien (ADR 0175) : ton non-lu et sa lecture à part, ses images distantes permises par
expéditeur, et ce que le cadre en garde."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from mika.adapters.mail import MailConfig
from mika.adapters.mail.client import ImapSmtpMail
from mika.inspector.framed import FRAME_CSP, FRAME_CSP_REMOTE, Documents, framed_html
from mika.plugins.email import EmailParams, EmailState, MailRead, Seen, _read
from mika.plugins.email.console.common import her_badge, state_badge, to_answer, unread
from mika.ports.mail import Mail

REF = "perso:<m1@exemple.fr>"


def seen(needs_reply: bool = True, **more) -> Seen:
    return Seen(1, "Léa <lea@exemple.fr>", "lea@exemple.fr", 0.9, needs_reply, 0, "", **more)


def read(state: EmailState, **data) -> Seen:
    return _read(state, SimpleNamespace(data=MailRead(mail=REF, **data)), None).mails[REF]


def test_what_she_read_is_hers_and_never_leaves_your_unread():
    state = EmailState(mails=EmailState().mails.set(REF, seen()))
    assert read(state).by_her and read(state, how="archivé").by_her  # un de ses outils, sans opérateur
    assert not read(state, by="user_1").by_her  # la console
    assert not read(state, how="ailleurs").by_her and not read(state, how="répondu").by_her  # un autre client
    mail = Mail("<m1@exemple.fr>", "Léa <lea@exemple.fr>", "lea@exemple.fr", "Devis", 0, "…", account="perso")
    hers = read(state)
    assert unread(mail, hers)  # elle l'a lu, pas toi : il reste dans tes non-lus
    assert state_badge(hers, mail, EmailParams()).text.startswith("important, non lu")
    assert her_badge(hers).text == "lu par elle" and her_badge(read(state, how="archivé")).text == "archivé par elle"
    assert her_badge(read(state, by="user_1")) is None and her_badge(seen()) is None
    assert not unread(replace(mail, seen=True), hers)  # lu sur le serveur : par toi
    assert to_answer(hers) and not to_answer(seen(how="répondu")) and not to_answer(seen(needs_reply=False))


def test_remote_images_load_only_when_allowed_and_nothing_else_comes_in():
    source = ('<p>Bonjour</p><img src="https://cdn.exemple.fr/logo.png" alt="Logo">'
              '<img src="javascript:alert(1)" alt="Piège"><img src="ftp://exemple.fr/x.png" alt="Autre">'
              '<img srcset="https://cdn.exemple.fr/2x.png 2x" alt="Double"><td background="https://exemple.fr/f.png">')
    masked = framed_html(source)
    assert "cdn.exemple.fr" not in masked and "Logo" in masked  # son texte de remplacement (ADR 0169)
    shown = framed_html(source, remote=True)
    assert 'src="https://cdn.exemple.fr/logo.png"' in shown
    for never in ("javascript:", "ftp://", "srcset", "background="):
        assert never not in shown
    assert "img-src data: https: http:;" in FRAME_CSP_REMOTE and "img-src data:;" in FRAME_CSP
    assert FRAME_CSP_REMOTE.replace("img-src data: https: http:;", "img-src data:;") == FRAME_CSP  # rien d'autre
    kept = Documents()
    once, always = kept.keep(source), kept.keep(source, remote=True)
    assert once != always and kept.get(always).remote and not kept.get(once).remote


class Stored:
    """Les réglages, pour la liste des expéditeurs dont on affiche les images."""

    def __init__(self) -> None:
        self.addresses: tuple[str, ...] = ()

    def mail_images(self) -> tuple[str, ...]:
        return self.addresses

    async def save_mail_images(self, addresses: tuple[str, ...]) -> None:
        self.addresses = addresses


def test_a_trusted_sender_is_kept_in_the_settings_and_forgotten_with_its_correspondent(tmp_path):
    stored = Stored()
    box = ImapSmtpMail(lambda: MailConfig(), tmp_path / "mail.db", images=stored)
    asyncio.run(box.show_images(" Lea@Exemple.fr ", True))
    asyncio.run(box.show_images("news@exemple.fr", True))
    assert stored.addresses == ("news@exemple.fr", "lea@exemple.fr")  # le plus récent d'abord, en minuscules
    assert box.images_shown("LEA@exemple.fr") and not box.images_shown("autre@exemple.fr")
    asyncio.run(box.show_images("news@exemple.fr", False))
    assert stored.addresses == ("lea@exemple.fr",)
    asyncio.run(box.forget("mail:lea@exemple.fr"))  # oublier le correspondant l'en retire
    assert stored.addresses == () and not box.images_shown("lea@exemple.fr")
    nowhere = ImapSmtpMail(lambda: MailConfig(), tmp_path / "autre.db")
    assert not nowhere.images_shown("lea@exemple.fr")
    try:
        asyncio.run(nowhere.show_images("lea@exemple.fr", True))
    except RuntimeError as exc:
        assert "retenir" in str(exc)
    else:
        raise AssertionError("sans réglages où le garder, rien ne se retient")
