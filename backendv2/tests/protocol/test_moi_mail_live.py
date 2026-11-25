"""Le courrier en direct (ADR 0308), par le vrai serveur et le faux serveur IMAP qui sait attendre :

- un mail arrivé pendant l'attente est rangé, et la trame ``mail`` part à l'écran de qui voit sa boîte — à personne
  d'autre ;
- il est rangé même quand rien d'elle ne tourne (son ordonnanceur arrêté : endormie, elle n'en fait pas plus), sans
  qu'elle le remarque ;
- sa relève, à son rythme, remarque chaque mail rangé une fois, une seule.

Le serveur ne démarre son courrier en direct que s'il sert pour de bon (``serving``, que ``serve`` passe) : les autres
tests qui règlent des boîtes ne joignent ainsi aucun serveur.
"""

from __future__ import annotations

import ast
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import Gateway
from mika.adapters.mail import MailAccount, MailConfig
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.domains.mail.settings import MailSettings
from mika.app.server import build
from mika.contracts import email as email_c
from mika.kernel.registry import ArbitrationPolicy
from mika.plugins.email import POLL_ASKED
from mika.vocab.episodes import VOICE_ROLES
from tests.fixtures.mail_servers import Imap, raw_mail, serve
from tests.protocol.test_moi_changes import SETTLED_S, changes, lea_session, received
from tests.protocol.test_moi_mail import append, journal
from tests.protocol.test_web import ORIGIN, WS, Echo, bootstrap

ARRIVED = "pro:<mail-9@exemple.fr>"
SRC = Path(__file__).resolve().parents[2] / "src" / "mika"


@pytest.fixture
def served(tmp_path) -> Iterator[tuple[TestClient, object, int]]:
    Imap.reset({3: raw_mail(3, "Coucou", "Tu viens samedi ?")}, caps="IMAP4rev1 MOVE UIDPLUS IDLE")
    imap = serve(Imap)
    roles = {str(r): "fake" for r in VOICE_ROLES}
    gateway = LiveGateway(Gateway({"fake": Echo()}, roles, clock=RealClock(), voice_roles=frozenset(roles),
                                  slots={"fake": 1}))
    app, live = build(tmp_path / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                      arbitration=ArbitrationPolicy(), reply_wait=None, serving=True)
    try:
        with TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN}) as client:
            yield client, live, imap.server_address[1]
    finally:
        Imap.cut()
        imap.shutdown()
        imap.server_close()


