import { describe, expect, it } from "vitest";
import { parseAddresses } from "../../shared/people";
import { chars } from "../../shared/text";
import {
  addressText,
  bodyLead,
  boxTitle,
  clip,
  draftReply,
  forwardSubject,
  howLabel,
  deleteTargets,
  keptRows,
  triageLabel,
  ofName,
  outgoingText,
  addPieces,
  recipientsText,
  replySubject,
  replyTargets,
  textHtml,
} from "./format";

describe("le nom d'une boîte partagée", () => {
  it("élide devant une voyelle ou un h", () => {
    expect(ofName("Léa")).toBe("de Léa");
    expect(ofName("Adrien")).toBe("d'Adrien");
    expect(ofName("Hélène")).toBe("d'Hélène");
    expect(ofName("Élodie")).toBe("d'Élodie");
    expect(ofName("")).toBe("");
  });
  it("« Boîte de Léa », le nom de la boîte en plus si elle en partage plusieurs", () => {
    const pro = { key: "pro", name: "Boîte Pro", level: "lire" as const, owner_name: "Adrien Moreau" };
    const perso = { key: "perso", name: "Perso", level: "servir" as const, owner_name: "Adrien Moreau" };
    expect(boxTitle(pro, [pro])).toBe("Boîte d'Adrien");
    expect(boxTitle(pro, [pro, perso])).toBe("Boîte Pro d'Adrien");
    expect(boxTitle({ ...pro, level: "proprietaire", owner_name: "" }, [])).toBe("Boîte Pro");
  });
});

describe("les adresses", () => {
  it("écrit « Nom <adresse> », cite un nom qui porte une virgule", () => {
    expect(addressText({ name: "Claire Dubois", address: "c@x.fr" })).toBe("Claire Dubois <c@x.fr>");
    expect(addressText({ name: "Dupré, Élodie", address: "e@x.fr" })).toBe('"Dupré, Élodie" <e@x.fr>');
    expect(addressText({ name: "", address: "e@x.fr" })).toBe("e@x.fr");
    // ce qui s'écrit se relit pareil
    expect(parseAddresses(addressText({ name: 'Le "Chef", Marc', address: "m@x.fr" }))).toEqual([{ name: 'Le "Chef", Marc', address: "m@x.fr" }]);
  });
});

describe("répondre", () => {
  const mail = {
    from: { name: "Claire Dubois", address: "claire@lumen.fr" },
    to: [{ name: "Adrien", address: "adrien@lumen.fr" }, { name: "Sophie", address: "sophie@lumen.fr" }],
    cc: [{ name: "Karim", address: "karim@lumen.fr" }, { name: "Claire Dubois", address: "claire@lumen.fr" }],
    reply_to: "",
    sent: false,
  };
  it("à l'expéditeur ; à tous, les autres en copie, sans la boîte ni doublon", () => {
    expect(replyTargets(mail, "adrien@lumen.fr", false)).toEqual({ to: [mail.from], cc: [] });
    expect(replyTargets(mail, "adrien@lumen.fr", true)).toEqual({
      to: [mail.from],
      cc: [{ name: "Sophie", address: "sophie@lumen.fr" }, { name: "Karim", address: "karim@lumen.fr" }],
    });
  });
  it("à son adresse de réponse quand elle en donne une", () => {
    expect(replyTargets({ ...mail, reply_to: "Équipe <equipe@lumen.fr>" }, "adrien@lumen.fr", false).to).toEqual([{ name: "Équipe", address: "equipe@lumen.fr" }]);
  });
  it("un mail parti de ta boîte : à ses destinataires", () => {
    const sent = { ...mail, from: { name: "Adrien", address: "adrien@lumen.fr" }, sent: true, cc: [] };
    expect(replyTargets(sent, "adrien@lumen.fr", false).to).toEqual([{ name: "Sophie", address: "sophie@lumen.fr" }]);
  });
  it("« Re: » et « Tr : » une seule fois", () => {
    expect(replySubject("Présentation")).toBe("Re: Présentation");
    expect(replySubject("RE: Présentation")).toBe("RE: Présentation");
    expect(forwardSubject("Devis")).toBe("Tr : Devis");
    expect(forwardSubject("Fwd: Devis")).toBe("Fwd: Devis");
  });
});

