import { describe, expect, it } from "vitest";
import {
  badgeOf,
  csvSeparator,
  isMarkdown,
  looksLikePdf,
  parseCsv,
  reasonWords,
  sortOf,
  textPreview,
  tile,
  typeLabel,
  TEXT_MAX_LINES,
} from "./files";

describe("la sorte d'un fichier, comme le serveur la dit (app/me/chat.py::sorte_of)", () => {
  it.each([
    ["tableau.jpg", "image/jpeg", "image", "image"],
    ["sans-extension", "image/png", "file", "image"],
    ["devis.pdf", "application/octet-stream", "file", "pdf"],
    ["devis.bin", "application/pdf", "file", "pdf"],
    ["comparatif.csv", "text/plain", "file", "tableau"],
    ["export", "text/csv; charset=utf-8", "file", "tableau"],
    ["notes.md", "", "file", "texte"],
    ["build.log", "application/octet-stream", "file", "texte"],
    ["donnees.json", "application/json", "file", "texte"],
    ["budget.xlsx", "application/vnd.ms-excel", "file", "autre"],
    ["voix.mp3", "audio/mpeg", "audio", "autre"],
    ["archive.zip", "", "file", "autre"],
  ])("%s (%s) : %s", (name, mime, kind, sorte) => {
    expect(sortOf(name, mime, kind)).toBe(sorte);
  });

  it("sa marque et son libellé", () => {
    expect(badgeOf("a.pdf", "pdf")).toBe("PDF");
    expect(badgeOf("a.tsv", "tableau")).toBe("CSV");
    expect(badgeOf("budget.xlsx", "autre")).toBe("XLSX");
    expect(badgeOf("sans", "autre")).toBe("");
    expect(typeLabel("photo.jpg", "image")).toBe("image JPEG");
    expect(typeLabel("notes.md", "texte")).toBe("Markdown");
    expect(typeLabel("notes", "texte", "text/markdown")).toBe("Markdown");
    expect(typeLabel("voix.mp3", "autre", "audio/mpeg")).toBe("son MP3");
    expect(isMarkdown("a.markdown")).toBe(true);
    expect(isMarkdown("a.txt", "text/plain")).toBe(false);
  });

  it("une tuile : la vignette d'une image à lire, sinon sa marque échappée", () => {
    expect(tile({ name: "a.png", sorte: "image", src: "/files/x", available: true })).toContain('<img data-file="/files/x"');
    expect(tile({ name: "a.png", sorte: "image", available: false })).not.toContain("<img");
    expect(tile({ name: 'x.<b>', sorte: "autre", available: true })).toContain("&lt;B&gt;");
  });

  it("pourquoi il ne se télécharge plus, en mots", () => {
    expect(reasonWords("retention")).toBe("trop vieux");
    expect(reasonWords("budget")).toBe("la place manquait");
    expect(reasonWords(undefined)).toBe("plus disponible");
  });
});

describe("ce que la visionneuse lit des octets", () => {
  const bytes = (s: string): Uint8Array => new TextEncoder().encode(s);

  it("un texte : UTF-8, la marque d'ordre et les fins de ligne Windows retirées, borné en lignes", () => {
    const t = textPreview(bytes("﻿un\r\ndeux\rtrois"));
    expect(t.lines).toEqual(["un", "deux", "trois"]);
    expect(t.truncated).toBe(false);
    const long = textPreview(bytes(Array.from({ length: TEXT_MAX_LINES + 10 }, (_, i) => `l${i}`).join("\n")));
    expect(long.lines).toHaveLength(TEXT_MAX_LINES);
    expect(long.truncated).toBe(true);
  });

  it("un CSV : son séparateur, les guillemets, les lignes vides ignorées, borné", () => {
    expect(csvSeparator("a;b;c\n1;2;3")).toBe(";");
    expect(csvSeparator("a,b\n1,2")).toBe(",");
    expect(csvSeparator("a\tb")).toBe("\t");
    expect(csvSeparator('"x;y",z,w')).toBe(",");
    const t = parseCsv('Poste;Montant\n"Main-d\'œuvre ; pose";"4 870"\n\n"dit ""oui""";12\n');
    expect(t.rows).toEqual([["Poste", "Montant"], ["Main-d'œuvre ; pose", "4 870"], ['dit "oui"', "12"]]);
    expect(t.columns).toBe(2);
    expect(t.truncated).toBe(false);
    const many = parseCsv(Array.from({ length: 30 }, (_, i) => `${i},x`).join("\n"), 10);
    expect(many.rows).toHaveLength(10);
    expect(many.truncated).toBe(true);
    expect(parseCsv("a,b\n1,2", 2).truncated).toBe(false);
  });

  it("un PDF se reconnaît à son en-tête, pas à son nom", () => {
    expect(looksLikePdf(bytes("%PDF-1.7\n…"))).toBe(true);
    expect(looksLikePdf(bytes("\n\n%PDF-1.4"))).toBe(true);
    expect(looksLikePdf(bytes("<html><script>"))).toBe(false);
    expect(looksLikePdf(bytes(""))).toBe(false);
  });
});
