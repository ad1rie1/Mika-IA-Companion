"""Les noms d'émotion sont stockés en anglais et affichés en français.

Le nom canonique d'``emotion/types.py`` est ce que le modèle produit dans sa
balise ``[EMOTION:...]``, ce que la base garde et ce qui compose la variable
CSS ``--emo-<nom>``. Il ne peut donc pas être traduit à la source. Mais un
tableau de bord entièrement en français qui affiche « mischievous » au milieu
d'une phrase française laisse à l'opérateur le soin de la traduction, sur les
écrans mêmes qu'on ouvre parce que quelque chose ne va pas.

La traduction se fait donc au seul moment du rendu, en un endroit :
``formatting.emotion_fr``. Ce que ces tests protègent :

- la table couvre **exactement** les 29 émotions — une nouvelle émotion
  ajoutée sans libellé s'afficherait en anglais dans une interface française,
  sans rien casser, donc sans que personne ne le voie ;
- la **couleur** reste indexée sur le nom canonique. Les deux valeurs partent
  ensemble dans le même ``<span>`` et il serait facile de traduire les deux :
  ``var(--emo-curieuse)`` n'existe pas, la pastille deviendrait grise.
"""
from __future__ import annotations

import pytest

from GestionSysteme import formatting as fmt
from GestionSysteme import panels
from emotion.types import Emotion


class TestTable:

    def test_les_29_emotions_ont_un_libelle(self):
        manquantes = [e.value for e in Emotion if e.value not in fmt.EMOTION_FR]
        assert not manquantes, f"émotions sans libellé français : {manquantes}"

    def test_aucun_libelle_orphelin(self):
        connues = {e.value for e in Emotion}
        orphelins = [k for k in fmt.EMOTION_FR if k not in connues]
        assert not orphelins, f"libellés pour des émotions inexistantes : {orphelins}"

    def test_les_libelles_sont_traduits(self):
        """Un libellé identique à sa clé est une traduction oubliée.

        ``surprise`` est la seule collision légitime : le mot est le même dans
        les deux langues.
        """
        identiques = [
            k for k, v in fmt.EMOTION_FR.items() if k == v and k != "surprised"
        ]
        assert not identiques, f"non traduits : {identiques}"


class TestProseDuPrompt:
    """La même règle, appliquée aux couches émotionnelles du *prompt*.

    « tu te sens a peine amused (intensite: 0.3) » : des chiffres bruts et des
    libellés anglais dans une phrase française, exactement ce que le dépôt
    s'interdit pour le bloc identité (« never prints a number »). Un modèle
    moyen les récite tels quels à l'utilisateur.

    La table est **recopiée** dans ``emotion/state.py`` plutôt qu'importée :
    l'app d'administration dépend du domaine, l'inverse ferait dépendre le
    moteur d'émotion de GestionSystème. Ces tests verrouillent la copie.
    """

    def test_la_table_du_prompt_couvre_les_29_emotions(self):
        from emotion.state import EMOTION_PROMPT_FR

        assert set(EMOTION_PROMPT_FR) == {e.value for e in Emotion}

    def test_elle_ne_s_ecarte_d_EMOTION_FR_que_sur_bored(self):
        from emotion.state import EMOTION_PROMPT_FR

        ecarts = {
            k for k, v in EMOTION_PROMPT_FR.items() if fmt.EMOTION_FR[k] != v
        }
        assert ecarts == {"bored"}, ecarts

    def test_toutes_les_entrees_entrent_dans_la_phrase(self):
        """« s'ennuie » est un verbe : il ne rentre pas dans « tu te sens … »."""
        from emotion.state import EMOTION_PROMPT_FR

        verbes = [
            v for v in EMOTION_PROMPT_FR.values()
            if v.startswith("s'") or v.startswith("se ")
        ]
        assert not verbes, f"inutilisables après « tu te sens » : {verbes}"

    def test_aucun_chiffre_dans_la_prose_emotionnelle(self):
        import re

        for texte in _prose_emotionnelle():
            assert not re.search(r"\d", texte), texte

    def test_aucun_nom_anglais_dans_la_prose_emotionnelle(self):
        canoniques = {e.value for e in Emotion} - {"surprised"}
        for texte in _prose_emotionnelle():
            trouves = [nom for nom in canoniques if nom in texte]
            assert not trouves, f"{trouves} dans « {texte} »"

    def test_le_nom_canonique_reste_dans_to_dict(self):
        """La traduction s'arrête au rendu : ni le stockage ni la diffusion."""
        from emotion import pad
        from emotion.state import MessageEmotion, PersonMood

        mood = PersonMood(person_id="p")
        mood.dynamic.position = pad.label_to_pad(Emotion.MISCHIEVOUS, 0.8)
        assert mood.to_dict()["emotion"] == "mischievous"

        msg = MessageEmotion(
            emotion=Emotion.MELANCHOLIC, intensity=0.6,
            person_emotion=Emotion.MELANCHOLIC, person_intensity=0.6,
            global_emotion=Emotion.HAPPY, global_intensity=0.2,
            blend=((Emotion.MELANCHOLIC, 0.6),),
        )
        assert msg.to_dict()["emotion"] == "melancholic"
        assert msg.to_dict()["blend"][0]["emotion"] == "melancholic"


