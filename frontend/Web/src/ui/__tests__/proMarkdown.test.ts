import { describe, expect, it } from "vitest";
import { escapeHtml, renderProMarkdown as md } from "../proMarkdown";

const LINK = (url: string, label = url) =>
  `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;

/** Les seules balises que la sortie peut porter, attributs compris. */
const ALLOWED_TAGS = [
  /^<\/?(p|br|strong|em|code|pre|ul|ol|li|hr)>$/,
  /^<p class="md-title">$/,
  /^<pre class="md-code">$/,
  /^<ol start="\d+">$/,
  /^<a href="https?:\/\/[^"<>\s]+" target="_blank" rel="noopener noreferrer">$/,
  /^<\/a>$/,
];

/** Toute balise de la sortie est de la liste blanche, et aucun `<` n'est hors d'une balise. */
function onlyAllowedTags(html: string): boolean {
  const tags = html.match(/<[^>]*>/g) ?? [];
  const lt = (html.match(/</g) ?? []).length;
  return lt === tags.length && tags.every((tag) => ALLOWED_TAGS.some((re) => re.test(tag)));
}

describe("renderProMarkdown — sûreté", () => {
  it("échappe tout le HTML d'abord : une balise du texte reste du texte", () => {
    expect(md('<script>alert(1)</script> <img src=x onerror="alert(1)">')).toBe(
      "<p>&lt;script&gt;alert(1)&lt;/script&gt; &lt;img src=x onerror=&quot;alert(1)&quot;&gt;</p>"
    );
  });

  it("escapeHtml couvre les cinq caractères", () => {
    expect(escapeHtml(`<a href="x" title='y'>&</a>`)).toBe(
      "&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;"
    );
  });

  it("un lien n'est cliquable qu'en http(s)", () => {
    expect(md("[clic](javascript:alert(1))")).toBe("<p>[clic](javascript:alert(1))</p>");
    expect(md("[clic](data:text/html,x)")).toBe("<p>[clic](data:text/html,x)</p>");
    expect(md("javascript:alert(1)")).toBe("<p>javascript:alert(1)</p>");
    expect(md("[ok](https://exemple.fr/devis)")).toBe(`<p>${LINK("https://exemple.fr/devis", "ok")}</p>`);
  });

  it("un guillemet ne peut pas fermer l'attribut d'un lien", () => {
    const html = md('[x](https://a.fr/"onmouseover="alert(1)) https://b.fr/"onclick=alert(1)');
    expect(html).not.toMatch(/"\s*on\w+=/);
    expect(onlyAllowedTags(html)).toBe(true);
  });

  it("le code (en bloc et en ligne) n'est jamais interprété", () => {
    expect(md("```html\n<b>**gras**</b>\n```")).toBe(
      '<pre class="md-code"><code>&lt;b&gt;**gras**&lt;/b&gt;</code></pre>'
    );
    expect(md("lance `<i>_x_</i>`")).toBe("<p>lance <code>&lt;i&gt;_x_&lt;/i&gt;</code></p>");
  });

  it("le séparateur interne retiré du texte ne peut pas forger un emplacement", () => {
    expect(md("\u00000\u0000 `a`")).toBe("<p>0 <code>a</code></p>");
  });

  it("sur des mélanges hostiles, la sortie ne porte que les balises permises", () => {
    const fragments = [
      "<script>", "</p>", "<img src=x onerror=alert(1)>", '"', "'", "&", "**", "*", "_", "__",
      "`", "```", "~~~", "[x](", "](", ")", "https://a.fr/", "http://b.fr/?q=1&r=2",
      "javascript:", "onerror=", "\n", "\n\n", "- ", "1. ", "# ", "  ", "mot", "é", "\t", "---",
    ];
    let seed = 42;
    const next = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    for (let n = 0; n < 400; n++) {
      let text = "";
      const len = 1 + Math.floor(next() * 24);
      for (let i = 0; i < len; i++) text += fragments[Math.floor(next() * fragments.length)];
      const html = md(text);
      if (!onlyAllowedTags(html)) throw new Error(`balise non permise pour ${JSON.stringify(text)} : ${html}`);
    }
  });
});

describe("renderProMarkdown — mise en forme", () => {
  it("gras, italique, code en ligne ; un snake_case reste tel quel", () => {
    expect(md("Salut **toi**, *elle* et _ici_ : `x_y` mais snake_case_name")).toBe(
      "<p>Salut <strong>toi</strong>, <em>elle</em> et <em>ici</em> : <code>x_y</code> mais snake_case_name</p>"
    );
  });

  it("gras-italique, gras souligné ; une multiplication n'est pas de l'italique", () => {
    expect(md("***fort*** et __gras__ et 2 * 3 * 4")).toBe(
      "<p><strong><em>fort</em></strong> et <strong>gras</strong> et 2 * 3 * 4</p>"
    );
  });

  it("un gras et un italique qui se chevauchent ne produisent pas de balises croisées", () => {
    expect(md("**a *b** c*")).toBe("<p><strong>a *b</strong> c*</p>");
  });

  it("une ligne simple est un saut de ligne, une ligne vide un paragraphe", () => {
    expect(md("un\ndeux\n\ntrois")).toBe("<p>un<br>deux</p><p>trois</p>");
  });

  it("une ligne vide ne coupe pas la réponse en bulles : tout reste dans la même sortie", () => {
    expect(md("a\n\n\n\nb")).toBe("<p>a</p><p>b</p>");
  });

  it("les titres sont en gras ; un # sans espace n'en est pas un", () => {
    expect(md("# Titre\n## Section ##\n#hashtag et C#")).toBe(
      '<p class="md-title"><strong>Titre</strong></p>' +
        '<p class="md-title"><strong>Section</strong></p>' +
        "<p>#hashtag et C#</p>"
    );
  });

  it("listes à puces, imbriquées par le retrait", () => {
    expect(md("- a\n- b\n  - b1\n  - b2\n- c")).toBe(
      "<ul><li>a</li><li>b<ul><li>b1</li><li>b2</li></ul></li><li>c</li></ul>"
    );
  });

  it("listes numérotées, avec leur premier numéro", () => {
    expect(md("1. un\n2. **deux**")).toBe("<ol><li>un</li><li><strong>deux</strong></li></ol>");
    expect(md("5. cinq\n6. six")).toBe('<ol start="5"><li>cinq</li><li>six</li></ol>');
  });

  it("une ligne en retrait prolonge l'élément ; une ligne sans retrait sort de la liste", () => {
    expect(md("- item\n  suite\nhors liste")).toBe("<ul><li>item<br>suite</li></ul><p>hors liste</p>");
  });

  it("deux sortes de listes à la suite font deux listes", () => {
    expect(md("- a\n1. b")).toBe("<ul><li>a</li></ul><ol><li>b</li></ol>");
  });

  it("un bloc de code garde sa mise en page et son retrait", () => {
    expect(md("Voilà :\n```ts\nconst a = 1;  // ok\n    retrait\n```\nfin")).toBe(
      '<p>Voilà :</p><pre class="md-code"><code>const a = 1;  // ok\n    retrait</code></pre><p>fin</p>'
    );
  });

  it("un bloc non fermé court jusqu'à la fin", () => {
    expect(md("```\nnon fermé\n**pas gras**")).toBe(
      '<pre class="md-code"><code>non fermé\n**pas gras**</code></pre>'
    );
  });

  it("un séparateur horizontal", () => {
    expect(md("a\n\n---\n\nb")).toBe("<p>a</p><hr><p>b</p>");
  });

  it("une adresse nue devient un lien, sans la ponctuation qui la suit", () => {
    expect(md("voir https://x.fr/a_b. et (https://y.fr/p)")).toBe(
      `<p>voir ${LINK("https://x.fr/a_b")}. et (${LINK("https://y.fr/p")})</p>`
    );
  });

  it("une adresse entre guillemets ou chevrons s'arrête avant eux", () => {
    expect(md('"https://x.com" <https://z.com>')).toBe(
      `<p>&quot;${LINK("https://x.com")}&quot; &lt;${LINK("https://z.com")}&gt;</p>`
    );
  });

  it("un _ ou un & dans une adresse ne devient pas une balise", () => {
    expect(md("[devis](https://a.fr/a_b_c?x=1&y=2)")).toBe(
      `<p>${LINK("https://a.fr/a_b_c?x=1&amp;y=2", "devis")}</p>`
    );
  });

  it("le libellé d'un lien garde sa mise en forme", () => {
    expect(md("[`code` **lien**](https://a.fr)")).toBe(
      `<p>${LINK("https://a.fr", "<code>code</code> <strong>lien</strong>")}</p>`
    );
  });

  it("les fins de ligne Windows sont des fins de ligne", () => {
    expect(md("a\r\nb")).toBe("<p>a<br>b</p>");
  });
});