describe("le texte d'un mail", () => {
  it("des paragraphes, ses retours à la ligne, tout échappé", () => {
    expect(textHtml("Bonjour,\n\nLigne 1\nLigne <2>\n\n\nFin")).toBe("<p>Bonjour,</p><p>Ligne 1<br>Ligne &lt;2&gt;</p><p>Fin</p>");
  });
  it("ce qu'il cite en citation, imbriquée", () => {
    expect(textHtml("Merci.\n\nLe 3 nov., Claire a écrit :\n> Salut\n> >> avant\n\nAprès")).toBe(
      "<p>Merci.</p><p>Le 3 nov., Claire a écrit :</p><blockquote><p>Salut</p><blockquote><blockquote><p>avant</p></blockquote></blockquote></blockquote><p>Après</p>",
    );
  });
  it("ses adresses web en liens, sans la ponctuation qui suit", () => {
    expect(textHtml("Voir https://exemple.fr/a?b=1&c=2.")).toBe(
      '<p>Voir <a href="https://exemple.fr/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer">https://exemple.fr/a?b=1&amp;c=2</a>.</p>',
    );
    expect(textHtml('<script>alert(1)</script> "x"')).toBe("<p>&lt;script&gt;alert(1)&lt;/script&gt; &quot;x&quot;</p>");
  });
  it("le cœur d'un brouillon : le paragraphe après la formule d'appel", () => {
    expect(bodyLead("Bonjour Claire,\n\nMerci pour ta relecture.\nÀ jeudi.\n\nAdrien")).toBe("Merci pour ta relecture. À jeudi.");
    expect(bodyLead("Un seul paragraphe, assez long pour ne pas être une formule d'appel du tout, vraiment.")).toContain("Un seul paragraphe");
  });
});

describe("ce qu'elle en a fait", () => {
  it("son tri : lu, en attente, deviné, survolé (ADR 0240)", () => {
    expect(triageLabel("read")).toMatchObject({ text: "lu par son tri", row: true, note: "" });
    expect(triageLabel("waiting")?.note).toContain("prochain relevé");
    expect(triageLabel("guessed")).toMatchObject({ text: "tri deviné", row: true });
    expect(triageLabel("bulk")?.row).toBe(false); // un envoi en masse : rien sur la ligne
    expect(triageLabel("")).toBeNull();
    expect(triageLabel(undefined)).toBeNull(); // un serveur d'avant
  });
  it("« lu par elle », « archivé par elle », la corbeille", () => {
    expect(howLabel("")).toEqual({ text: "lu par elle", icon: "eye" });
    expect(howLabel("archivé")).toEqual({ text: "archivé par elle", icon: "archive" });
    expect(howLabel("corbeille").text).toBe("mis à la corbeille par elle");
  });
});

