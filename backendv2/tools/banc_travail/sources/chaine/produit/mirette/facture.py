"""Les calculs d'une facture : ses lignes, ses totaux, sa TVA par taux, son numéro."""

from dataclasses import dataclass, field


@dataclass
class Ligne:
    libelle: str
    quantite: float
    prix: float
    tva: float = 20.0

    @property
    def hors_taxes(self) -> float:
        return self.quantite * self.prix


@dataclass
class Facture:
    numero: str
    client: str
    lignes: list[Ligne] = field(default_factory=list)

    @property
    def hors_taxes(self) -> float:
        return round(sum(ligne.hors_taxes for ligne in self.lignes), 2)

    def tva_par_taux(self) -> dict[float, float]:
        """La TVA due pour chaque taux de la facture."""
        par_taux: dict[float, float] = {}
        for ligne in self.lignes:
            par_taux[ligne.tva] = par_taux.get(ligne.tva, 0.0) + ligne.hors_taxes * ligne.tva / 100
        return par_taux

    @property
    def tva(self) -> float:
        # arrondie une seule fois, sur le total
        return round(sum(self.tva_par_taux().values()), 2)

    @property
    def a_payer(self) -> float:
        return round(self.hors_taxes + self.tva, 2)


def lire(donnees: dict) -> Facture:
    lignes = [Ligne(x["libelle"], x["quantite"], x["prix"], x.get("tva", 20.0)) for x in donnees.get("lignes", [])]
    return Facture(donnees["numero"], donnees["client"], lignes)


def numero_suivant(dernier: str) -> str:
    """Le numéro qui suit « 2026-0042 » : « 2026-0043 »."""
    annee, rang = dernier.split("-")
    return f"{annee}-{int(rang) + 1:04d}"
