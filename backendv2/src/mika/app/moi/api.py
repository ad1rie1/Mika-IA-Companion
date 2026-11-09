"""Le cadre de l'API par personne (ADR 0187) : qui est connecté, ce qu'une route reçoit, comment elle refuse, comment
une route se déclare. Les modules (``mail``, ``teams``…) l'importent d'ici ; le paquet les réunit (``mika.app.moi``).

Qui demande est lu par ``adapters.web.session`` (le jeton d'un client natif sans ``Origin``, sinon la session) : c'est
la même lecture que le transport web.
"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mika.adapters.web.accounts import Account, Accounts
from mika.adapters.web.app import (
    BODY_MAX_BYTES,
    LoginThrottle,
    PayloadTooLarge,
    bounded_stream,
    read_bounded,
)
from mika.adapters.web.session import account_of, csrf_header_ok, native_token
from mika.contracts import identity as identity_c
from mika.kernel.forms import RENDERED, errors_fr
from mika.ports.mail import PIECES_MAX, PIECES_TOTAL_MAX, File
from mika.runtime.bootstrap import Kernel
from mika.runtime.operations import FIXED_FIELD, SPACE, Outcome, perform

#: où vit l'API
PREFIX = "/api/moi"
#: une réponse de l'API ne se garde nulle part : elle dit ce qui est à quelqu'un
NO_STORE = {"Cache-Control": "no-store"}
#: changer son mot de passe : au plus tant d'essais par compte dans la fenêtre (les bornes de ``/auth/login`` ; un essai
#: réussi est rendu)
PASSWORD_TRIES = (5, 60.0)
#: tester une boîte ou un service, relever ses boîtes (un clic les relève toutes) : au plus tant de fois par compte dans
#: la fenêtre, car chaque essai fait joindre un serveur au moteur
PROBES = (30, 60.0)
#: ce qui fait sortir une demande vers un service du dehors pour la carte (un itinéraire, une adresse, un ordre,
#: un GPX) : au plus tant par compte dans la fenêtre. Le serveur d'itinéraires public (une demande par seconde pour
#: tout ce serveur) reste ainsi à tous, et à ses outils à elle : une seule personne ne le tient pas. Le GPX qu'un
#: opérateur tire de la console compte dans la borne de son compte, la même (``spend``, ADR 0204).
OUTBOUND = (20, 60.0)
#: une demande de trop vers le serveur d'itinéraires (``OUTBOUND``), dans l'écran Carte comme dans la console
ROUTES_BUSY = "Trop de trajets demandés d'affilée : attends une minute."
#: une adresse cherchée, à la Géoplateforme (qui en permet 50 par seconde) : au plus tant par compte dans la fenêtre —
#: une saisie en cours en demande plusieurs, sans priver qui que ce soit du serveur d'itinéraires
ADDRESSES = (60, 60.0)
#: ce qu'une personne qui n'est pas opératrice branche à elle : au plus tant de boîtes, de comptes Teams, de services
OWN_MAX = 10
#: les créations dont on garde la réponse, pour qu'une création redite avec la même clé ne refasse rien
CREATED_MAX = 512
#: un envoi avec ses fichiers (``upload``), corps entier : ses pièces, et de quoi porter ses champs et ses délimiteurs
UPLOAD_BODY_MAX = PIECES_TOTAL_MAX + 1024 * 1024
#: les champs d'un envoi avec ses fichiers : ceux d'un mail, avec de la marge (chacun est borné par ``Call.arg``)
UPLOAD_FIELDS = 32


class Denied(Exception):
    """Un refus à rendre tel quel : son statut HTTP et ce qu'il dit, en français."""

    def __init__(self, status: int, message: str, fields: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.fields = dict(fields or {})


#: ce qu'on ne trouve pas, ou qui n'est pas à qui demande : une seule réponse, qui ne dit pas laquelle
NOT_FOUND = "Introuvable."


def missing() -> Denied:
    return Denied(404, NOT_FOUND)


def refused(exc: Exception) -> Denied:
    """Un réglage refusé (400), dit en mots : pour pydantic, chaque champ et ce qu'il demande — jamais la dernière ligne
    de son message, l'adresse de sa documentation ; sinon, la première ligne de l'erreur."""
    if isinstance(exc, ValidationError):
        said = " ; ".join(f"{path} : {message}" if path else message for path, message in errors_fr(exc).items())
    else:
        said = (str(exc).splitlines() or [""])[0]
    return Denied(400, said[:300] or "Réglage refusé.")


def spend(throttle: LoginThrottle, account: Account) -> bool:
    """Une demande de plus pour ce compte dans ``throttle`` ; faux, sans rien compter, s'il est à sa borne. La clé est
    le compte : l'écran Carte et la console (le GPX d'un voyage, ADR 0204) usent ainsi la même borne ``OUTBOUND``."""
    key = f"compte:{account.id}"
    if throttle.blocked(key):
        return False
    throttle.fail(key)
    return True


@dataclass(frozen=True, slots=True)
class Me:
    """Qui est connecté : son compte, sa personne, et si elle est une de ses propriétaires."""

    account: Account
    #: la clé de sa personne (``identity.person`` de son adresse ; l'adresse elle-même si rien ne l'a reliée)
    person: str
    #: une de ses propriétaires : ce qui est « à toi » (sans propriétaire nommé) est à elle
    owner: bool

    @property
    def handle(self) -> str:
        return self.account.handle

    @property
    def name(self) -> str:
        return self.account.display_name

    @property
    def operator(self) -> bool:
        return self.account.operator


def person_of(frame: Any, handle: str) -> str:
    """La personne derrière une adresse, telle que l'identité la relie maintenant."""
    return str(frame.get(identity_c.PERSON(handle)) or handle)


def me_of(frame: Any, account: Account) -> Me:
    person = person_of(frame, account.handle)
    return Me(account, person, person in set(frame.get(identity_c.OWNERS) or ()))


def form(fixed: Mapping[str, str] | None = None, **values: Any) -> dict[str, list[str]]:
    """Une soumission telle que la console l'enverrait (``kernel.forms`` : chaque valeur une liste, les champs rendus
    nommés dans ``_champs``) : un booléen faux est absent, une suite donne une valeur par élément. ``fixed`` : les
    champs cachés (l'objet visé : un brouillon, le mail auquel on répond), que la page pose et que personne ne tape —
    nommés dans ``_fixes``, jamais parmi les champs rendus."""
    out: dict[str, list[str]] = {RENDERED: list(values)}
    if fixed:
        out[FIXED_FIELD] = list(fixed)
        out.update({key: [str(value)] for key, value in fixed.items()})
    for key, value in values.items():
        if isinstance(value, bool):
            out[key] = ["1"] if value else []
        elif isinstance(value, list | tuple):
            out[key] = [str(v) for v in value]
        elif value is None:
            out[key] = []
        else:
            out[key] = [str(value)]
    return out


def done(outcome: Outcome, **more: Any) -> dict[str, Any]:
    """Ce qu'une action a donné, ou le refus qu'elle a dit (400, ses messages par champ)."""
    if not outcome.ok:
        raise Denied(400 if outcome.errors else 409, outcome.message, outcome.errors)
    return {"ok": True, "message": outcome.message, "deduped": outcome.deduped, **more}


class Call:
    """Ce qu'une route reçoit : la requête, qui la fait, le noyau, et le corps JSON lu (``{}`` pour une lecture)."""

    __slots__ = ("request", "me", "kernel", "data", "api", "files")

    def __init__(self, request: Request, me: Me, kernel: Kernel, data: dict[str, Any], api: MeApiBase,
                 files: tuple[File, ...] = ()) -> None:
        self.request = request
        self.me = me
        self.kernel = kernel
        self.data = data
        #: les fichiers d'un envoi en multipart (``upload``), tels qu'ils sont arrivés : l'action qui les joint les juge
        self.files = files
        #: l'API (ses comptes, ses origines, où est l'application du téléphone)
        self.api = api

    @property
    def frame(self) -> Any:
        return self.kernel.mind.frame()

    def port(self, name: str) -> Any:
        """Un port du monde, lu à chaque requête (un test, une reconfiguration le remplacent)."""
        return self.kernel.ports.get(name)

    def arg(self, name: str, default: str = "", limit: int = 500) -> str:
        """Un paramètre de la requête (``?nom=``), sinon du corps : une chaîne, refusée au-delà de sa borne — jamais
        coupée (un destinataire, un texte tronqué partiraient sans rien dire)."""
        raw = self.request.query_params.get(name)
        if raw is None:
            raw = self.data.get(name, default)
        if raw is None:
            return default
        if isinstance(raw, bool | int | float):
            raw = str(raw)
        if not isinstance(raw, str):
            raise Denied(400, f"« {name} » : une chaîne.", {name: "une chaîne"})
        if len(raw) > limit:
            raise Denied(400, f"« {name} » : {limit} caractères au plus.", {name: f"{limit} caractères au plus"})
        return raw

    def flag(self, name: str) -> bool:
        raw = self.request.query_params.get(name)
        got: Any = raw if raw is not None else self.data.get(name)
        return got is True or (isinstance(got, str) and got.lower() in ("1", "true", "oui", "on"))

    def number(self, name: str, default: int, low: int = 1, high: int = 1_000_000) -> int:
        raw = self.request.query_params.get(name)
        got: Any = raw if raw is not None else self.data.get(name, default)
        try:
            value = int(got)
        except (TypeError, ValueError):
            raise Denied(400, f"« {name} » : un nombre.") from None
        return max(low, min(high, value))

    def strings(self, name: str, limit: int = 100, size: int = 500) -> list[str]:
        """Une liste de chaînes du corps (``refs``…), bornée en nombre et en taille."""
        raw = self.data.get(name)
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            raise Denied(400, f"« {name} » : une liste de chaînes.")
        if len(raw) > limit:
            raise Denied(400, f"« {name} » : {limit} au plus.")
        return [x[:size] for x in raw]

    def nonce(self) -> str:
        """La clé d'un envoi (un double clic ne refait rien) : ``Idempotency-Key``, sinon ``nonce`` dans le corps."""
        given = self.request.headers.get("idempotency-key") or self.data.get("nonce") or ""
        cleaned = "".join(ch for ch in str(given) if ch.isalnum() or ch in "-_.")[:80]
        return f"moi:{self.me.handle}:{cleaned}" if cleaned else ""

    async def act(self, key: str, values: dict[str, list[str]], *, subject: str = "") -> Outcome:
        """Une action déclarée par une faculté, au nom de qui est connecté (``by`` : son adresse), auditée comme faite
        depuis son espace (``moi.<action>``)."""
        return await perform(self.kernel, key, values, by=self.me.handle, subject=subject, nonce=self.nonce(),
                             via=SPACE, files=self.files)

    async def once(self, make: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        """Une création qui ne passe pas par une action (une boîte, un compte Teams, un service) : redite avec la même
        clé d'envoi, elle rend la même réponse sans rien refaire (``deduped``), tant que le serveur tourne. Les
        créations d'un compte se font l'une après l'autre (deux envois simultanés de la même clé n'en font qu'une) ;
        celles d'un autre compte ne les attendent pas."""
        nonce = self.nonce()
        if not nonce:
            return await make()
        async with self.api.creating.setdefault(self.me.account.id, asyncio.Lock()):
            known = self.api.created.get(nonce)
            if known is not None:
                return {**known, "deduped": True}
            got = await make()
            self.api.created[nonce] = got
            while len(self.api.created) > CREATED_MAX:
                self.api.created.popitem(last=False)
            return got

    def probe(self) -> None:
        """Un essai qui fait joindre un serveur (tester, relever) : borné par compte (429 au-delà)."""
        key = f"compte:{self.me.account.id}"
        if self.api.probes.blocked(key):
            raise Denied(429, "Trop d'essais d'affilée : attends une minute avant de réessayer.")
        self.api.probes.fail(key)

    def outbound(self, *, addresses: bool = False) -> None:
        """Une demande de la carte qui sort vers un service du dehors : bornée par compte, 429 au-delà — le serveur
        d'itinéraires public est à tous (``OUTBOUND``, que la console use aussi) ; une adresse a sa propre borne, plus
        large (``ADDRESSES``)."""
        if not spend(self.api.address_tries if addresses else self.api.outbound, self.me.account):
            raise Denied(429, "Trop d'adresses cherchées d'affilée : attends une minute." if addresses else
                         ROUTES_BUSY)


Handler = Callable[[Call], Awaitable[Any]]


def _is_multipart(request: Request) -> bool:
    return request.headers.get("content-type", "").lower().startswith("multipart/form-data")


async def read_upload(request: Request) -> tuple[dict[str, Any], tuple[File, ...]]:
    """Un envoi en ``multipart/form-data`` : ses champs, comme un corps JSON, et ses fichiers. Le corps est borné pendant
    qu'il arrive (``PayloadTooLarge``), et les fichiers attendent sur le disque le temps de le lire. Ce qu'ils valent
    (taille, nombre, nom, sorte) se juge dans l'action qui les joint."""
    parser = MultiPartParser(request.headers, bounded_stream(request, UPLOAD_BODY_MAX), max_files=PIECES_MAX + 1,
                             max_fields=UPLOAD_FIELDS)
    try:
        form_data = await parser.parse()
    except (MultiPartException, ValueError):  # une erreur de ``python-multipart`` est une ValueError
        raise Denied(400, f"Cet envoi n'a pas pu être lu : un formulaire abîmé, ou plus de {PIECES_MAX} pièces.") from None
    try:
        data: dict[str, Any] = {}
        files: list[File] = []
        for name, value in form_data.multi_items():
            if isinstance(value, UploadFile):
                files.append(File(value.filename or "", value.content_type or "", await value.read()))
            else:  # un formulaire écrit ses fins de ligne en CRLF : un champ se compte comme en JSON
                data[name] = value.replace("\r\n", "\n")
    finally:
        await form_data.close()
    return data, tuple(files)


class MeApiBase:
    """Le cadre de l'API par personne : ce que toute route a en commun (qui demande, le jeton CSRF, le corps, les bornes
    par compte). Les routes elles-mêmes viennent des modules, que le paquet réunit (``mika.app.moi.MeApi``)."""

    def __init__(self, kernel: Kernel, accounts: Accounts, *, origins: Iterable[str] = (),
                 apk: Path | None = None, settings: Any = None,
                 reconfigure: Callable[[], Awaitable[list[str]]] | None = None, maps: Any = None) -> None:
        self.kernel = kernel
        self.accounts = accounts
        #: les réglages du serveur (ses boîtes, ses comptes Teams), et de quoi rejournaliser ce qui en dérive
        self.settings = settings
        self.reconfigure = reconfigure
        #: les essais pour changer son mot de passe, par compte (les bornes de ``/auth/login``)
        self.password_tries = LoginThrottle(*PASSWORD_TRIES)
        #: les essais qui font joindre un serveur (tester une boîte ou un service, relever), par compte
        self.probes = LoginThrottle(*PROBES)
        #: les demandes de la carte qui sortent vers un service du dehors, par compte
        self.outbound = LoginThrottle(*OUTBOUND)
        #: les adresses cherchées, par compte (``ADDRESSES``)
        self.address_tries = LoginThrottle(*ADDRESSES)
        #: les créations faites, par clé d'envoi (``Call.once``), et ce qui fait celles d'un compte l'une après l'autre
        self.created: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.creating: dict[int, asyncio.Lock] = {}
        #: les origines du client web : un cadre de l'API (un mail HTML) se laisse poser par elles seules
        self.origins = tuple(origins)
        #: l'application du téléphone qu'on y dépose (ADR 0190), servie à qui est connecté (sa session, ou un jeton
        #: de son compte)
        self.apk = apk
        #: la carte de sa position (ADR 0193 : ``adapters.maps.MapTiles``) ; ``None`` : pas de carte, le plan dessiné
        self.maps = maps

    def route(self, path: str, handler: Handler, *, write: bool = False,
              raw: bool = False, upload: bool = False) -> Route:
        """Une route : ``write`` — un POST, qui exige le jeton CSRF et lit un corps JSON ; ``upload`` — ce corps peut
        aussi être un ``multipart/form-data`` : ses champs valent ceux du JSON, ses fichiers vont à ``Call.files``
        (ADR 0214) ; ``raw`` — le gestionnaire rend lui-même sa réponse (un fichier, un cadre)."""

        async def endpoint(request: Request) -> Response:
            account = account_of(request, self.accounts)
            if account is None:
                return JSONResponse({"error": "Authentification requise."}, status_code=401, headers=NO_STORE)
            data: dict[str, Any] = {}
            files: tuple[File, ...] = ()
            if write:
                if native_token(request.headers):
                    # un client natif ne fait que lire : son jeton porteur et un CSRF qu'il poserait lui-même ne
                    # prouvent pas une session de navigateur
                    return JSONResponse({"error": "Un client natif ne fait que lire ici : écris depuis le navigateur."},
                                        status_code=403, headers=NO_STORE)
                if not csrf_header_ok(request):
                    return JSONResponse({"error": "Requête refusée (CSRF)."}, status_code=403, headers=NO_STORE)
                try:
                    if upload and _is_multipart(request):
                        parsed, files = await read_upload(request)
                    else:
                        parsed = json.loads(await read_bounded(request, BODY_MAX_BYTES) or b"{}")
                except PayloadTooLarge:
                    return JSONResponse({"error": "Requête trop grande."}, status_code=413, headers=NO_STORE)
                except Denied as exc:
                    return JSONResponse({"error": exc.message}, status_code=exc.status, headers=NO_STORE)
                except (ValueError, RecursionError):
                    parsed = None
                if not isinstance(parsed, dict):
                    return JSONResponse({"error": "Un objet JSON."}, status_code=400, headers=NO_STORE)
                data = parsed
            req = Call(request, me_of(self.kernel.mind.frame(), account), self.kernel, data, self, files)
            try:
                got = await handler(req)
            except Denied as exc:
                body: dict[str, Any] = {"error": exc.message}
                if exc.fields:
                    body["fields"] = exc.fields
                return JSONResponse(body, status_code=exc.status, headers=NO_STORE)
            if raw:
                return got
            return JSONResponse(got, headers=NO_STORE)

        return Route(f"{PREFIX}{path}", endpoint, methods=["POST"] if write else ["GET"])
