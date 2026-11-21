"""Les sorties d'une facture : texte brut et HTML."""

from html import escape

from .facture import Facture


def en_texte(facture: Facture) -> str:
    lignes = [f"Facture {facture.numero} — {facture.client}", ""]
    for x in facture.lignes:
        lignes.append(f"{x.libelle:<32} {x.quantite:>6g} x {x.prix:>8.2f} = {x.hors_taxes:>9.2f}")
    lignes += ["", f"Total hors taxes : {facture.hors_taxes:.2f} €"]
    for taux, montant in sorted(facture.tva_par_taux().items()):
        lignes.append(f"TVA {taux:g} % : {montant:.2f} €")
    lignes.append(f"Total à payer : {facture.a_payer:.2f} €")
    return "\n".join(lignes) + "\n"


def en_html(facture: Facture) -> str:
    rangs = "".join(
        f"<tr><td>{escape(x.libelle)}</td><td>{x.quantite:g}</td><td>{x.prix:.2f}</td><td>{x.hors_taxes:.2f}</td></tr>"
        for x in facture.lignes)
    taux = "".join(f"<p>TVA {t:g} % : {m:.2f} €</p>" for t, m in sorted(facture.tva_par_taux().items()))
    return (f"<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
            f"<title>Facture {escape(facture.numero)}</title></head><body>"
            f"<h1>Facture {escape(facture.numero)}</h1><p>{escape(facture.client)}</p>"
            f"<table><tr><th>Libellé</th><th>Quantité</th><th>Prix</th><th>Hors taxes</th></tr>{rangs}</table>"
            f"<p>Total hors taxes : {facture.hors_taxes:.2f} €</p>{taux}"
            f"<p><strong>Total à payer : {facture.a_payer:.2f} €</strong></p></body></html>\n")
