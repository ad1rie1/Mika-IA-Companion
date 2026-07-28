"""Tests du module RSS.

Le module n'en avait aucun, et c'est précisément ce qui a permis à sa panne de
passer inaperçue : ``is_available()`` renvoyait ``False`` faute d'une
dépendance non déclarée, donc le module ne démarrait jamais, donc son espace
d'administration restait vide — sans qu'aucune erreur ne soit levée nulle part.
Un module désactivé et un module cassé se ressemblent trop pour qu'on s'en
remette à l'inspection.

Priorités, par coût d'une régression :

1. **Le module doit être disponible sans ``feedparser``.** C'est la panne
   d'origine, et le repli en bibliothèque standard est ce qui l'empêche de
   revenir.
2. **Aucun appel réseau dans la suite.** Le téléchargement est le seul point
   remplacé ; l'analyse, la déduplication et l'écriture sont exercées pour de
   vrai sur des octets fournis en dur.
3. **Ce qui atteint Mika est borné** : plafond d'articles par tour,
   interrupteur d'événements, mots-clés.
"""
from __future__ import annotations

import pytest

from modules.plugins.rss import parser
from modules.plugins.rss.module import DEFAULT_FEEDS, PollSettings, RSSModule


# ── Flux d'exemple ──────────────────────────────────────────────────────

RSS2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Journal d'exemple</title>
    <item>
      <title>Un titre &amp; une esperluette</title>
      <link>https://exemple.test/a</link>
      <guid>urn:a</guid>
      <description>&lt;p&gt;Du &lt;b&gt;balisage&lt;/b&gt; dans le resume.&lt;/p&gt;</description>
      <author>Alice</author>
      <pubDate>Tue, 21 Jul 2026 08:12:00 +0200</pubDate>
    </item>
    <item>
      <title>Deuxieme article</title>
      <link>https://exemple.test/b</link>
      <guid>urn:b</guid>
      <description>Rien de special.</description>
      <pubDate>Mon, 20 Jul 2026 18:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Carnet Atom</title>
  <entry>
    <title>Billet atom</title>
    <id>tag:exemple.test,2026:1</id>
    <link rel="edit" href="https://exemple.test/edit/1"/>
    <link rel="alternate" href="https://exemple.test/atom-1"/>
    <published>2026-07-21T10:30:00Z</published>
    <summary>Un resume court.</summary>
    <author><name>Bob</name></author>
  </entry>
</feed>
"""

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel><title>Vieux flux RDF</title></channel>
  <item>
    <title>Article RDF</title>
    <link>https://exemple.test/rdf-1</link>
    <description>Resume RDF.</description>
    <dc:date>2026-07-19T09:00:00+02:00</dc:date>
    <dc:creator>Carol</dc:creator>
  </item>
</rdf:RDF>
"""


# ══════════════════════════════════════════════════════════════════════
#  Analyse — le chemin bibliothèque standard, celui qui doit toujours marcher
# ══════════════════════════════════════════════════════════════════════