def _prose_emotionnelle():
    """Tout ce que les couches émotionnelles rendent au prompt."""
    from emotion import pad
    from emotion.state import GlobalMood, MessageEmotion, PersonMood

    for emotion in Emotion:
        for intensite in (0.15, 0.45, 0.95):
            mood = PersonMood(person_id="p")
            mood.dynamic.position = pad.label_to_pad(emotion, intensite)
            yield mood.to_prompt_description()

            globale = GlobalMood()
            globale.dynamic.position = pad.label_to_pad(emotion, intensite)
            yield globale.to_prompt_description(Emotion.HAPPY)

            yield MessageEmotion(
                emotion=emotion, intensity=intensite,
                person_emotion=emotion, person_intensity=intensite,
                global_emotion=Emotion.HAPPY, global_intensity=0.2,
            ).to_prompt_description()
            yield MessageEmotion(
                emotion=emotion, intensity=intensite,
                person_emotion=emotion, person_intensity=intensite,
                global_emotion=Emotion.HAPPY, global_intensity=0.2,
                blend=((emotion, intensite), (Emotion.NOSTALGIC, intensite)),
            ).to_prompt_description()


class TestRendu:

    def test_un_nom_connu_est_traduit(self):
        assert fmt.emotion_fr("curious") == "curieuse"
        assert fmt.emotion_fr("mischievous") == "malicieuse"

    def test_la_casse_et_les_espaces_ne_gênent_pas(self):
        assert fmt.emotion_fr("  Curious ") == "curieuse"

    def test_un_nom_inconnu_sort_tel_quel(self):
        """Contrairement à ``emotion_var``, pas de repli sur ``neutral`` : la
        sortie est du texte échappé, donc sans danger, et afficher la valeur
        brute dit « hors liste » au lieu de mentir avec « neutre »."""
        assert fmt.emotion_fr("euphorique") == "euphorique"

    def test_rien_donne_un_tiret(self):
        assert fmt.emotion_fr(None) == "—"
        assert fmt.emotion_fr("") == "—"

    def test_la_couleur_reste_sur_le_nom_canonique(self):
        """Traduire aussi la variable CSS produirait ``var(--emo-curieuse)``,
        qui n'existe pas : la pastille perdrait sa couleur en silence."""
        assert fmt.emotion_var("curious") == "var(--emo-curious)"


class TestCellulesDeModule:

    def test_la_cellule_traduit_le_texte_et_garde_le_nom(self):
        """Traduire ici couvre d'un coup tous les panneaux de modules, qui
        n'ont jamais à connaître le vocabulaire d'affichage."""
        cell = panels.emotion("melancholic", weight=0.4)
        assert cell.text == "mélancolique"
        assert cell.emotion == "melancholic"
        assert cell.ratio == pytest.approx(0.4)


@pytest.mark.django_db
class TestPages:

    def test_l_onglet_emotions_affiche_du_francais(self, client):
        from emotion.engine import emotion_engine
        from emotion import pad

        reponse = client.get("/gestion/interieur/emotions/")
        assert reponse.status_code == 200

        label, _ = pad.pad_to_label(emotion_engine.global_mood.dynamic.position)
        attendu = fmt.EMOTION_FR[label.value]

        html = reponse.content.decode()
        assert f">{attendu}</span>" in html or f"{attendu}\n" in html, (
            "l'humeur globale doit s'afficher traduite"
        )
        # La couleur passe toujours par le nom canonique.
        assert f"--emo-{label.value}" in html

    def test_la_barre_superieure_affiche_l_humeur_en_francais(self, client):
        """Le seul indicateur présent sur *toutes* les pages. Rendu côté
        serveur au premier affichage et rafraîchi par le même dictionnaire :
        un seul endroit décide comment une humeur s'écrit."""
        from GestionSysteme.shell import vitals

        assert vitals()["mood"].split()[0] in fmt.EMOTION_FR.values()

        charge = client.get("/gestion/api/vitaux").json()
        assert charge["mood"].split()[0] in fmt.EMOTION_FR.values()

    def test_l_etat_d_une_rumination_est_traduit(self, client):
        from conscience.models import Rumination

        Rumination.objects.create(
            summary="il n'a jamais répondu", emotion="anxious",
            intensity=0.6, status="active", themes=[],
        )
        html = client.get("/gestion/interieur/ruminations/").content.decode()
        assert "anxieuse" in html
        assert ">anxious<" not in html

    def test_les_analyses_ne_sortent_plus_un_dict_python(self, client):
        """La répartition était rendue avec ``{{ value }}`` — le ``repr`` d'un
        dict, accolades et guillemets compris, au milieu d'une liste de
        définitions. C'est pourtant la seule information de la carte."""
        from emotion.engine import emotion_engine
        from emotion.state import EmotionHistoryEntry, PersonMood

        mood = PersonMood(person_id="web_test")
        mood.history.append(EmotionHistoryEntry(
            timestamp=0.0, emotion=Emotion.CURIOUS,
            intensity=0.8, source="impulse",
        ))
        emotion_engine.person_moods["web_test"] = mood
        try:
            reponse = client.get("/gestion/interieur/emotions/")
            analyses = reponse.context["analytics"]
            assert isinstance(analyses["distribution"], list)
            assert analyses["distribution"][0]["emotion"] == "curious"

            html = reponse.content.decode()
            assert "curieuse" in html
            assert "{'curious'" not in html
        finally:
            emotion_engine.person_moods.pop("web_test", None)
