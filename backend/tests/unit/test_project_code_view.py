"""Ce que la vue Code de la faculté garde pur (ADR 0297) : un diff mis en texte puis relu avec ses numéros, et la
lecture de l'hôte pour la console — gardée un moment (une erreur moins longtemps), bornée à la minute, relue une
fois par « relire »."""

from __future__ import annotations

import asyncio

from mika.faculties.projects import inspect_code as code
from mika.ports.workshop import LINE_ADDED, LINE_REMOVED, LINE_SAME, DiffLine, FileDiff, Hunk

SECOND = 1_000_000


def test_a_diff_put_in_text_reads_back_with_its_line_numbers():
    lines = (DiffLine(LINE_SAME, 9, 9, "PORT = 22"), DiffLine(LINE_REMOVED, 10, 0, "DELAI = 1"),
             DiffLine(LINE_ADDED, 0, 10, "DELAI = 2"), DiffLine(LINE_ADDED, 0, 11, ""),
             DiffLine(LINE_SAME, 11, 12, "def scan():"))
    f = FileDiff("outils/scan.py", hunks=(Hunk("@@ -9,3 +9,4 @@ def x():", lines),
                                          Hunk("@@ -40 +41 @@", (DiffLine(LINE_SAME, 40, 41, "# fin"),))))
    text = code.diff_text(f)
    assert text.splitlines()[0] == "@@ -9,3 +9,4 @@ def x():" and "+DELAI = 2" in text
    rows = code.diff_rows(text)
    assert [(r.kind, r.old, r.new, r.text) for r in rows if r.kind != "@"] == [
        (x.kind, x.old, x.new, x.text) for h in f.hunks for x in h.lines]
    assert [r.text for r in rows if r.kind == "@"] == ["@@ -9,3 +9,4 @@ def x():", "@@ -40 +41 @@"]
    assert code.diff_rows("") == [] and code.diff_rows("@@ -1 +1 @@\n\\ No newline at end of file") == [
        code.DiffRow("@", 0, 0, "@@ -1 +1 @@")]


class Host:
    def __init__(self) -> None:
        self.calls = 0

    async def read(self) -> str:
        self.calls += 1
        return f"lecture {self.calls}"


def test_the_console_reads_the_host_through_a_kept_and_bounded_read():
    host = Host()

    async def scenario() -> list:
        out = [await code.hosted(host, ("a",), 0, host.read),
               await code.hosted(host, ("a",), 30 * SECOND, host.read),  # gardée
               await code.hosted(host, ("a",), 31 * SECOND, host.read, fresh="25"),  # « relire »
               await code.hosted(host, ("a",), (31 + code.HOST_KEPT_S) * SECOND, host.read)]  # périmée
        # la borne : pas plus de HOST_READS lectures par minute ; au-delà, ce qui est gardé (même vieux), ou rien
        at = 1000 * SECOND
        out.append(await code.hosted(host, ("d",), at, host.read))
        later = at + (code.HOST_KEPT_S + 1) * SECOND
        for n in range(code.HOST_READS):
            await code.hosted(host, ("b", n), later, host.read)
        out.append(await code.hosted(host, ("c",), later, host.read))
        out.append(await code.hosted(host, ("d",), later, host.read))
        out.append(await code.hosted(host, ("c",), later + code.HOST_WINDOW_S * SECOND, host.read))
        return out

    got = asyncio.run(scenario())
    assert got[:4] == [("lecture 1", 0), ("lecture 1", 0), ("lecture 2", 31 * SECOND),
                       ("lecture 3", (31 + code.HOST_KEPT_S) * SECOND)]
    assert got[4] == ("lecture 4", 1000 * SECOND)
    assert got[5] == (None, 0)  # la borne est atteinte, rien n'est gardé pour cette clé
    assert got[6] == ("lecture 4", 1000 * SECOND)  # gardée et vieillie : la console la montre plutôt que rien
    assert got[7][0] == f"lecture {4 + code.HOST_READS + 1}"  # la minute passée, elle relit


class Failing:
    """Un hôte qui ne répond pas, puis répond."""

    def __init__(self) -> None:
        self.calls = 0

    async def read(self) -> object:
        self.calls += 1
        return type("Read", (), {"error": "hôte injoignable" if self.calls == 1 else ""})()


def test_relire_reads_the_host_again_once_and_an_error_is_not_kept_two_minutes():
    """« Relire » porte un jeton (l'instant de la page qui l'a offert) : la lecture se refait une fois ; recharger la
    page qui garde ``frais`` dans son adresse ne joint plus l'hôte. Une erreur de l'hôte se garde moins longtemps qu'une
    réponse (la relecture de la relecture du 22 novembre : gardée 120 s, elle cachait un hôte revenu)."""
    host = Host()

    async def again() -> list:
        return [await code.hosted(host, ("a",), 0, host.read),
                await code.hosted(host, ("a",), 5 * SECOND, host.read, fresh="4000000"),  # « relire »
                await code.hosted(host, ("a",), 6 * SECOND, host.read, fresh="4000000"),  # la page rechargée
                await code.hosted(host, ("a",), 7 * SECOND, host.read, fresh="6500000")]  # un autre « relire »

    assert [x for x, _ in asyncio.run(again())] == ["lecture 1", "lecture 2", "lecture 2", "lecture 3"]
    failing = Failing()

    async def error() -> list:
        return [await code.hosted(failing, ("e",), 0, failing.read),
                await code.hosted(failing, ("e",), (code.HOST_ERROR_KEPT_S - 1) * SECOND, failing.read),
                await code.hosted(failing, ("e",), code.HOST_ERROR_KEPT_S * SECOND, failing.read)]

    got = [x.error for x, _ in asyncio.run(error())]
    assert got == ["hôte injoignable", "hôte injoignable", ""] and code.HOST_ERROR_KEPT_S < code.HOST_KEPT_S
    # le jeton : un nombre (l'instant de la page), sinon rien à relire
    assert [code.fresh_from(type("C", (), {"param": lambda self, k, v=v: v})()) for v in ("1764", "", "oui")] == [
        "1764", "", ""]
