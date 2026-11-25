import { describe, expect, it } from "vitest";
import { ApiError } from "../api/moi";
import { correctButton, correctedText, correctTurn, countLabel, countSpan, errorText, markToFill, refusalText, toFill } from "./compose";

describe("le compte d'un texte borné", () => {
  it("se montre près de la borne", () => {
    expect(countLabel("x".repeat(100), 20_000)).toBe("");
    expect(countLabel("x".repeat(16_000), 20_000)).toBe("16\u202f000 / 20\u202f000");
    expect(countLabel("x".repeat(4000), 4000)).toBe("4\u202f000 / 4\u202f000 — la limite");
    expect(countSpan("x".repeat(4000), 4000)).toContain(" full");
  });
});

describe("« [À COMPLÉTER »", () => {
  it("se reconnaît sous toutes ses graphies, comme ports/drafts.py::to_fill", () => {
    expect(toFill("Nous pourrions démarrer le [À COMPLÉTER : date].")).toBe(true);
    expect(toFill("[a completer]")).toBe(true);
    expect(toFill("[ À remplir ]")).toBe(true);
    expect(toFill("［À PRÉCISER］")).toBe(true); // crochets pleine chasse
    expect(toFill("À COMPLÉTER sans crochet")).toBe(false);
    expect(toFill("Rien à compléter ici.", "")).toBe(false);
  });
  it("se marque en rouge dans un texte déjà échappé, le reste intact", () => {
    expect(markToFill("le [À COMPLÉTER : date] et [note] &amp; fin")).toBe('le <mark class="completer">[À COMPLÉTER : date]</mark> et [note] &amp; fin');
    expect(markToFill("ouvert [À COMPLÉTER")).toBe('ouvert <mark class="completer">[À COMPLÉTER</mark>');
  });
});

describe("le texte d'un refus", () => {
  it("un refus de borne se dit par son champ, en mots", () => {
    expect(refusalText("« body » : 20000 caractères au plus.", { body: "20000 caractères au plus" })).toBe("Message : 20000 caractères au plus");
    expect(refusalText("Le formulaire a des erreurs.", { to: "adresse invalide" })).toBe("Le formulaire a des erreurs. (À : adresse invalide)");
    expect(refusalText("Introuvable.", {})).toBe("Introuvable.");
    expect(errorText(new ApiError(400, "« to » : 300 caractères au plus.", { to: "300 caractères au plus" }))).toBe("À : 300 caractères au plus");
  });
});

describe("« Corriger » (ADR 0307) : ce qu'il dit une fois fait", () => {
  it("combien de fautes, ou aucune", () => {
    expect(correctedText(0)).toBe("Aucune faute : ton texte reste tel quel.");
    expect(correctedText(1)).toBe("1 faute corrigée.");
    expect(correctedText(3)).toBe("3 fautes corrigées.");
  });
  it("ce qui a été écarté parce que ça touchait aux mots", () => {
    expect(correctedText(2, 1)).toBe("2 fautes corrigées ; 1 changement écarté : il touchait aux mots.");
    expect(correctedText(1, 3)).toBe("1 faute corrigée ; 3 changements écartés : ils touchaient aux mots.");
    expect(correctedText(0, 4)).toBe("La correction touchait aux mots : rien n'a été changé.");
  });
  it("posée seulement là où on l'a demandée, sur le texte d'alors", () => {
    expect(correctTurn("salu", "salu", true)).toBe("put");
    expect(correctTurn("salu", "salut toi", true)).toBe("moved"); // tu as continué d'écrire
    expect(correctTurn("salu", "salu", false)).toBe("gone"); // une autre discussion, un autre mail
    expect(correctTurn("salu", null, true)).toBe("gone"); // la fenêtre fermée, le mail parti
  });
  it("son bouton, allumé quand un modèle corrige", () => {
    expect(correctButton("data-corriger", true)).not.toContain("disabled");
  });
});
