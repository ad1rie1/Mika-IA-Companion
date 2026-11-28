import { describe, expect, it } from "vitest";
import { nameTitleButtons } from "./shell";

/** Un bouton de la barre de titre, réduit à ce que `nameTitleButtons` en lit et en écrit. */
function button(label: string | null, attrs: Record<string, string> = {}) {
  const set = new Map(Object.entries(attrs));
  return {
    attrs: set,
    querySelector: (sel: string) => (sel === ".lbl" && label !== null ? { textContent: label } : null),
    hasAttribute: (name: string) => set.has(name),
    setAttribute: (name: string, value: string) => void set.set(name, value),
  };
}

function head(buttons: ReturnType<typeof button>[]): ParentNode {
  return { querySelectorAll: (sel: string) => (sel === ".ph-actions .btn" ? buttons : []) } as unknown as ParentNode;
}

describe("la barre de titre sur un téléphone, où les libellés se cachent", () => {
  it("chaque bouton à libellé reçoit son nom : infobulle et nom pour un lecteur d'écran", () => {
    const test = button(" Tester la\n connexion ");
    nameTitleButtons(head([test]));
    expect(test.attrs.get("title")).toBe("Tester la connexion");
    expect(test.attrs.get("aria-label")).toBe("Tester la connexion");
  });

  it("ce que l'écran a posé reste ; un bouton sans libellé (une icône à infobulle) ne change pas", () => {
    const apk = button("Télécharger l'APK", { title: "L'application n'est pas encore déposée sur le serveur" });
    const icon = button(null, { title: "Chercher dans la conversation" });
    nameTitleButtons(head([apk, icon]));
    expect(apk.attrs.get("title")).toBe("L'application n'est pas encore déposée sur le serveur");
    expect(apk.attrs.get("aria-label")).toBe("Télécharger l'APK");
    expect([...icon.attrs.keys()]).toEqual(["title"]);
  });
});