class TestParserStdlib:
    """Exercé directement, sans passer par ``parse()`` : sur une machine où
    ``feedparser`` est installé, ``parse()`` ne prendrait jamais ce chemin et
    le repli ne serait plus testé nulle part — exactement l'angle mort qui a
    laissé la panne d'origine s'installer."""

    def test_rss2(self):
        feed = parser._parse_stdlib(RSS2)
        assert feed.title == "Journal d'exemple"
        assert len(feed.entries) == 2
        premier = feed.entries[0]
        assert premier.uid == "urn:a"
        assert premier.title == "Un titre & une esperluette"
        assert premier.link == "https://exemple.test/a"
        assert premier.author == "Alice"
        assert premier.published_at is not None
        assert premier.published_at.year == 2026

    def test_le_balisage_du_resume_est_reduit_en_texte(self):
        """Un resume RSS est du HTML fourni par un tiers ; il n'est affiché
        qu'en texte, donc il est nettoyé une fois, ici."""
        feed = parser._parse_stdlib(RSS2)
        resume = feed.entries[0].summary
        assert "<" not in resume and ">" not in resume
        assert "balisage" in resume

    def test_atom_prend_le_lien_alternate(self):
        feed = parser._parse_stdlib(ATOM)
        assert feed.title == "Carnet Atom"
        entry = feed.entries[0]
        # `rel="edit"` vient en premier dans le document : le prendre
        # enverrait le lecteur sur une URL d'édition d'API.
        assert entry.link == "https://exemple.test/atom-1"
        assert entry.uid == "tag:exemple.test,2026:1"
        assert entry.author == "Bob"

    def test_rdf(self):
        feed = parser._parse_stdlib(RDF)
        assert len(feed.entries) == 1
        entry = feed.entries[0]
        assert entry.title == "Article RDF"
        assert entry.author == "Carol"
        assert entry.published_at is not None

    def test_xml_invalide_donne_une_erreur_pas_une_exception(self):
        feed = parser._parse_stdlib(b"<rss><channel><item>")
        assert feed.entries == []
        assert feed.error

    def test_format_inconnu_est_nomme(self):
        feed = parser._parse_stdlib(b"<html><body>pas un flux</body></html>")
        assert feed.entries == []
        assert "reconnu" in feed.error.lower()


class TestDates:
    def test_rfc822(self):
        d = parser.parse_date("Tue, 21 Jul 2026 08:12:00 +0200")
        assert d is not None and d.tzinfo is not None
        assert d.hour == 8

    def test_iso8601_avec_z(self):
        d = parser.parse_date("2026-07-21T10:30:00Z")
        assert d is not None and d.tzinfo is not None

    def test_date_absente_ou_illisible(self):
        assert parser.parse_date("") is None
        assert parser.parse_date("la semaine derniere") is None

    def test_sans_fuseau_on_suppose_utc(self):
        """Supposer *local* daterait un flux etranger dans le futur, et
        l'ordre d'affichage passerait devant des articles plus recents."""
        d = parser.parse_date("2026-07-21T10:30:00")
        assert d is not None and d.tzinfo is not None
        assert d.utcoffset().total_seconds() == 0


def test_empreinte_stable_et_portee_au_flux():
    a = parser.entry_hash("urn:a", "https://un.test/feed")
    assert a == parser.entry_hash("urn:a", "https://un.test/feed")
    # Deux flux qui republient le même article restent deux lignes : c'est ce
    # qui permet de dire « vu sur tel flux ».
    assert a != parser.entry_hash("urn:a", "https://autre.test/feed")


def test_parse_public_ne_leve_jamais():
    for octets in (b"", b"\x00\x01\x02", b"<rss>", RSS2):
        assert parser.parse(octets) is not None


# ══════════════════════════════════════════════════════════════════════
#  Disponibilité — la panne d'origine
# ══════════════════════════════════════════════════════════════════════

