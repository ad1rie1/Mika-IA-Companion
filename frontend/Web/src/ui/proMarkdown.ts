/**
 * Le Markdown d'une réponse pro (ADR 0116), rendu sans risque.
 *
 * Une réponse de travail est longue et structurée : blocs de code, code en
 * ligne, gras, italique, listes, titres, liens. `inlineMarkup.ts` (les
 * réponses ordinaires) n'en sait que trois ; ici, le rendu complet de ce que
 * le modèle écrit d'ordinaire, et rien de plus (ni tableau, ni image, ni HTML).
 *
 * La règle de sûreté tient en une ligne : **tout le HTML est échappé d'abord**,
 * avant qu'aucune balise ne soit posée. Le texte ne peut donc plus rien
 * contenir qu'un navigateur lirait comme une balise ou un attribut ; les seules
 * balises de la sortie sont celles que ce module écrit (`p`, `br`, `strong`,
 * `em`, `code`, `pre`, `ul`, `ol`, `li`, `hr`, `a`), sans autre attribut qu'une
 * classe fixe, un `start` numérique, et le `href` d'un lien — seulement
 * `http(s)://`, déjà échappé (un `"` y est `&quot;` : il ne peut pas fermer
 * l'attribut). C'est ce qui permet à la bulle de poser la sortie en
 * `innerHTML`. Le code (en bloc ou en ligne) et les adresses sont mis de côté
 * avant le gras et l'italique : un `_` ou un `*` qu'ils contiennent ne devient
 * jamais une balise.
 */

/** Échappe tout ce qu'un navigateur pourrait lire comme du HTML. */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Le séparateur des morceaux mis de côté : un caractère retiré du texte en entrée. */
const MARK = "\u0000";
const SLOT = /\u0000(\d+)\u0000/g;

const FENCE_OPEN = /^(\s*)(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/;
const RULE = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/;
const BULLET = /^(\s*)[-*+]\s+(.*)$/;
const NUMBERED = /^(\s*)(\d{1,9})[.)]\s+(.*)$/;

/** Une adresse cliquable : `http://` ou `https://`, rien d'autre. */
const URL_HEAD = /^https?:\/\/[^\s/]/i;

/**
 * Le rendu HTML d'une réponse pro. Une ligne simple est un saut de ligne
 * (comme dans le chat), une ligne vide sépare deux paragraphes.
 */
export function renderProMarkdown(source: string): string {
  const lines = escapeHtml(source.replace(/\r\n?/g, "\n").split(MARK).join("")).split("\n");
  const out: string[] = [];
  let paragraph: string[] = [];
  let list: ListBuilder | null = null;

  const flushParagraph = () => {
    if (paragraph.length) out.push(`<p>${paragraph.map(inline).join("<br>")}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (list) out.push(list.close());
    list = null;
  };
  const flush = () => {
    flushParagraph();
    flushList();
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    const fence = FENCE_OPEN.exec(line);
    if (fence) {
      flush();
      const [, indent, marker] = fence;
      const body: string[] = [];
      // un bloc non fermé court jusqu'à la fin, comme en Markdown
      for (i += 1; i < lines.length; i++) {
        const closing = lines[i].trim();
        if (closing.startsWith(marker[0].repeat(marker.length)) && /^(`{3,}|~{3,})$/.test(closing)) break;
        body.push(dedent(lines[i], indent.length));
      }
      out.push(`<pre class="md-code"><code>${body.join("\n")}</code></pre>`);
      continue;
    }

    if (!line.trim()) {
      flush();
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      out.push(`<p class="md-title"><strong>${inline(heading[2])}</strong></p>`);
      continue;
    }

    if (RULE.test(line)) {
      flush();
      out.push("<hr>");
      continue;
    }

    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const indent = (bullet ?? numbered)![1].replace(/\t/g, "    ").length;
      const item = bullet
        ? { indent, ordered: false, start: 1, html: inline(bullet[2]) }
        : { indent, ordered: true, start: Number(numbered![2]), html: inline(numbered![3]) };
      if (!list) list = new ListBuilder();
      list.add(item);
      continue;
    }

    // une ligne en retrait juste sous un élément de liste le prolonge
    if (list && /^\s/.test(line) && !paragraph.length) {
      list.extend(inline(line.trim()));
      continue;
    }

    flushList();
    paragraph.push(line.trim());
  }
  flush();
  return out.join("");
}

/** Retire jusqu'à `n` espaces de tête (le retrait d'un bloc de code dans une liste). */
function dedent(line: string, n: number): string {
  let i = 0;
  while (i < n && i < line.length && line[i] === " ") i++;
  return line.slice(i);
}

interface ListItem {
  indent: number;
  ordered: boolean;
  start: number;
  html: string;
}

/** Des listes imbriquées par le retrait, ouvertes et fermées dans l'ordre. */
class ListBuilder {
  private html = "";
  private stack: Array<{ indent: number; ordered: boolean }> = [];

