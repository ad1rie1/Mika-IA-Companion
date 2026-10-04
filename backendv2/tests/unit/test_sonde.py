"""La sonde : une semaine de sa vie avec le vrai modèle configuré (``mika sim sonde``). Ici, un modèle factice
qui répond tout de suite — on vérifie la mécanique : la semaine va au bout sur le vrai noyau, ce qu'on en lit est
écrit, et la commande refuse proprement sans fournisseur (ADR 0043)."""

from __future__ import annotations

from mika.app import cli
from mika.app.composition import for_simulation
from mika.ports.llm import LLMRequest, LLMResponse
from mika.sim.sonde import run_probe


class Fake:
    name = "faux"

    def __init__(self) -> None:
        self.roles: list[str] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.roles.append(req.role)
        return LLMResponse("ah d'accord [EMOTION:happy:0.4]", model="faux")


def test_the_week_goes_to_the_end_and_is_written_down(tmp_path):
    fake = Fake()
    out = run_probe(for_simulation(), fake, tmp_path / "sonde", log=lambda _line: None)
    fil = (out / "fil.txt").read_text()
    assert "Adrien > salut mika, bien dormi ?" in fil and "Léo > il t'a dit quoi sur son taf ?" in fil
    assert "Mika → Adrien" in fil  # elle a répondu
    assert (out / "appels.jsonl").read_text().count("\n") == len(fake.roles) > 30
    bilan = (out / "bilan.txt").read_text()
    assert bilan.startswith(f"appels : {len(fake.roles)}") and "à Léo" in bilan


def test_without_a_configured_model_the_probe_says_so(tmp_path, capsys):
    assert cli.main(["--data", str(tmp_path / "v2"), "sim", "sonde", "--out", str(tmp_path / "sonde")]) == 2
    assert "mika llm backend" in capsys.readouterr().out


def test_the_second_week_goes_to_the_end_with_its_group_and_its_report(tmp_path):
    fake = Fake()
    out = run_probe(for_simulation(), fake, tmp_path / "sonde", log=lambda _line: None, which="2")
    fil = (out / "fil.txt").read_text()
    assert "Sam > salut Mikachu" in fil and "Julie > joyeux anniv Sam" in fil
    assert "Marc > @Mika toi tu sais comment il va ?" in fil and "Inès > tu dors ?" in fil
    assert "Mika → Sam" in fil
    bilan = (out / "bilan.txt").read_text()
    assert "le rappel du dentiste" in bilan and "ses 30 ans" in bilan and "dans le salon extérieur" in bilan