def test_module_disponible_sans_feedparser(monkeypatch):
    """``is_available()`` renvoyait ``False`` sans ``feedparser``, dependance
    absente de requirements.txt : le module n'a jamais tourne sur une
    installation neuve, et rien ne le disait."""
    import builtins

    reel = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "feedparser":
            raise ImportError("feedparser absent (simulé)")
        return reel(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert RSSModule().is_available() is True
    assert parser.which_parser() == "stdlib"
    assert parser.parse(RSS2).entries, "le repli doit produire des articles"


# ══════════════════════════════════════════════════════════════════════
#  Relevé — sans réseau
# ══════════════════════════════════════════════════════════════════════

def _sans_reseau(module, monkeypatch, reponses):
    """Remplace le seul point qui touche le réseau.

    Tout le reste — analyse, déduplication, écriture, élagage, événements —
    s'exécute réellement. ``reponses`` associe une URL à ``octets`` ou à une
    exception à lever (ou ``None`` pour un 304).
    """
    def faux_fetch(url, timeout, etag, modified):
        valeur = reponses[url]
        if isinstance(valeur, Exception):
            raise valeur
        if valeur is None:
            return None, etag, modified
        return valeur, "W/\"etag-1\"", "Tue, 21 Jul 2026 08:00:00 GMT"

    monkeypatch.setattr(module, "_fetch", faux_fetch)


@pytest.fixture
def module(monkeypatch):
    m = RSSModule()
    # Réglages figés : les lire passerait par l'ORM et par la config réelle
    # du développeur, ce qui rendrait le résultat dépendant de sa machine.
    monkeypatch.setattr(m, "_settings", _fige(PollSettings()))
    return m


def _fige(conf: PollSettings):
    async def _lire():
        return conf
    return _lire


def _feed(**kw):
    from modules.plugins.rss.models import RSSFeed
    params = {"name": "Exemple", "url": "https://exemple.test/feed"}
    params.update(kw)
    return RSSFeed.objects.create(**params)


@pytest.mark.django_db(transaction=True)
class TestPoll:
    async def test_premier_releve_stocke_et_publie(self, module, monkeypatch):
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSEntry

        feed = await sync_to_async(_feed)()
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})
        emis = _capture_evenements(monkeypatch)

        report = await module.poll()

        assert report.new_entries == 2
        assert report.failed == 0
        assert await sync_to_async(RSSEntry.objects.count)() == 2
        assert [e.event_type for e in emis] == ["rss.new_entry"] * 2
        assert emis[0].data["feed_name"] == "Exemple"

    async def test_second_releve_ne_republie_rien(self, module, monkeypatch):
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSEntry

        feed = await sync_to_async(_feed)()
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})
        await module.poll()
        emis = _capture_evenements(monkeypatch)

        report = await module.poll()

        assert report.new_entries == 0
        assert emis == []
        assert await sync_to_async(RSSEntry.objects.count)() == 2

    async def test_304_ne_touche_a_rien_et_est_compte(self, module, monkeypatch):
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSEntry

        feed = await sync_to_async(_feed)()
        _sans_reseau(module, monkeypatch, {feed.url: None})

        report = await module.poll()

        assert report.unchanged == 1
        assert report.new_entries == 0
        assert await sync_to_async(RSSEntry.objects.count)() == 0

    async def test_un_flux_en_panne_n_empeche_pas_les_autres(self, module, monkeypatch):
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSFeed

        casse = await sync_to_async(_feed)(name="Casse", url="https://casse.test/feed")
        bon = await sync_to_async(_feed)(name="Bon", url="https://bon.test/feed")
        _sans_reseau(module, monkeypatch, {
            casse.url: OSError("injoignable"),
            bon.url: RSS2,
        })

        report = await module.poll()

        assert report.failed == 1
        assert report.new_entries == 2, "le flux sain doit avoir été relevé"

        # L'échec est *stocké* : un flux mort ressemblait exactement à un flux
        # calme, ce qui rendait la panne invisible sur la page.
        relu = await sync_to_async(RSSFeed.objects.get)(pk=casse.pk)
        assert relu.error_count == 1
        assert "injoignable" in relu.last_error
        assert relu.last_error_at is not None

    async def test_un_releve_reussi_efface_l_erreur(self, module, monkeypatch):
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSFeed

        feed = await sync_to_async(_feed)()
        _sans_reseau(module, monkeypatch, {feed.url: OSError("coupure")})
        await module.poll()
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})

        await module.poll()

        relu = await sync_to_async(RSSFeed.objects.get)(pk=feed.pk)
        assert relu.error_count == 0
        assert relu.last_error == ""
        assert relu.etag, "l'ETag doit être conservé pour le relevé conditionnel"

    async def test_plafond_par_tour(self, module, monkeypatch):
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSEntry

        monkeypatch.setattr(module, "_settings", _fige(PollSettings(max_entries=1)))
        feed = await sync_to_async(_feed)()
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})

        report = await module.poll()

        assert report.new_entries == 1
        assert await sync_to_async(RSSEntry.objects.count)() == 1

    async def test_l_interrupteur_global_coupe_les_evenements(self, module, monkeypatch):
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSEntry

        monkeypatch.setattr(module, "_settings", _fige(PollSettings(emit_events=False)))
        feed = await sync_to_async(_feed)()
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})
        emis = _capture_evenements(monkeypatch)

        report = await module.poll()

        # Silencieux ne veut pas dire aveugle : les articles sont bien là.
        assert report.new_entries == 2
        assert await sync_to_async(RSSEntry.objects.count)() == 2
        assert emis == []

    async def test_un_flux_peut_se_taire_seul(self, module, monkeypatch):
        from asgiref.sync import sync_to_async

        feed = await sync_to_async(_feed)(emit_events=False)
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})
        emis = _capture_evenements(monkeypatch)

        assert (await module.poll()).new_entries == 2
        assert emis == []

    async def test_les_mots_cles_du_flux_filtrent_ce_qui_est_signale(self, module, monkeypatch):
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSEntry

        feed = await sync_to_async(_feed)(keywords="esperluette")
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})
        emis = _capture_evenements(monkeypatch)

        report = await module.poll()

        assert report.new_entries == 2, "tout est stocké, le filtre ne perd rien"
        assert await sync_to_async(RSSEntry.objects.count)() == 2
        assert len(emis) == 1
        assert "esperluette" in emis[0].data["title"]

    async def test_un_mot_d_alerte_interrompt_mika(self, module, monkeypatch):
        from asgiref.sync import sync_to_async

        monkeypatch.setattr(module, "_settings", _fige(
            PollSettings(alert_keywords=("esperluette",), max_alerts=5),
        ))
        feed = await sync_to_async(_feed)()
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})
        _capture_evenements(monkeypatch)

        alertes = []

        async def faux_notify(notification):
            alertes.append(notification)
            return None

        module.set_notify_ai(faux_notify)
        await module.poll()

        assert len(alertes) == 1, "seul l'article contenant le mot doit alerter"
        assert "esperluette" in alertes[0].summary.lower()

    async def test_les_alertes_sont_plafonnees(self, module, monkeypatch):
        """Un mot-clé trop large ne doit pas pouvoir déclencher trente
        interruptions : chacune coûte un tour de pipeline complet."""
        from asgiref.sync import sync_to_async

        monkeypatch.setattr(module, "_settings", _fige(
            PollSettings(alert_keywords=("article", "titre"), max_alerts=1),
        ))
        feed = await sync_to_async(_feed)()
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})
        _capture_evenements(monkeypatch)

        alertes = []

        async def faux_notify(notification):
            alertes.append(notification)
            return None

        module.set_notify_ai(faux_notify)
        await module.poll()

        assert len(alertes) == 1

    async def test_le_titre_du_flux_remplace_l_etiquette_provisoire(self, module, monkeypatch):
        """Coller une URL suffit : l'hôte sert d'étiquette, puis le premier
        relevé apporte le vrai titre. Un nom choisi, lui, n'est pas touché."""
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSFeed

        provisoire = await sync_to_async(_feed)(name="exemple.test")
        choisi = await sync_to_async(_feed)(
            name="Mon flux à moi", url="https://autre.test/feed",
        )
        _sans_reseau(module, monkeypatch, {
            provisoire.url: RSS2, choisi.url: RSS2,
        })

        await module.poll()

        assert (await sync_to_async(RSSFeed.objects.get)(pk=provisoire.pk)).name \
            == "Journal d'exemple"
        assert (await sync_to_async(RSSFeed.objects.get)(pk=choisi.pk)).name \
            == "Mon flux à moi"

    async def test_un_flux_suspendu_n_est_pas_releve(self, module, monkeypatch):
        from asgiref.sync import sync_to_async

        feed = await sync_to_async(_feed)(is_active=False)
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})

        report = await module.poll()

        assert report.feeds == 0
        assert report.new_entries == 0

    async def test_elagage_par_flux(self, module, monkeypatch):
        from asgiref.sync import sync_to_async
        from modules.plugins.rss.models import RSSEntry

        monkeypatch.setattr(module, "_settings", _fige(PollSettings(keep_per_feed=1)))
        feed = await sync_to_async(_feed)()
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})

        await module.poll()

        assert await sync_to_async(RSSEntry.objects.count)() == 1

    async def test_les_titres_de_l_invite_sont_en_ram(self, module, monkeypatch):
        """``get_context`` est appelé depuis une coroutine, où toute requête
        ORM lève ``SynchronousOnlyOperation`` — que le collecteur avale. Le
        bloc disparaîtrait donc de chaque invite sans que rien ne le dise."""
        from asgiref.sync import sync_to_async

        feed = await sync_to_async(_feed)()
        _sans_reseau(module, monkeypatch, {feed.url: RSS2})
        await module.poll()

        # Pas de sync_to_async ici, volontairement : on est dans la boucle.
        contexte = module.get_context("web_x")
        assert "2 article(s) non lu(s)" in contexte
        assert "Exemple" in contexte


