import unittest

from mirette.export import en_html, en_texte
from mirette.facture import Facture, Ligne, numero_suivant


class TestFacture(unittest.TestCase):
    def setUp(self):
        self.facture = Facture("2026-0042", "Atelier Bravard", [
            Ligne("Pose d'une étagère", 2, 45.0, 20), Ligne("Livre de comptes", 1, 12.5, 5.5)])

    def test_totaux(self):
        self.assertEqual(self.facture.hors_taxes, 102.5)
        self.assertEqual(self.facture.tva, 18.69)
        self.assertEqual(self.facture.a_payer, 121.19)

    def test_un_sous_total_par_taux(self):
        self.assertEqual(sorted(self.facture.tva_par_taux()), [5.5, 20])

    def test_numero_suivant(self):
        self.assertEqual(numero_suivant("2026-0042"), "2026-0043")

    def test_exports(self):
        self.assertIn("Total à payer : 121.19 €", en_texte(self.facture))
        self.assertIn("<title>Facture 2026-0042</title>", en_html(self.facture))


if __name__ == "__main__":
    unittest.main()
