"""Un compte du système est une personne, dès sa création.

Avant, un compte ne devenait quelqu'un qu'à sa première connexion par le chat : un
opérateur qui n'avait fait que la console restait « user_1 » partout (la fiche d'un
projet qu'il avait confié, le formulaire qui le modifiait refusait « personne
inconnue »), et sa fiche de personne répondait 404.

- le premier compte (amorce) et tout compte créé depuis la console existent comme
  personnes, authentifiées, sous leur nom affiché (sinon l'identifiant) ;
- renommer un compte renomme la personne (et un retour à l'ancien nom s'écrit aussi) ;
- un opérateur désactivé n'est plus propriétaire ;
- rejouer la synchronisation n'écrit rien de plus ;
- la fiche d'un projet nomme la personne, jamais « user_1 » ;
- les deux boutons de la console ajoutent un utilisateur (le chat, sans la console) ou un
  opérateur, et chacun est une personne dès l'ajout.
"""

from __future__ import annotations

import html

from mika.app.server import register_accounts
from mika.contracts import identity as identity_c
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture

ACCOUNTS = "/inspecteur/reglages/comptes"


def _identity(client, live, handle: str):
    return client.portal.call(lambda: _async(live.kernel.mind.frame().get(identity_c.IDENTITY(handle))))


async def _async(value):
    return value


def _registered(client, live) -> list:
    async def go():
        mind = live.kernel.mind
        return [mind.decode(e) for e in mind.store.read() if e.type == identity_c.REGISTERED.name]

    return client.portal.call(go)


def test_an_account_is_a_named_person_from_its_creation(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)  # « adrien », sans nom complet, jamais connecté au chat
    me = _identity(client, live, "user_1")
    assert me.known and me.authenticated and me.operator and me.name == "adrien"
    owners = client.portal.call(lambda: _async(live.kernel.mind.frame().get(identity_c.OWNERS)))
    assert "user_1" in owners
    person = client.get("/inspecteur/fiche/person/user_1")
    assert person.status_code == 200 and "adrien" in html.unescape(person.text)

    async def edit():
        await live.accounts.update(1, operator=True, active=True, full_name="Adrien Dupont")
        bea = await live.accounts.create("bea", "un-mot-de-passe-long", operator=True, full_name="Béa Martin")
        return bea

    bea = client.portal.call(edit)
    assert _identity(client, live, "user_1").name == "Adrien Dupont"
    assert _identity(client, live, bea.handle).name == "Béa Martin"
    listing = html.unescape(client.get("/inspecteur/reglages/comptes").text)
    assert "Adrien Dupont" in listing

    async def back_and_off():
        await live.accounts.update(1, operator=True, active=True, full_name="")  # retour à l'identifiant
        await live.accounts.update(bea.id, operator=True, active=False)

    client.portal.call(back_and_off)
    assert _identity(client, live, "user_1").name == "adrien"
    off = _identity(client, live, bea.handle)
    assert off.known and not off.operator  # désactivé : plus propriétaire
    before = len(_registered(client, live))
    again = client.portal.call(lambda: register_accounts(live.kernel, live.accounts))
    assert again == 0 and len(_registered(client, live)) == before  # rien de plus


def test_the_console_adds_a_user_or_an_operator_each_a_person_at_once(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    listing = html.unescape(client.get(ACCOUNTS).text)
    assert f"{ACCOUNTS}?nouveau=utilisateur" in listing and f"{ACCOUNTS}?nouveau=operateur" in listing
    form = html.unescape(client.get(f"{ACCOUNTS}?nouveau=utilisateur").text)
    assert "Ajouter un utilisateur" in form and 'name="role" value="utilisateur"' in form
    assert "Ajouter un opérateur" in html.unescape(client.get(f"{ACCOUNTS}?nouveau=operateur").text)

    def add(role: str, username: str, full_name: str):
        return client.post(ACCOUNTS, data={"csrf": client.cookies.get("csrftoken"), "action": "create", "role": role,
                                           "username": username, "full_name": full_name,
                                           "password": "une-phrase-assez-longue"})

    weak = client.post(ACCOUNTS, data={"csrf": client.cookies.get("csrftoken"), "action": "create",
                                       "role": "operateur", "username": "cam", "password": "12345678"})
    assert weak.status_code == 400 and 'name="role" value="operateur"' in html.unescape(weak.text)  # le rôle reste
    added = add("utilisateur", "bea", "Béa Martin")
    assert "Utilisateur ajouté" in html.unescape(added.text)
    assert "/inspecteur/fiche/person/user_2" in added.text  # la page du compte mène à sa fiche
    add("operateur", "dan", "")
    by_name = {a.username: a for a in client.portal.call(live.accounts.all)}
    assert not by_name["bea"].operator and by_name["dan"].operator
    bea, dan = _identity(client, live, by_name["bea"].handle), _identity(client, live, by_name["dan"].handle)
    assert bea.known and bea.authenticated and bea.name == "Béa Martin" and not bea.operator
    assert dan.known and dan.authenticated and dan.operator  # un opérateur est aussi propriétaire
    assert client.get(f"/inspecteur/fiche/person/{by_name['bea'].handle}").status_code == 200


def test_a_confided_project_names_its_person_and_can_be_modified_by_an_operator_who_never_chatted(world):  # noqa: F811
    import re

    client, live, _ = world
    bootstrap(client)
    client.portal.call(lambda: live.accounts.update(1, operator=True, active=True, full_name="Adrien Dupont"))
    token = client.cookies.get("csrftoken")
    fields = ["title", "description", "owner", "objectives", "constants", "cadence_hours", "mode", "schedule", "days",
              "start", "end", "runs_per_day", "priority", "approval", "remote", "branch"]
    done = client.post("/inspecteur/action/projects.creer", data={
        "csrf": token, "_op": "c1", "_retour": "/inspecteur/projets", "_sujet": "", "title": "Un projet",
        "description": "", "owner": "", "objectives": "Le premier pas", "constants": "", "cadence_hours": "0",
        "mode": "persona", "schedule": "manual", "days": "all", "start": "", "end": "", "runs_per_day": "0",
        "priority": "normal", "approval": "on", "remote": "", "branch": "main", "_champs": fields},
        follow_redirects=False)
    pid = done.headers["location"].split("/fiche/project/", 1)[1].split("?", 1)[0]
    behaviour = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}?onglet=comportement").text)
    assert "Adrien Dupont" in behaviour and "user_1" not in re.sub(r'(value|href|name)="[^"]*"', "", behaviour)
    form = behaviour[behaviour.find('action="/inspecteur/action/projects.modifier"') - 200:]
    form = form[:form.find("</form>")]
    posted: dict[str, list[str]] = {}
    for m in re.finditer(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form):
        posted.setdefault(m.group(1), []).append(m.group(2))
    posted |= {"csrf": [token], "title": ["Un projet mieux nommé"], "description": ["Le faire bien."],
               "owner": ["user_1"], "mode": ["persona"], "schedule": ["manual"], "days": ["all"], "start": [""],
               "end": [""], "runs_per_day": ["0"], "priority": ["high"], "approval": ["on"]}
    saved = client.post("/inspecteur/action/projects.modifier", data=posted, follow_redirects=False)
    assert saved.status_code == 303, re.findall(r'class="error"[^>]*>([^<]+)', saved.text)
    overview = html.unescape(client.get(f"/inspecteur/fiche/project/{pid}").text)
    assert "Un projet mieux nommé" in overview and "Le faire bien." in overview
