"""``mika console apercu`` : une Mika neuve, deux conversations, puis chaque page
exportée en clair et en sombre — aucune n'a échoué, aucune ne dépend du
serveur (feuille de style copiée, script retiré)."""

from __future__ import annotations

from mika.app.apercu import export


def test_the_console_exports_page_by_page(tmp_path):
    pages = export(tmp_path)
    assert len(pages) >= 60
    assert (tmp_path / "index.html").exists() and (tmp_path / "static" / "console.css").exists()
    for theme, attr in (("clair", "light"), ("sombre", "dark")):
        files = sorted((tmp_path / theme).glob("*.html"))
        assert len(files) == len(pages)
        for f in files:
            text = f.read_text(encoding="utf-8")
            assert f'data-theme="{attr}"' in text, f.name
            assert "a échoué" not in text and "Bloc inconnu" not in text, f.name
            assert "console.js" not in text and "../static/console.css" in text, f.name
