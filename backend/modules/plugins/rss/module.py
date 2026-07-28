"""Module RSS — relève des flux, en garde les articles, signale ce qui compte.

**Ce qui n'allait pas.** Le module déclarait ``is_available()`` faux sans
``feedparser``, dépendance absente de ``requirements.txt`` : il n'était donc
jamais actif, son espace n'affichait rien, aucun flux n'était relevé, et la
seule façon d'ajouter un flux était l'admin Django ou une variable
d'environnement héritée. Trois choses ont changé :

1. **La lecture d'un flux ne dépend plus d'une dépendance optionnelle**
   (``parser.py`` : ``feedparser`` s'il est là, bibliothèque standard sinon).
   Le module est donc toujours disponible.
2. **Les flux s'éditent dans le tableau de bord** (``rss.feeds``, adossé au
   modèle ``RSSFeed``), et une liste de flux par défaut est semée au premier
   démarrage — un module de revue de presse vide ne se distingue pas d'un
   module en panne.
3. **Les articles se consultent** (``panels.py``), se cherchent, se relisent
   et se relèvent à la demande, au lieu d'exister uniquement comme empreintes
   de déduplication.

**Ce que le relevé garantit.** Un flux lent ne bloque pas les autres au-delà
de son délai ; un flux en panne est *enregistré comme tel* plutôt que noyé
dans les logs ; un flux inchangé n'est pas retéléchargé (relevé conditionnel
ETag / If-Modified-Since) ; et le nombre d'articles examinés par tour est
borné, parce que le premier relevé d'une poignée de flux produit sinon des
centaines d'événements d'un coup.

**Ce qui atteint Mika.** Par défaut un nouvel article émet ``rss.new_entry``,
que la conscience interprète par heuristique (pas d'appel LLM — voir
``conscience/interpreter.py``). Un article qui contient un *mot-clé d'alerte*
l'interrompt directement via ``notify_ai``. Les deux sont réglables, et
désactivables jusqu'au silence complet.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from functools import partial

from django.conf import settings

from modules.base import BaseModule
from modules.plugins.rss import parser
from modules.types import (
    ModuleCapability,
    ModuleEvent,
    ModuleNotification,
    ModuleStatus,
    ModuleTool,
    ToolParameter,
    ToolParameterType,
)

logger = logging.getLogger(__name__)

# Un flux est une liste de titres ; au-delà, ce n'en est pas un.
MAX_FEED_BYTES = 5 * 1024 * 1024
USER_AGENT = "vtuber-rss/2.0 (+https://localhost)"

# Semés au premier démarrage, uniquement si aucun flux n'existe et qu'aucun
# n'est déclaré en environnement. Un module de veille livré vide ne se
# distingue pas d'un module cassé — c'était précisément le symptôme. Tout est
# modifiable ou supprimable depuis Configuration ; rien n'est re-semé ensuite.
DEFAULT_FEEDS: tuple[dict[str, str], ...] = (
    {"name": "Le Monde — À la une", "url": "https://www.lemonde.fr/rss/une.xml", "category": "Actualité"},
    {"name": "France Info", "url": "https://www.francetvinfo.fr/titres.rss", "category": "Actualité"},
    {"name": "Hacker News", "url": "https://hnrss.org/frontpage", "category": "Tech"},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "category": "Tech"},
    {"name": "Korben", "url": "https://korben.info/feed", "category": "Tech"},
    {"name": "Hugging Face — Blog", "url": "https://huggingface.co/blog/feed.xml", "category": "IA"},
    {"name": "MIT Tech Review — IA", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "category": "IA"},
    {"name": "Futura Sciences", "url": "https://www.futura-sciences.com/rss/actualites.xml", "category": "Science"},
    {"name": "NASA", "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss", "category": "Science"},
)


@dataclass
class PollSettings:
    """Les réglages d'un tour de relevé, lus en une fois.

    Relus à chaque tour plutôt que mémorisés au démarrage : les réglages sont
    marqués « à chaud » dans le tableau de bord, ce qui doit vouloir dire
    quelque chose.
    """
    poll_interval: int = 600
    fetch_timeout: int = 20
    max_entries: int = 15
    keep_per_feed: int = 200
    emit_events: bool = True
    alert_keywords: tuple[str, ...] = ()
    max_alerts: int = 2
    context_items: int = 4


@dataclass
class PollReport:
    """Ce qu'un tour de relevé a produit — rendu tel quel par l'action manuelle."""
    feeds: int = 0
    new_entries: int = 0
    unchanged: int = 0        # réponses 304 : rien n'a bougé côté serveur
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class RSSModule(BaseModule):
    """Relève des flux RSS/Atom et publie les nouveaux articles."""

    CRON_INTERVAL = 600

    # Le module n'écoute pas le bus : le motif par défaut ``*`` le réveillait
    # pour chaque signal du système afin d'exécuter un ``on_event`` vide.
    EVENT_PATTERN = "rss.__inutilise__"

    def __init__(self):
        super().__init__("rss")
        self._new_count: int = 0            # nouveautés du dernier tour
        self._last_report: PollReport | None = None
        self._polling: bool = False
        self._parser: str = parser.which_parser()
        # Instantané pour l'invite système. Tenu en RAM, et pas relu en base
        # au moment de bâtir l'invite : ``collect_context`` est appelé depuis
        # une coroutine, où toute requête ORM lève ``SynchronousOnlyOperation``
        # — que le collecteur avale, si bien que le bloc disparaîtrait de
        # chaque invite sans que rien ne le signale. Même raison que les
        # compteurs de non-lus du module email.
        self._headlines: list[dict] = []
        self._unread_total: int = 0
        self._context_items: int = 4

    # ── Cycle de vie ──────────────────────────────────────────────

    def is_available(self) -> bool:
        """Toujours disponible.

        C'était ``False`` sans ``feedparser``, et comme la dépendance n'était
        pas déclarée, le module n'a jamais tourné sur une installation neuve —
        sans qu'aucun écran ne dise pourquoi. La lecture d'un flux a maintenant
        un chemin en bibliothèque standard, donc plus rien à vérifier ici.
        """
        return True

    def config_schema(self):
        from modules.plugins.rss.config_schema import CONFIG_SCHEMA
        return CONFIG_SCHEMA

    def get_models(self) -> list:
        from modules.plugins.rss.models import RSSEntry, RSSFeed
        return [RSSFeed, RSSEntry]

    def get_panels(self) -> list:
        from modules.plugins.rss.panels import get_panels
        return get_panels()

    async def instantiate(self) -> None:
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSFeed

        conf = await self._settings()
        self.CRON_INTERVAL = conf.poll_interval

        await sync_to_async(self._seed_feeds)()
        # Sans ça, les titres n'apparaissent dans l'invite qu'après le premier
        # relevé — soit dix minutes de « je ne sais pas ce qui se passe » au
        # redémarrage, alors que la base est pleine.
        await sync_to_async(self._refresh_headlines)(conf.context_items)

        actifs = await sync_to_async(RSSFeed.objects.filter(is_active=True).count)()
        self.logger.info(
            "Module RSS démarré (%d flux actif(s), relevé toutes les %ds, analyseur : %s)",
            actifs, self.CRON_INTERVAL, self._parser,
        )

    # ── Amorçage des flux ─────────────────────────────────────────

    def _seed_feeds(self) -> None:
        """Crée les flux d'environnement, puis la liste par défaut si vide.

        Ne s'exécute qu'avec une table vide : supprimer tous ses flux est une
        décision, pas un état à corriger au redémarrage suivant.
        """
        from modules.plugins.rss.models import RSSFeed

        for feed_cfg in getattr(settings, "RSS_FEEDS", []) or []:
            url = (feed_cfg or {}).get("url", "")
            if not url or RSSFeed.objects.filter(url=url).exists():
                continue
            RSSFeed.objects.create(
                name=feed_cfg.get("name") or url,
                url=url,
                category=feed_cfg.get("category", ""),
            )
            self.logger.info("Flux repris de l'environnement : %s", url)

        if RSSFeed.objects.exists():
            return

        RSSFeed.objects.bulk_create([
            RSSFeed(name=f["name"], url=f["url"], category=f["category"])
            for f in DEFAULT_FEEDS
        ], ignore_conflicts=True)
        self.logger.info(
            "%d flux par défaut installés (modifiables dans Configuration)",
            len(DEFAULT_FEEDS),
        )

    # ── Réglages ──────────────────────────────────────────────────

    async def _settings(self) -> PollSettings:
        from asgiref.sync import sync_to_async
        return await sync_to_async(self._settings_sync)()

    @staticmethod
    def _settings_sync() -> PollSettings:
        """Lecture groupée. Passe par l'ORM, donc jamais depuis une coroutine.

        ``config_service.get`` avale l'erreur d'accès synchrone à l'ORM et
        retombe silencieusement sur le défaut du schéma : appelé directement
        depuis une boucle asynchrone, il rendrait donc la valeur d'usine en
        ignorant ce que l'utilisateur a réglé. D'où le passage obligé par
        ``sync_to_async``.
        """
        from configs.service import config_service

        def lire(key, default):
            try:
                value = config_service.get(key, default=default)
            except Exception:
                return default
            return default if value is None else value

        mots = lire("rss.alert_keywords", []) or []
        if isinstance(mots, str):
            mots = [m.strip() for m in mots.split(",")]

        return PollSettings(
            poll_interval=int(lire("rss.poll_interval", 600)),
            fetch_timeout=int(lire("rss.fetch_timeout", 20)),
            max_entries=int(lire("rss.max_entries_per_poll", 15)),
            keep_per_feed=int(lire("rss.keep_per_feed", 200)),
            emit_events=bool(lire("rss.emit_events", True)),
            alert_keywords=tuple(m.strip().lower() for m in mots if str(m).strip()),
            max_alerts=int(lire("rss.max_alerts_per_poll", 2)),
            context_items=int(lire("rss.context_items", 4)),
        )

    # ── Téléchargement ────────────────────────────────────────────

    def _fetch(self, url: str, timeout: int, etag: str, modified: str):
        """Télécharge un flux. Renvoie ``(octets|None, etag, last_modified)``.

        ``None`` signifie **304 Non modifié** : rien à analyser, et c'est le
        cas le plus fréquent sur un flux relevé toutes les dix minutes.

        Les octets sont récupérés ici plutôt que confiés à un analyseur qui
        ferait sa propre requête : ``urllib`` sans délai attend *indéfiniment*,
        et le ``wait_for`` en amont cesserait d'attendre pendant que le fil
        d'exécution, lui, resterait bloqué — or il vient de l'exécuteur par
        défaut, partagé avec ``sync_to_async``. Quelques flux morts
        affameraient l'ORM.
        """
        import urllib.error
        import urllib.request

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        }
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified

        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                raw = resp.read(MAX_FEED_BYTES)
                return (
                    raw,
                    (resp.headers.get("ETag") or "")[:200],
                    (resp.headers.get("Last-Modified") or "")[:100],
                )
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return None, etag, modified
            raise

    # ── Relevé ────────────────────────────────────────────────────

    async def worker_cron(self) -> None:
        await self.poll()

    async def poll(self, *, feed_ids: list[int] | None = None) -> PollReport:
        """Relève les flux actifs (ou ceux demandés) et publie les nouveautés.

        Utilisable module arrêté : c'est ce qui permet au bouton « Relever
        maintenant » de fonctionner sur la page d'un module qu'on vient
        justement d'ouvrir parce qu'il ne tourne pas.
        """
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSFeed

        conf = await self._settings()
        self.CRON_INTERVAL = conf.poll_interval

        def _flux():
            qs = RSSFeed.objects.all()
            if feed_ids is None:
                qs = qs.filter(is_active=True)
            else:
                qs = qs.filter(pk__in=feed_ids)
            return list(qs)

        feeds = await sync_to_async(_flux)()
        report = PollReport(feeds=len(feeds))
        if not feeds:
            self._last_report = report
            return report

        self._polling = True
        alerts_restantes = conf.max_alerts
        try:
            for feed in feeds:
                try:
                    nouveaux, inchange = await self._poll_feed(feed, conf, alerts_restantes)
                except Exception as exc:
                    report.failed += 1
                    report.errors.append(f"{feed.name} : {type(exc).__name__}")
                    self.logger.exception("Relevé impossible pour %s", feed.name)
                    await sync_to_async(self._record_failure)(feed, exc)
                    continue
                report.new_entries += len(nouveaux)
                report.unchanged += 1 if inchange else 0
                alerts_restantes -= sum(1 for e in nouveaux if e.get("alerted"))
        finally:
            self._polling = False

        self._new_count = report.new_entries
        self._last_report = report
        if report.new_entries:
            self.logger.info(
                "RSS : %d nouvel(les) entrée(s) sur %d flux",
                report.new_entries, report.feeds,
            )

        await sync_to_async(self._prune)(conf.keep_per_feed)
        await sync_to_async(self._refresh_headlines)(conf.context_items)
        return report

    async def _poll_feed(self, feed, conf: PollSettings, alerts_restantes: int):
        """Un flux. Renvoie ``(nouveautés, inchangé)``."""
        from asgiref.sync import sync_to_async

        loop = asyncio.get_event_loop()
        try:
            raw, etag, modified = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    partial(
                        self._fetch, feed.url, conf.fetch_timeout,
                        feed.etag, feed.http_last_modified,
                    ),
                ),
                # Marge au-delà du délai de la socket : le ``wait_for`` est un
                # garde-fou contre un fil bloqué ailleurs que dans la lecture
                # réseau, pas un second délai concurrent du premier.
                timeout=conf.fetch_timeout + 5,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"délai de {conf.fetch_timeout}s dépassé")

        if raw is None:                       # 304
            await sync_to_async(self._record_success)(feed, None, etag, modified)
            return [], True

        parsed = parser.parse(raw)
        if parsed.error and not parsed.entries:
            raise ValueError(parsed.error)

        nouveaux = await sync_to_async(self._store)(feed, parsed, conf)
        await sync_to_async(self._record_success)(feed, parsed.title, etag, modified)

        for item in nouveaux:
            if item["emit"]:
                await self._emit(feed, item)
            if item["notable"] and alerts_restantes > 0 and conf.alert_keywords:
                if await self._alert(feed, item):
                    item["alerted"] = True
                    alerts_restantes -= 1

        return nouveaux, False

    # ── Écriture ──────────────────────────────────────────────────

    def _store(self, feed, parsed: parser.ParsedFeed, conf: PollSettings) -> list[dict]:
        """Enregistre les articles inédits. Renvoie de quoi les publier.

        Les empreintes déjà connues sont lues **en une requête** plutôt qu'une
        par article : un tour sur dix flux faisait 150 ``exists()`` pour
        n'apprendre presque jamais rien, sur une base SQLite que six boucles de
        fond écrivent en permanence.
        """
        from modules.plugins.rss.models import RSSEntry

        candidats = []
        for entry in parsed.entries[:conf.max_entries]:
            if not entry.uid:
                continue
            candidats.append((parser.entry_hash(entry.uid, feed.url), entry))
        if not candidats:
            return []

        connus = set(
            RSSEntry.objects.filter(
                feed=feed, entry_hash__in=[h for h, _ in candidats],
            ).values_list("entry_hash", flat=True)
        )

        mots_flux = feed.keyword_list
        mots_alerte = conf.alert_keywords
        emettre = conf.emit_events and feed.emit_events

        lignes, sorties = [], []
        for empreinte, entry in candidats:
            if empreinte in connus:
                continue
            texte = f"{entry.title} {entry.summary}".lower()
            # Deux filtres distincts : les mots-clés du flux décident si
            # l'article mérite d'être signalé du tout, les mots d'alerte s'il
            # doit interrompre Mika.
            retenu = (not mots_flux) or any(m in texte for m in mots_flux)
            notable = bool(mots_alerte) and any(m in texte for m in mots_alerte)

            lignes.append(RSSEntry(
                feed=feed,
                entry_hash=empreinte,
                title=entry.title[:500],
                link=entry.link[:500],
                summary=entry.summary[:4000],
                author=entry.author[:200],
                published=entry.published_raw[:100],
                published_at=entry.published_at,
                is_notable=notable,
            ))
            sorties.append({
                "title": entry.title,
                "link": entry.link,
                "summary": entry.summary,
                "author": entry.author,
                "published": entry.published_raw,
                "emit": emettre and retenu,
                "notable": notable,
                "alerted": False,
            })

        if not lignes:
            return []

        # ``ignore_conflicts`` : un relevé manuel peut croiser le relevé
        # périodique, et l'unicité (flux, empreinte) est là pour ça.
        RSSEntry.objects.bulk_create(lignes, ignore_conflicts=True)
        feed.entries_total = (feed.entries_total or 0) + len(lignes)
        feed.save(update_fields=["entries_total"])
        return sorties

    @staticmethod
    def _record_success(feed, titre: str | None, etag: str, modified: str) -> None:
        from django.utils import timezone
        from urllib.parse import urlparse

        champs = [
            "last_polled", "last_success_at", "last_error",
            "last_error_at", "error_count", "etag", "http_last_modified",
        ]
        maintenant = timezone.now()
        feed.last_polled = maintenant
        feed.last_success_at = maintenant
        feed.last_error = ""
        feed.last_error_at = None
        feed.error_count = 0
        feed.etag = etag or ""
        feed.http_last_modified = modified or ""

        # Le nom saisi fait foi ; on ne remplace que l'étiquette provisoire
        # posée par le formulaire quand l'utilisateur n'a collé qu'une URL.
        if titre and feed.name in ("", feed.url, urlparse(feed.url).hostname):
            feed.name = titre[:200]
            champs.append("name")

        feed.save(update_fields=champs)

    @staticmethod
    def _record_failure(feed, exc: Exception) -> None:
        from django.utils import timezone

        feed.last_polled = timezone.now()
        feed.last_error = f"{type(exc).__name__}: {exc}"[:500]
        feed.last_error_at = feed.last_polled
        feed.error_count = (feed.error_count or 0) + 1
        feed.save(update_fields=[
            "last_polled", "last_error", "last_error_at", "error_count",
        ])

    def _prune(self, keep_per_feed: int) -> None:
        """Borne la table. Ne touche pas aux flux inactifs : leurs articles
        sont un historique figé, pas une file qui grossit."""
        from modules.plugins.rss.models import RSSEntry, RSSFeed

        for feed in RSSFeed.objects.filter(is_active=True):
            total = RSSEntry.objects.filter(feed=feed).count()
            if total <= keep_per_feed:
                continue
            gardes = list(
                RSSEntry.objects.filter(feed=feed)
                .order_by("-seen_at")[:keep_per_feed]
                .values_list("id", flat=True)
            )
            supprimes, _ = (
                RSSEntry.objects.filter(feed=feed).exclude(id__in=gardes).delete()
            )
            if supprimes:
                self.logger.info("%d article(s) élagué(s) sur %s", supprimes, feed.name)

    # ── Publication ───────────────────────────────────────────────

    async def _emit(self, feed, item: dict) -> None:
        from modules.manager import module_manager

        await module_manager.emit_event(ModuleEvent(
            source_module=self.name,
            event_type="rss.new_entry",
            data={
                "feed_name": feed.name,
                "feed_url": feed.url,
                "category": feed.category,
                "title": item["title"],
                "link": item["link"],
                "summary": item["summary"][:500],
                "published": item["published"],
                "author": item["author"],
            },
        ))

    async def _alert(self, feed, item: dict) -> bool:
        """Interrompt Mika sur un mot-clé d'alerte. ``False`` si impossible.

        Volontairement distinct de l'événement : ``emit_event`` dit « ceci est
        arrivé » et personne n'est tenu d'y répondre ; ``notify_ai`` demande
        une réponse et coûte un tour de pipeline complet. Un mot-clé d'alerte
        est une déclaration explicite que ce sujet vaut l'interruption.
        """
        if self._notify_ai is None:
            return False
        try:
            await self._notify_ai(ModuleNotification(
                source_module=self.name,
                summary=f"Article surveillé sur {feed.name} : {item['title'][:120]}",
                details=(
                    f"Flux : {feed.name}\nTitre : {item['title']}\n"
                    f"Lien : {item['link']}\n\n{item['summary'][:600]}"
                ),
                urgency="normal",
                suggested_action="En parler si c'est pertinent, sinon ne rien faire.",
                metadata={"feed": feed.name, "link": item["link"]},
            ))
            return True
        except Exception:
            self.logger.exception("Alerte RSS non délivrée pour %s", feed.name)
            return False

    # ── Capacités & outils ────────────────────────────────────────

    def get_capabilities(self) -> list[ModuleCapability]:
        return [
            ModuleCapability(
                description="Lire les derniers articles des flux d'actualité suivis",
                tool_names=["list_rss_entries", "read_rss_entry", "list_rss_feeds"],
            ),
            ModuleCapability(
                description="Chercher un sujet dans les articles déjà relevés",
                tool_names=["search_rss"],
            ),
            ModuleCapability(
                description="Relever les flux immédiatement pour voir s'il y a du nouveau",
                tool_names=["refresh_rss_feeds"],
            ),
        ]

    def return_tools(self) -> list[ModuleTool]:
        return [
            ModuleTool(
                name="list_rss_entries",
                description=(
                    "Liste les articles récents des flux suivis. Renvoie un "
                    "identifiant par article, à passer à read_rss_entry pour le résumé complet."
                ),
                parameters=[
                    ToolParameter(
                        name="limit", type=ToolParameterType.INTEGER,
                        description="Nombre maximum d'articles (défaut 10, max 50)",
                        required=False,
                    ),
                    ToolParameter(
                        name="feed_name", type=ToolParameterType.STRING,
                        description="Ne garder qu'un flux (correspondance partielle)",
                        required=False,
                    ),
                    ToolParameter(
                        name="category", type=ToolParameterType.STRING,
                        description="Ne garder qu'une catégorie (Tech, Actualité, IA, Science…)",
                        required=False,
                    ),
                    ToolParameter(
                        name="unread_only", type=ToolParameterType.BOOLEAN,
                        description="Uniquement les articles jamais consultés",
                        required=False,
                    ),
                ],
                handler=self._tool_list_entries,
            ),
            ModuleTool(
                name="read_rss_entry",
                description="Lit un article en entier (résumé complet, auteur, lien, date).",
                parameters=[
                    ToolParameter(
                        name="entry_id", type=ToolParameterType.INTEGER,
                        description="Identifiant renvoyé par list_rss_entries ou search_rss",
                    ),
                ],
                handler=self._tool_read_entry,
            ),
            ModuleTool(
                name="search_rss",
                description="Cherche des mots dans les titres et résumés des articles relevés.",
                parameters=[
                    ToolParameter(
                        name="query", type=ToolParameterType.STRING,
                        description="Mots à chercher",
                    ),
                    ToolParameter(
                        name="limit", type=ToolParameterType.INTEGER,
                        description="Nombre maximum de résultats (défaut 10)",
                        required=False,
                    ),
                ],
                handler=self._tool_search,
            ),
            ModuleTool(
                name="list_rss_feeds",
                description="Liste les flux suivis, leur état et leur dernier relevé.",
                parameters=[],
                handler=self._tool_list_feeds,
            ),
            ModuleTool(
                name="refresh_rss_feeds",
                description=(
                    "Relève les flux maintenant sans attendre le tour suivant. "
                    "Renvoie le nombre de nouveaux articles."
                ),
                parameters=[
                    ToolParameter(
                        name="feed_name", type=ToolParameterType.STRING,
                        description="Ne relever qu'un flux (correspondance partielle)",
                        required=False,
                    ),
                ],
                handler=self._tool_refresh,
            ),
        ]

    # ── Implémentation des outils ─────────────────────────────────

    @staticmethod
    def _texte(message: str) -> dict:
        return {"content": [{"type": "text", "text": message}]}

    async def _tool_list_entries(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSEntry

        limite = max(1, min(50, int(args.get("limit") or 10)))

        def _lire():
            qs = RSSEntry.objects.select_related("feed")
            if args.get("feed_name"):
                qs = qs.filter(feed__name__icontains=str(args["feed_name"]))
            if args.get("category"):
                qs = qs.filter(feed__category__icontains=str(args["category"]))
            if args.get("unread_only"):
                qs = qs.filter(is_read=False)
            return list(qs[:limite])

        entries = await sync_to_async(_lire)()
        if not entries:
            return self._texte("Aucun article ne correspond.")
        return self._texte("\n".join(self._ligne_outil(e) for e in entries))

    @staticmethod
    def _ligne_outil(entry) -> str:
        quand = entry.dated.strftime("%d/%m %H:%M") if entry.dated else "?"
        return (
            f"[#{entry.pk}] ({quand}) [{entry.feed.name}] {entry.title}\n"
            f"    {entry.summary[:180]}"
        )

    async def _tool_read_entry(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSEntry

        try:
            entry_id = int(args.get("entry_id"))
        except (TypeError, ValueError):
            return self._texte("entry_id doit être un nombre.")

        def _lire():
            entry = RSSEntry.objects.select_related("feed").filter(pk=entry_id).first()
            if entry is not None and not entry.is_read:
                # Lire un article, c'est l'avoir lu : l'invite système ne doit
                # pas continuer à le proposer comme nouveauté.
                entry.is_read = True
                entry.save(update_fields=["is_read"])
            return entry

        entry = await sync_to_async(_lire)()
        if entry is None:
            return self._texte(f"Aucun article #{entry_id}.")

        # L'instantané d'invite est en RAM : sans ça, elle continuerait à voir
        # comme « non lu » l'article qu'elle vient d'ouvrir.
        if any(h["id"] == entry_id for h in self._headlines):
            self._headlines = [h for h in self._headlines if h["id"] != entry_id]
            self._unread_total = max(0, self._unread_total - 1)

        quand = entry.dated.strftime("%d/%m/%Y %H:%M") if entry.dated else "date inconnue"
        return self._texte(
            f"{entry.title}\n"
            f"Flux : {entry.feed.name} ({entry.feed.category or 'sans catégorie'})\n"
            f"Date : {quand}\n"
            f"Auteur : {entry.author or 'non précisé'}\n"
            f"Lien : {entry.link or '—'}\n\n"
            f"{entry.summary or '(pas de résumé dans le flux)'}"
        )

    async def _tool_search(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async
        from django.db.models import Q
        from modules.plugins.rss.models import RSSEntry

        requete = str(args.get("query") or "").strip()
        if not requete:
            return self._texte("Précise ce que tu cherches.")
        limite = max(1, min(50, int(args.get("limit") or 10)))

        def _chercher():
            return list(
                RSSEntry.objects.select_related("feed").filter(
                    Q(title__icontains=requete) | Q(summary__icontains=requete)
                )[:limite]
            )

        entries = await sync_to_async(_chercher)()
        if not entries:
            return self._texte(f"Rien sur « {requete} » dans les articles relevés.")
        return self._texte("\n".join(self._ligne_outil(e) for e in entries))

    async def _tool_list_feeds(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSFeed

        feeds = await sync_to_async(lambda: list(RSSFeed.objects.all()))()
        if not feeds:
            return self._texte("Aucun flux suivi.")

        lignes = []
        for f in feeds:
            quand = f.last_polled.strftime("%d/%m %H:%M") if f.last_polled else "jamais"
            etat = "actif" if f.is_active else "suspendu"
            if f.error_count:
                etat = f"en erreur ({f.error_count}) — {f.last_error[:80]}"
            lignes.append(
                f"- [#{f.pk}] {f.name} · {f.category or 'sans catégorie'} · "
                f"{etat} · dernier relevé {quand}"
            )
        return self._texte("\n".join(lignes))

    async def _tool_refresh(self, args: dict) -> dict:
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSFeed

        ids = None
        if args.get("feed_name"):
            nom = str(args["feed_name"])
            ids = await sync_to_async(
                lambda: list(
                    RSSFeed.objects.filter(name__icontains=nom, is_active=True)
                    .values_list("id", flat=True)
                )
            )()
            if not ids:
                return self._texte(f"Aucun flux actif ne correspond à « {nom} ».")

        report = await self.poll(feed_ids=ids)
        if not report.new_entries:
            return self._texte(
                f"Relevé de {report.feeds} flux : rien de nouveau"
                + (f" ({report.failed} en erreur)." if report.failed else ".")
            )
        return self._texte(
            f"{report.new_entries} nouvel(les) entrée(s) sur {report.feeds} flux. "
            "Utilise list_rss_entries pour les voir."
        )

    # ── Contexte d'invite ─────────────────────────────────────────

    def _refresh_headlines(self, combien: int) -> None:
        """Rafraîchit l'instantané d'invite. Appelé sous ``sync_to_async``."""
        from modules.plugins.rss.models import RSSEntry

        self._context_items = combien
        if combien <= 0:
            self._headlines = []
            self._unread_total = RSSEntry.objects.filter(is_read=False).count()
            return
        self._headlines = [
            {"id": e.pk, "feed": e.feed.name, "title": e.title}
            for e in RSSEntry.objects.select_related("feed")
                       .filter(is_read=False)[:combien]
        ]
        self._unread_total = RSSEntry.objects.filter(is_read=False).count()

    def get_context(self, person_id: str = "") -> str:
        """Les titres récents non lus, pas seulement leur nombre.

        « 7 nouveaux articles RSS » ne permet d'en parler qu'en le récitant.
        Quelques titres lui donnent de quoi rebondir — et les outils font le
        reste. Lecture RAM uniquement (voir ``_headlines``).
        """
        if self._context_items <= 0 or not self._headlines:
            return ""
        titres = "\n".join(
            f"- [{h['feed']}] {h['title'][:120]}" for h in self._headlines
        )
        reste = self._unread_total - len(self._headlines)
        suite = f"\n(et {reste} autre(s) — outil list_rss_entries)" if reste > 0 else ""
        return f"{self._unread_total} article(s) non lu(s) dans tes flux :\n{titres}{suite}"

    # ── État ──────────────────────────────────────────────────────

    def get_status(self) -> ModuleStatus:
        status = super().get_status()
        details = {
            "analyseur": self._parser,
            "intervalle_s": self.CRON_INTERVAL,
            "nouveautes_dernier_tour": self._new_count,
            "releve_en_cours": self._polling,
        }
        if self._last_report is not None:
            details.update({
                "flux_releves": self._last_report.feeds,
                "flux_inchanges": self._last_report.unchanged,
                "flux_en_erreur": self._last_report.failed,
            })
        try:
            from modules.plugins.rss.models import RSSEntry, RSSFeed
            details["flux_actifs"] = RSSFeed.objects.filter(is_active=True).count()
            details["articles_non_lus"] = RSSEntry.objects.filter(is_read=False).count()
        except Exception:
            logger.debug("compteurs RSS indisponibles", exc_info=True)
        status.details = details
        return status