def eventually(cond: Callable[[], object], timeout: float = 8.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "trop long"
        time.sleep(0.02)


def plug(client, live, port: int) -> None:
    """La boîte « pro », « à toi » (à ses propriétaires), sur le faux serveur : enregistrée, elle est observée."""
    box = MailAccount(address="atelier@exemple.fr", imap_host="127.0.0.1", imap_port=port, imap_ssl=False,
                      user="atelier", password="secret", since_days=7)
    client.portal.call(live.settings.of(MailSettings).save_email, MailConfig(accounts={"pro": box}))
    eventually(lambda: Imap.waiting() == 1)


def kept(client, live, ref: str) -> bool:
    port = live.kernel.ports["mail"]
    return client.portal.call(lambda: port.cached_one(ref)) is not None


def noticed(live, ref: str) -> int:
    return sum(1 for e in journal(live, email_c.NOTICED) if e.data.mail == ref)


def test_a_mail_that_arrives_reaches_whoever_sees_its_box_and_no_one_else(served):
    client, live, port = served
    bootstrap(client)  # Adrien : une des propriétaires, à qui est « pro » (« à toi »)
    session = lea_session(client, live)  # Léa : un compte, pas une propriétaire
    plug(client, live, port)
    with client.websocket_connect(WS) as adrien, \
            client.websocket_connect(WS, headers={"cookie": f"sessionid={session}"}) as lea:
        time.sleep(SETTLED_S)
        received(adrien, 1), received(lea, 1)  # ce que dit une ouverture
        Imap.deliver(raw_mail(9, "Maquettes", "Tu as vu les deux pistes ?"))
        eventually(lambda: kept(client, live, ARRIVED))
        time.sleep(SETTLED_S)
        his, hers = changes(received(adrien, 2)), changes(received(lea, 2))
    assert {"topic": "mail", "boxes": ["pro"]} in his
    assert "Maquettes" not in str(his)  # jamais le contenu
    assert hers == []  # la boîte d'un autre n'existe pas pour elle, même dans un avis
    assert noticed(live, ARRIVED) == 0  # rangé, pas remarqué : sa relève n'est pas venue


def test_her_poll_notices_each_ranged_mail_once(served):
    client, live, port = served
    bootstrap(client)
    plug(client, live, port)
    Imap.deliver(raw_mail(9, "Maquettes", "Tu as vu les deux pistes ?"))
    eventually(lambda: kept(client, live, ARRIVED))
    assert noticed(live, ARRIVED) == 0
    # sa relève (demandée, comme « Relever » dans la console) : chacun une fois
    append(client, live, [POLL_ASKED.draft(by="")], emitter="email")
    eventually(lambda: noticed(live, ARRIVED) == 1)
    Imap.deliver(raw_mail(10, "Encore", "Et la troisième ?"))
    eventually(lambda: kept(client, live, "pro:<mail-10@exemple.fr>"))
    append(client, live, [POLL_ASKED.draft(by="")], emitter="email")
    eventually(lambda: noticed(live, "pro:<mail-10@exemple.fr>") == 1)
    assert noticed(live, ARRIVED) == 1 and noticed(live, "pro:<mail-3@exemple.fr>") == 1


def test_a_mail_is_ranged_even_when_nothing_of_hers_runs(served):
    client, live, port = served
    bootstrap(client)
    live.kernel.scheduler.stop()  # ni sa relève, ni son sommeil, ni rien de ce qu'elle fait d'elle-même
    plug(client, live, port)
    with client.websocket_connect(WS) as adrien:
        time.sleep(SETTLED_S)
        received(adrien, 1)
        Imap.deliver(raw_mail(9, "Cette nuit", "Tu dors ?"))
        eventually(lambda: kept(client, live, ARRIVED))
        time.sleep(SETTLED_S)
        his = changes(received(adrien, 2))
    assert {"topic": "mail", "boxes": ["pro"]} in his
    port_ = live.kernel.ports["mail"]
    assert ARRIVED in client.portal.call(port_.waiting)  # il attend son tri, à son réveil
    assert noticed(live, ARRIVED) == 0
    boxes = client.get("/api/moi/mail/boxes").json()["boxes"]
    pro = next(b for b in boxes if b["key"] == "pro")
    assert pro["last_poll"] > 0 and not pro["error"]  # rangé : compté comme une relève


def test_only_the_real_server_watches_the_mail():
    """Seul ``serve`` dit que le serveur sert pour de bon, et seul le câblage du courrier construit son courrier en
    direct : ni une commande, ni la sonde, ni l'aperçu de la console n'ouvrent de connexion IMAP d'eux-mêmes (lu dans
    le source, par l'AST). Relayer ce qu'on a reçu (``serving=serving``, de ``build`` au câblage) n'est pas le dire."""
    asking: set[tuple[str, str]] = set()
    making: set[str] = set()

    def says(value: ast.expr) -> bool:
        relayed = isinstance(value, ast.Name) and value.id == "serving"
        return not relayed and not (isinstance(value, ast.Constant) and value.value is False)

    for path in SRC.rglob("*.py"):
        where = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)):
            for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
                if any(k.arg == "serving" and says(k.value) for k in call.keywords):
                    asking.add((where, fn.name))
                named = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")
                if named == "MailWatch":
                    making.add(where)
    assert asking == {("app/server.py", "serve")}
    assert making == {"app/domains/mail/wiring.py"}