def _capture_evenements(monkeypatch) -> list:
    """Intercepte le bus. Les évènements sont ce que la conscience paye —
    combien il y en a est donc un fait à tester, pas un détail."""
    from modules.manager import module_manager

    recus = []

    async def faux_emit(event):
        recus.append(event)

    monkeypatch.setattr(module_manager, "emit_event", faux_emit)
    return recus


# ══════════════════════════════════════════════════════════════════════
#  Configuration — les flux éditables depuis le tableau de bord
# ══════════════════════════════════════════════════════════════════════

def _item_feeds():
    from configs.registry import registry
    item = registry.get("rss.feeds")
    assert item is not None, "rss.feeds doit être déclaré au registre"
    return item


@pytest.mark.django_db
class TestConfigBackend:
    def test_le_backend_est_branche_sur_le_modele(self):
        """Sans ça les lignes atterriraient dans ``ConfigRecordItem`` et le
        tableau de bord deviendrait une seconde source de vérité."""
        from configs import backends
        from modules.plugins.rss.config_backend import RSSFeedBackend

        assert isinstance(backends.resolve("rss.feeds"), RSSFeedBackend)

    def test_ajout_lecture_modification_suppression(self):
        from configs.service import config_service
        from modules.plugins.rss.models import RSSFeed

        config_service.add_row("rss.feeds", {
            "url": "https://ajout.test/feed", "name": "Ajouté",
            "category": "Tech", "keywords": "python", "emit_events": True,
        })
        feed = RSSFeed.objects.get(url="https://ajout.test/feed")
        assert feed.name == "Ajouté" and feed.category == "Tech"

        rows = config_service.list_rows("rss.feeds")
        assert [r["payload"]["name"] for r in rows] == ["Ajouté"]

        config_service.update_row("rss.feeds", str(feed.pk), {
            "url": feed.url, "name": "Renommé",
            "category": "Tech", "keywords": "", "emit_events": False,
        })
        feed.refresh_from_db()
        assert feed.name == "Renommé" and feed.emit_events is False

        config_service.delete_row("rss.feeds", str(feed.pk))
        assert not RSSFeed.objects.filter(pk=feed.pk).exists()

    def test_url_manquante_ou_absurde_refusee(self):
        from modules.plugins.rss.config_backend import RSSFeedBackend

        backend = RSSFeedBackend()
        item = _item_feeds()
        with pytest.raises(ValueError):
            backend.add_row(item, {"name": "Sans URL", "url": ""})
        with pytest.raises(ValueError):
            backend.add_row(item, {"name": "Bizarre", "url": "ftp://ailleurs.test/f"})

    def test_doublon_refuse_avec_un_message(self):
        """La contrainte d'unicité remonterait sinon en 500 au lieu d'un
        message au-dessus du formulaire."""
        from modules.plugins.rss.config_backend import RSSFeedBackend

        backend = RSSFeedBackend()
        item = _item_feeds()
        backend.add_row(item, {"url": "https://double.test/feed", "name": "Un"})
        with pytest.raises(ValueError, match="déjà suivi"):
            backend.add_row(item, {"url": "https://double.test/feed", "name": "Deux"})

    def test_coller_une_url_suffit(self):
        from modules.plugins.rss.config_backend import RSSFeedBackend

        row = RSSFeedBackend().add_row(
            _item_feeds(), {"url": "https://sansnom.test/feed"},
        )
        assert row["payload"]["name"] == "sansnom.test"

    def test_changer_d_url_oublie_l_etag(self):
        """Garder l'ETag d'une autre ressource ferait répondre 304 à tort, et
        le nouveau flux resterait éternellement vide."""
        from modules.plugins.rss.config_backend import RSSFeedBackend
        from modules.plugins.rss.models import RSSFeed

        backend = RSSFeedBackend()
        item = _item_feeds()
        row = backend.add_row(item, {"url": "https://avant.test/feed", "name": "F"})
        RSSFeed.objects.filter(pk=row["row_id"]).update(
            etag='W/"abc"', http_last_modified="hier",
        )

        backend.update_row(item, row["row_id"], {
            "url": "https://apres.test/feed", "name": "F",
        })

        feed = RSSFeed.objects.get(pk=row["row_id"])
        assert feed.etag == "" and feed.http_last_modified == ""

    def test_les_reglages_ont_tous_un_defaut_utilisable(self):
        """La section ne contenait qu'un champ ; ces défauts sont ce qui fait
        qu'une installation neuve relève quelque chose sans rien régler."""
        from configs.registry import registry

        attendus = {
            "rss.poll_interval", "rss.fetch_timeout", "rss.max_entries_per_poll",
            "rss.keep_per_feed", "rss.emit_events", "rss.alert_keywords",
            "rss.max_alerts_per_poll", "rss.context_items",
        }
        declares = {
            i.key: i for i in registry.all_items() if i.key.startswith("rss.")
        }
        assert attendus <= set(declares)
        for key in attendus:
            assert declares[key].default is not None, key


