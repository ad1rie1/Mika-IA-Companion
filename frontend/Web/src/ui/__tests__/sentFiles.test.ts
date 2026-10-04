import { describe, it, expect } from "vitest";
import { mergeHistory, sentFiles } from "../chatSync";
import type { StoredMessage } from "../chatSync";
import type { HistoryEntry } from "../../types";

const ID = "0123456789abcdef0123456789abcdef";
const IMAGE = {
  id: ID,
  name: "dessin-0123ab.png",
  kind: "image",
  mime: "image/png",
  size: 1234,
  url: `/files/${ID}`,
  available: true,
};

describe("les fichiers qu'elle envoie (backendv2, ADR 0062–0063)", () => {
  it("garde un fichier dont l'adresse est exactement /files/<id>", () => {
    expect(sentFiles([IMAGE])).toEqual([IMAGE]);
    expect(sentFiles([{ ...IMAGE, kind: "file", name: "", available: undefined }])).toEqual([
      { ...IMAGE, kind: "file", name: "fichier", available: true },
    ]);
  });

  it("ignore une adresse vers une autre page ou un autre hôte, un identifiant douteux", () => {
    expect(sentFiles([{ ...IMAGE, url: "https://evil.example/files/" + ID }])).toEqual([]);
    expect(sentFiles([{ ...IMAGE, url: "/inspecteur/reglages" }])).toEqual([]);
    expect(sentFiles([{ ...IMAGE, id: "../../etc", url: "/files/../../etc" }])).toEqual([]);
    expect(sentFiles([{ ...IMAGE, url: `/files/${ID.replace("0", "f")}` }])).toEqual([]); // pas le sien
    expect(sentFiles(null)).toEqual([]);
    expect(sentFiles([null, 3, "x"])).toEqual([]);
  });

  it("un fichier retiré reste là, marqué indisponible", () => {
    expect(sentFiles([{ ...IMAGE, available: false }])[0].available).toBe(false);
  });

  it("l'historique rend ses fichiers à un message de Mika, jamais à un message de la personne", () => {
    const entries: HistoryEntry[] = [
      { id: 1, role: "user", text: "dessine-moi un chat", ts: 1, attachments: [{ name: "photo.png", kind: "image" }] },
      { id: 2, role: "assistant", text: "Le voilà !", ts: 2, attachments: [IMAGE] },
    ];
    const { history } = mergeHistory([], entries, 50);
    const [user, mika] = history;
    expect(user.files).toBeUndefined();
    expect(user.text).toBe("dessine-moi un chat [photo.png]");
    expect(mika.files).toEqual([IMAGE]);
  });

  it("une bulle reçue en direct, sans fichier gardé, les reprend de l'historique", () => {
    // (le texte d'une bulle en direct est déjà passé par stripProsody : pas de ponctuation ici)
    const live: StoredMessage[] = [{ text: "Le voilà", sender: "vtuber", ts: 2 }];
    const { history, adopted } = mergeHistory(
      live,
      [{ id: 2, role: "assistant", text: "Le voilà", ts: 2, attachments: [IMAGE] }],
      50
    );
    expect(adopted).toBe(1);
    expect(history[0].files).toEqual([IMAGE]);
  });
});