describe("les bornes d'un envoi : refusé plutôt que coupé (protocole-moi.md § 1)", () => {
  // sept collègues nommés, « Répondre à tous » : la forme « Nom <adresse> » dépasse les 300 caractères
  const team = Array.from({ length: 7 }, (_, i) => ({ name: `Collègue Numéro ${i + 1} du Service`, address: `collegue.numero${i + 1}@entreprise-exemple.test` }));

  it("les destinataires gardent leurs noms quand tout tient, sinon leurs seules adresses : aucun ne se perd", () => {
    const two = team.slice(0, 2);
    expect(recipientsText(two)).toBe(two.map(addressText).join(", "));
    expect(chars(team.map(addressText).join(", "))).toBeGreaterThan(300);
    const bare = recipientsText(team);
    expect(bare).toBe(team.map((p) => p.address).join(", "));
    expect(chars(bare!)).toBeLessThanOrEqual(300);
    expect(parseAddresses(bare!)).toHaveLength(7);
    // même nues, trop d'adresses : rien ne part
    const crowd = Array.from({ length: 12 }, (_, i) => ({ name: "", address: `personne.tres.longue${i}@entreprise-exemple.test` }));
    expect(recipientsText(crowd)).toBeNull();
  });

  it("joindre : ce qui tient dans les bornes de l'API, et le premier refus dit (ADR 0214)", () => {
    const mo = 1024 * 1024;
    const f = (name: string, size: number) => ({ name, size });
    const big = addPieces([f("a.pdf", 10)], [f("gros.bin", 25 * mo + 1), f("b.pdf", 20)]);
    expect(big.pieces.map((p) => p.name)).toEqual(["a.pdf", "b.pdf"]); // le refus ne retient pas les autres
    expect(big.problem).toBe("« gros.bin » est trop grosse : 25 Mo par pièce.");
    expect(addPieces([], [f("juste.bin", 25 * mo)]).problem).toBe("");
    expect(addPieces([f("a.pdf", 10)], [f("a.pdf", 10)])).toEqual({ pieces: [f("a.pdf", 10)], problem: "" }); // le même, une fois
    expect(addPieces([], [f("vide.txt", 0)]).problem).toBe("« vide.txt » est vide.");
    const full = Array.from({ length: 10 }, (_, i) => f(`p${i}`, 1));
    expect(addPieces(full, [f("onze", 1)]).problem).toBe("Un mail porte au plus 10 pièces.");
    const heavy = addPieces([f("a", 25 * mo), f("b", 25 * mo)], [f("c", 1)]);
    expect(heavy.pieces).toHaveLength(2);
    expect(heavy.problem).toBe("Ces pièces sont trop lourdes pour un seul mail : 50 Mo en tout.");
  });

  it("joindre à un transfert : ses pièces d'origine comptent dans les bornes (ADR 0214)", () => {
    const mo = 1024 * 1024;
    const f = (name: string, size: number) => ({ name, size });
    const nine = Array.from({ length: 9 }, (_, i) => f(`o${i}`, 1));
    expect(addPieces([], [f("a", 1)], nine).pieces).toHaveLength(1);
    expect(addPieces([f("a", 1)], [f("b", 1)], nine).problem).toBe("Un mail porte au plus 10 pièces, celles du mail d'origine comprises.");
    expect(addPieces([], [f("c", 11 * mo)], [f("o", 40 * mo)]).problem).toBe("Ces pièces sont trop lourdes pour un seul mail : 50 Mo en tout, celles du mail d'origine comprises.");
    expect(addPieces([], [f("c", 10 * mo)], [f("o", 40 * mo)]).problem).toBe("");
  });

  it("la Cci suit les mêmes bornes que les autres destinataires", () => {
    const ok = outgoingText({ to: team.slice(0, 1), cc: [], bcc: team.slice(1, 2), subject: "x", body: "y" });
    expect(ok.mail?.bcc).toBe(addressText(team[1]));
    expect(outgoingText({ to: team.slice(0, 1), cc: [], subject: "x", body: "y" }).mail?.bcc).toBe("");
    const crowd = Array.from({ length: 12 }, (_, i) => ({ name: "", address: `personne.tres.longue${i}@entreprise-exemple.test` }));
    expect(outgoingText({ to: team.slice(0, 1), cc: [], bcc: crowd, subject: "x", body: "y" }).problem).toContain("« Cci »");
  });

  it("dit pourquoi un mail ne part pas tel quel, sinon ce qui part", () => {
    const ok = outgoingText({ to: team.slice(0, 1), cc: team, subject: "Re: point", body: "Bonjour" });
    expect(ok.problem).toBe("");
    expect(ok.mail?.cc).toBe(team.map((p) => p.address).join(", "));
    const crowd = Array.from({ length: 12 }, (_, i) => ({ name: "", address: `personne.tres.longue${i}@entreprise-exemple.test` }));
    expect(outgoingText({ to: crowd, cc: [], subject: "x", body: "y" }).problem).toContain("« À »");
    expect(outgoingText({ to: team.slice(0, 1), cc: crowd, subject: "x", body: "y" }).problem).toContain("« Cc »");
    expect(outgoingText({ to: team.slice(0, 1), cc: [], subject: "o".repeat(201), body: "y" }).problem).toBe("L'objet est trop long : 200 caractères au plus (il en a 201).");
    const long = outgoingText({ to: team.slice(0, 1), cc: [], subject: "x", body: "m".repeat(20_001) });
    expect(long.mail).toBeNull();
    expect(long.problem).toBe("Le message est trop long : 20\u202f000 caractères au plus (il en a 20\u202f001).");
    // compté comme le serveur : un emoji est un caractère
    expect(outgoingText({ to: team.slice(0, 1), cc: [], subject: "x", body: "😀".repeat(20_000) }).problem).toBe("");
  });

  it("un objet qu'on n'a pas tapé tient dans sa borne", () => {
    expect(clip("Re: court", 200)).toBe("Re: court");
    const clipped = clip(`Re: ${"é".repeat(300)}`, 200);
    expect(chars(clipped)).toBe(200);
    expect(clipped.endsWith("…")).toBe(true);
    expect(chars(clip("😀".repeat(300), 200))).toBe(200);
  });
});