def test_flux_par_defaut_bien_formes():
    """Semés au premier démarrage : un module de veille livré vide ne se
    distingue pas d'un module cassé — c'était le symptôme."""
    urls = [f["url"] for f in DEFAULT_FEEDS]
    assert len(urls) == len(set(urls)), "URL dupliquée dans les flux par défaut"
    assert len(DEFAULT_FEEDS) >= 5
    for f in DEFAULT_FEEDS:
        assert f["url"].startswith("https://"), f
        assert f["name"] and f["category"], f


@pytest.mark.django_db
def test_amorcage_ne_repasse_pas_sur_une_table_non_vide():
    """Supprimer tous ses flux est une décision, pas un état à corriger au
    redémarrage suivant."""
    from modules.plugins.rss.models import RSSFeed

    module = RSSModule()
    module._seed_feeds()
    assert RSSFeed.objects.count() == len(DEFAULT_FEEDS)

    RSSFeed.objects.all().delete()
    RSSFeed.objects.create(name="Le mien", url="https://mien.test/feed")
    module._seed_feeds()
    assert RSSFeed.objects.count() == 1


# ══════════════════════════════════════════════════════════════════════
#  Espace d'administration
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestEspace:
    def _entree(self, **kw):
        from modules.plugins.rss.models import RSSEntry

        feed = kw.pop("feed", None) or _feed()
        params = {
            "feed": feed, "entry_hash": "h1", "title": "Un titre",
            "summary": "Un résumé", "link": "https://exemple.test/a",
        }
        params.update(kw)
        return RSSEntry.objects.create(**params)

    def test_les_panneaux_sont_declares(self):
        from GestionSysteme import panels

        cles = [p.key for p in panels.panels_for("rss")]
        assert cles == ["articles", "flux"], (
            "le module n'en déclarait aucun : son espace se réduisait à l'état "
            "et à un champ de configuration"
        )

    @pytest.mark.parametrize("panneau", ["articles", "flux", "configuration"])
    def test_chaque_onglet_repond(self, client, panneau):
        from django.urls import reverse

        self._entree()
        url = reverse("gestionsysteme:module-panel", args=["rss", panneau])
        assert client.get(url).status_code == 200

    def test_la_fiche_d_un_article_s_ouvre_dans_l_url(self, client):
        from django.urls import reverse

        entry = self._entree(summary="Le corps du résumé")
        url = reverse("gestionsysteme:module-panel", args=["rss", "articles"])
        page = client.get(url, {"article": entry.pk})
        assert page.status_code == 200
        assert "Le corps du résumé" in page.content.decode()

    def test_un_article_disparu_ne_casse_pas_la_page(self, client):
        from django.urls import reverse

        url = reverse("gestionsysteme:module-panel", args=["rss", "articles"])
        page = client.get(url, {"article": 999999})
        assert page.status_code == 200
        assert "n&#x27;est plus en base" in page.content.decode()

    def test_le_filtre_flux_filtre_vraiment(self, client):
        from django.urls import reverse

        a = _feed(name="Flux A", url="https://a.test/f")
        b = _feed(name="Flux B", url="https://b.test/f")
        self._entree(feed=a, title="Article de A", entry_hash="ha")
        self._entree(feed=b, title="Article de B", entry_hash="hb")

        url = reverse("gestionsysteme:module-panel", args=["rss", "articles"])
        corps = client.get(url, {"flux": a.pk}).content.decode()
        assert "Article de A" in corps
        assert "Article de B" not in corps

    def test_un_flux_inconnu_dans_l_url_n_atteint_pas_l_orm(self, client):
        """Toute valeur d'URL qui atteint l'ORM passe par une liste fermée."""
        from django.urls import reverse

        _feed(name="A", url="https://a.test/f")
        _feed(name="B", url="https://b.test/f")
        url = reverse("gestionsysteme:module-panel", args=["rss", "articles"])
        assert client.get(url, {"flux": "1) OR 1=1"}).status_code == 200

    def test_un_flux_hostile_ne_produit_jamais_de_balisage(self, client):
        """Bout en bout, sur le chemin réel : octets du flux → relevé → base →
        page. Un flux tiers est du contenu hostile par défaut, et c'est
        exactement ce que l'ancien rendu par ``innerHTML`` injectait tel quel.

        L'assertion porte sur l'**absence du contenu**, pas sur son
        échappement : vérifier que ``&lt;script&gt;`` est bien échappé ne
        prouverait que le fonctionnement de Django. Ici le balisage est retiré
        au relevé, donc il n'atteint jamais le gabarit.
        """
        from asgiref.sync import async_to_sync
        from django.urls import reverse
        from modules.plugins.rss.models import RSSEntry

        hostile = (
            b'<?xml version="1.0"?><rss version="2.0"><channel>'
            b"<title>Piege</title><item>"
            b"<title>&lt;script&gt;alert(1)&lt;/script&gt;</title>"
            b"<link>https://hostile.test/a</link><guid>urn:x</guid>"
            b"<description>&lt;img src=x onerror=alert(2)&gt;suite&lt;/img&gt;</description>"
            b"</item></channel></rss>"
        )

        module = RSSModule()
        module._settings = _fige(PollSettings())
        feed = _feed(name="Piege", url="https://hostile.test/feed")
        module._fetch = lambda url, timeout, etag, modified: (hostile, "", "")

        async_to_sync(module.poll)()

        entry = RSSEntry.objects.get(feed=feed)
        assert "<" not in entry.title and "<" not in entry.summary
        assert "suite" in entry.summary, "le texte utile doit survivre au nettoyage"

        url = reverse("gestionsysteme:module-panel", args=["rss", "articles"])
        corps = client.get(url, {"article": entry.pk}).content.decode()
        # Une balise parvenue jusqu'au gabarit s'y lirait échappée : son
        # absence sous cette forme prouve qu'elle n'y est jamais arrivée.
        assert "&lt;script" not in corps
        assert "&lt;img" not in corps
        assert "onerror" not in corps

    def test_tout_marquer_lu(self, client):
        from django.urls import reverse
        from modules.plugins.rss.models import RSSEntry

        self._entree()
        url = reverse(
            "gestionsysteme:module-action", args=["rss", "articles", "tout_lu"],
        )
        assert client.post(url).status_code in (302, 200)
        assert RSSEntry.objects.filter(is_read=False).count() == 0
