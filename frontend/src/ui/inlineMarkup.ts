/**
 * Mise en forme légère d'une réponse : blocs de code (```), code en ligne
 * (`x`) et gras (`**texte**`).
 *
 * Les modèles écrivent du Markdown que la bulle affichait tel quel, astérisques
 * et backticks compris. Le rendu ne passe jamais par `innerHTML` : le découpage
 * produit des segments typés, et la bulle les pose en nœuds texte / `<strong>` /
 * `<code>` / `<pre>`. Une balise sans partenaire reste du texte.
 */

export type BlockSegment =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string; lang: string };

export type InlineSegment =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "code"; text: string };

const FENCE = /```([\w+-]*)[ \t]*\n?([\s\S]*?)\n?```/g;
const INLINE = /`([^`\n]+)`|\*\*(?=\S)([\s\S]*?\S)\*\*/g;

export function parseBlocks(text: string): BlockSegment[] {
  const out: BlockSegment[] = [];
  let last = 0;
  for (const m of text.matchAll(FENCE)) {
    const start = m.index ?? 0;
    if (start > last) out.push({ kind: "text", text: text.slice(last, start) });
    out.push({ kind: "code", lang: m[1], text: m[2] });
    last = start + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

export function parseInline(text: string): InlineSegment[] {
  const out: InlineSegment[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    const start = m.index ?? 0;
    if (start > last) out.push({ kind: "text", text: text.slice(last, start) });
    if (m[1] !== undefined) out.push({ kind: "code", text: m[1] });
    else out.push({ kind: "bold", text: m[2] });
    last = start + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

/** Remplit `el` avec le rendu de `text`, sans jamais interpréter de HTML. */
export function renderInline(el: HTMLElement, text: string): void {
  el.textContent = "";
  for (const block of parseBlocks(text)) {
    if (block.kind === "code") {
      const pre = document.createElement("pre");
      pre.className = "chat-code";
      const code = document.createElement("code");
      code.textContent = block.text;
      pre.appendChild(code);
      el.appendChild(pre);
      continue;
    }
    // Les sauts de ligne qui entourent un bloc de code sont portés par le
    // bloc lui-même : les garder doublerait l'espace autour du <pre>.
    const body = block.text.replace(/^\n+/, "").replace(/\n+$/, "");
    for (const seg of parseInline(body)) {
      if (seg.kind === "text") {
        el.appendChild(document.createTextNode(seg.text));
        continue;
      }
      const node = document.createElement(seg.kind === "bold" ? "strong" : "code");
      node.textContent = seg.text;
      el.appendChild(node);
    }
  }
}