describe("ta réponse partie de son brouillon (R2-02)", () => {
  const d = (state: "attend" | "approuve" | "parti" | "refuse" | "echec", id = "d1") => ({ id, state });
  it("il attend : elle passe par lui", () => {
    expect(draftReply([d("attend")], "d1")).toEqual({ via: "draft", draft: d("attend") });
  });
  it("refusé ou plus là : une réponse ordinaire", () => {
    expect(draftReply([d("refuse")], "d1")).toEqual({ via: "reply" });
    expect(draftReply([d("attend", "d2")], "d1")).toEqual({ via: "reply" });
    expect(draftReply([], "d1")).toEqual({ via: "reply" });
  });
  it("parti, approuvé ou en échec : rien de plus ne part, et pourquoi", () => {
    // envoyé une première fois (la réponse du serveur perdue), puis retouché : la clé est neuve, le serveur ne dédoublonne pas
    expect(draftReply([d("parti")], "d1")).toEqual({ via: "stop", why: "Son brouillon est déjà parti." });
    expect(draftReply([d("approuve")], "d1")).toEqual({ via: "stop", why: "Son brouillon est déjà parti." });
    expect(draftReply([d("echec")], "d1")).toMatchObject({ via: "stop" });
  });
});

describe("la touche Suppr", () => {
  const row = { tag: "DIV", editable: false };
  const key = (target: { tag: string; type?: string; editable: boolean } = row, k = "Delete", ctrl = false) => ({ key: k, ctrl, target });
  it("met à la corbeille les mails cochés, sinon le mail ouvert qu'on peut ranger", () => {
    expect(deleteTargets(key(), ["a", "b"], { ref: "c", tidy: true })).toEqual(["a", "b"]);
    expect(deleteTargets(key({ tag: "INPUT", type: "checkbox", editable: false }), ["a"], null)).toEqual(["a"]); // la case qu'on vient de cocher
    expect(deleteTargets(key(), [], { ref: "c", tidy: true })).toEqual(["c"]);
    expect(deleteTargets(key(), [], { ref: "c", tidy: false })).toEqual([]); // une boîte qu'on ne fait que lire
    expect(deleteTargets(key(), [], null)).toEqual([]);
  });
  it("jamais dans un champ qu'on remplit, ni avec une autre touche", () => {
    expect(deleteTargets(key({ tag: "TEXTAREA", editable: false }), ["a"], null)).toEqual([]);
    expect(deleteTargets(key({ tag: "INPUT", type: "text", editable: false }), ["a"], null)).toEqual([]);
    expect(deleteTargets(key({ tag: "DIV", editable: true }), ["a"], null)).toEqual([]);
    expect(deleteTargets(key(row, "Backspace"), ["a"], null)).toEqual([]);
    expect(deleteTargets(key(row, "Delete", true), ["a"], null)).toEqual([]);
  });
});

describe("un rangement se voit aussitôt (le serveur range ensuite)", () => {
  const rows = [{ ref: "a" }, { ref: "b" }, { ref: "c" }];
  it("un mail en route ne revient avec aucune liste", () => {
    const leaving = new Map([["b", Infinity]]);
    expect(keptRows(rows, leaving, 7).map((r) => r.ref)).toEqual(["a", "c"]);
    expect(keptRows(rows, leaving, 1000).map((r) => r.ref)).toEqual(["a", "c"]);
    expect(leaving.has("b")).toBe(true);
  });
  it("une liste partie avant la réponse du serveur ne le remontre pas", () => {
    // la réponse est arrivée alors que la lecture n° 4 était la dernière partie
    const leaving = new Map([["b", 4]]);
    expect(keptRows(rows, leaving, 4).map((r) => r.ref)).toEqual(["a", "c"]);
    expect(leaving.has("b")).toBe(true);
  });
  it("une liste partie après dit vrai : un mail refusé en partie revient, et n'est plus écarté", () => {
    const leaving = new Map([["b", 4]]);
    expect(keptRows(rows, leaving, 5).map((r) => r.ref)).toEqual(["a", "b", "c"]);
    expect(leaving.size).toBe(0);
  });
});