  add(item: ListItem): void {
    const top = this.stack[this.stack.length - 1];
    if (!top) {
      this.open(item);
      return;
    }
    if (item.indent >= top.indent + 2) {
      // une sous-liste, dans l'élément en cours
      this.open(item);
      return;
    }
    while (this.stack.length > 1 && item.indent < this.stack[this.stack.length - 1].indent) {
      this.closeTop();
    }
    const level = this.stack[this.stack.length - 1];
    if (level.ordered !== item.ordered) {
      // une liste d'une autre sorte au même niveau : on ferme, on rouvre
      this.closeTop();
      this.open({ ...item, indent: level.indent });
      return;
    }
    this.html += `</li><li>${item.html}`;
  }

  extend(html: string): void {
    this.html += `<br>${html}`;
  }

  close(): string {
    while (this.stack.length) this.closeTop();
    return this.html;
  }

  private open(item: ListItem): void {
    const tag = item.ordered ? "ol" : "ul";
    const start = item.ordered && item.start !== 1 ? ` start="${item.start}"` : "";
    this.html += `<${tag}${start}><li>${item.html}`;
    this.stack.push({ indent: item.indent, ordered: item.ordered });
  }

  private closeTop(): void {
    const level = this.stack.pop();
    if (level) this.html += `</li></${level.ordered ? "ol" : "ul"}>`;
  }
}

/**
 * La mise en forme d'une ligne déjà échappée. Le code en ligne, les liens et
 * les adresses sont mis de côté d'abord (un emplacement `\0n\0`), puis le gras
 * et l'italique, puis les emplacements sont rendus.
 */
function inline(escaped: string): string {
  const slots: string[] = [];
  const keep = (html: string) => {
    slots.push(html);
    return `${MARK}${slots.length - 1}${MARK}`;
  };

  let s = escaped.replace(/(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)/g, (_m, _ticks, code: string) =>
    keep(`<code>${code.trim() || code}</code>`)
  );
  // [libellé](https://…) — le libellé garde son gras et son italique
  s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)\u0000]+)\)/gi, (_m, label: string, url: string) =>
    keep(`<a href="${url}" target="_blank" rel="noopener noreferrer">${emphasis(label)}</a>`)
  );
  // une adresse nue
  s = s.replace(/https?:\/\/[^\s\u0000]+/gi, (raw: string) => {
    const { url, rest } = trimUrl(raw);
    if (!URL_HEAD.test(url)) return raw;
    return keep(`<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`) + rest;
  });
  s = emphasis(s);
  // les emplacements peuvent en contenir d'autres (du code dans un libellé)
  for (let pass = 0; pass < 3 && s.includes(MARK); pass++) {
    s = s.replace(SLOT, (_m, n: string) => slots[Number(n)] ?? "");
  }
  return s;
}

/** Gras et italique, sur un texte échappé dont le code et les liens sont mis de côté. */
function emphasis(s: string): string {
  return (
    s
      .replace(/\*\*\*(?=\S)([^*\n]*?\S)\*\*\*/g, "<strong><em>$1</em></strong>")
      .replace(/\*\*(?=\S)([^\n]*?\S)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^\p{L}\p{N}_])__(?=\S)([^\n]*?\S)__(?![\p{L}\p{N}_])/gu, "$1<strong>$2</strong>")
      // l'italique ne contient pas de balise : il ne peut pas chevaucher un gras
      .replace(/(^|[^*\\])\*(?=[^\s*])([^*<\n]*?[^\s*<\\])\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/(^|[^\p{L}\p{N}_])_(?=[^\s_])([^_<\n]*?[^\s_<])_(?![\p{L}\p{N}_])/gu, "$1<em>$2</em>")
  );
}

/**
 * Une adresse nue s'arrête avant la ponctuation qui la suit (« voir
 * https://x.fr. ») et avant un guillemet échappé ; une parenthèse fermante
 * n'en fait partie que si elle en ferme une.
 */
function trimUrl(raw: string): { url: string; rest: string } {
  let url = raw;
  let rest = "";
  for (;;) {
    const entity = /(&quot;|&#39;|&gt;|&lt;)$/.exec(url);
    if (entity) {
      rest = entity[1] + rest;
      url = url.slice(0, -entity[1].length);
      continue;
    }
    const last = url[url.length - 1];
    if (last && ".,;:!?*_".includes(last)) {
      rest = last + rest;
      url = url.slice(0, -1);
      continue;
    }
    if (last === ")" && (url.match(/\(/g)?.length ?? 0) < (url.match(/\)/g)?.length ?? 0)) {
      rest = last + rest;
      url = url.slice(0, -1);
      continue;
    }
    break;
  }
  // une entité coupée en deux au milieu de l'adresse (`&quot` sans `;`) ne passe pas
  const cut = url.search(/&(quot|#39|gt|lt);/);
  if (cut >= 0) {
    rest = url.slice(cut) + rest;
    url = url.slice(0, cut);
  }
  return { url, rest };
}
