"""L'intention du murmure dit d'où vient ce à quoi elle réagit.

Cas réel : le seul résumé `[France Info] "Une dangerosité particulière": au
cœur du transfert…` a fait murmurer « "dangerosité particulière", c'est qui
ça ? » : le modèle ignorait qu'il lisait un titre de presse.
"""

from types import SimpleNamespace

from conscience.intention import decrire_observation
from pipeline.inner_voice import SYSTEM_PROMPT


def _obs(source, resume="", **raw):
    return SimpleNamespace(source=source, summary=resume, raw_data=raw, pertinence=0.5)


class TestDecrireObservation:
    def test_rss_nomme_actualite_flux_titre_complet_et_chapo(self):
        titre = (
            '"Une dangerosité particulière": au cœur du transfert ultra-sécurisé '
            "d'un détenu vers le nouveau quartier de haute-sécurité de Réau"
        )
        texte = decrire_observation(_obs(
            "rss",
            resume=f"[France Info] {titre[:100]}",
            feed_name="France Info",
            title=titre,
            summary="L'administration pénitentiaire transfère ses détenus.",
        ))
        assert "titre d'actualité" in texte
        assert "« France Info »" in texte
        assert "haute-sécurité de Réau" in texte  # le titre entier, pas le résumé coupé
        assert "l'article dit : L'administration pénitentiaire" in texte

    def test_rss_sans_raw_data_retombe_sur_le_resume(self):
        obs = SimpleNamespace(source="rss", summary="[Le Monde] Titre", raw_data=None)
        texte = decrire_observation(obs)
        assert "titre d'actualité" in texte and "[Le Monde] Titre" in texte

    def test_email_nomme_expediteur_et_sujet(self):
        texte = decrire_observation(_obs("email", resume="x", **{"from": "alice@x.fr", "subject": "Réunion"}))
        assert texte == "réagir à un email reçu de alice@x.fr : « Réunion »"

    def test_autre_source_nommee(self):
        assert decrire_observation(_obs("frontend", resume="Message de user_2")) == (
            "réagir à ce que j'ai perçu via frontend : Message de user_2"
        )

    def test_rien_a_decrire(self):
        assert decrire_observation(_obs("rss")) == ""
        assert decrire_observation(SimpleNamespace()) == ""

    def test_stable_pour_une_meme_observation(self):
        obs = _obs("rss", feed_name="HN", title="Neovim", summary="don")
        assert decrire_observation(obs) == decrire_observation(obs)

    def test_retours_a_la_ligne_aplatis(self):
        texte = decrire_observation(_obs("rss", feed_name="F", title="a\nb"))
        assert "\n" not in texte


def test_la_consigne_dit_qu_une_citation_n_est_pas_une_personne():
    assert "citation" in SYSTEM_PROMPT and "actualité" in SYSTEM_PROMPT
