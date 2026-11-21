/**
 * Un petit rendu Markdown (pur) pour un texte de la personne ou de Mika — la description d'un ticket, un plan, un
 * compte rendu : des titres (#), des listes (-, 1.), du `code`, des blocs de code, du **gras**. Tout est échappé avant
 * d'être mis en forme : aucune balise du texte ne passe, aucun lien n'est fabriqué. Un texte venu d'ailleurs
 * (`outside`) ne passe jamais par ici : il est cité tel quel (`parts.ts::outside`).
 */
import { h } from "../../shell/dom";

/** Le code entre accents graves, et le gras : sur un texte déjà échappé. */
export function inline(text: string): string {
  return h(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
}

export function markdown(source: string): string {
  const out: string[] = [];
  let list: "ul" | "ol" | "" = "";
  let para: string[] = [];
  let fence: string[] | null = null;
  const flush = (): void => {
    if (para.length) out.push(`<p>${para.map(inline).join("<br>")}</p>`);
    para = [];
    if (list) out.push(`</${list}>`);
    list = "";
  };
  for (const line of String(source ?? "").replace(/\r\n?/g, "\n").split("\n")) {
    if (fence) {
      if (/^```/.test(line)) {
        out.push(`<pre><code>${h(fence.join("\n"))}</code></pre>`);
        fence = null;
      } else fence.push(line);
      continue;
    }
    if (/^```/.test(line)) {
      flush();
      fence = [];
      continue;
    }
    const title = /^(#{1,4})\s+(.*)$/.exec(line);
    const item = /^\s*(?:[-*]|(\d+)[.)])\s+(.*)$/.exec(line);
    if (title) {
      flush();
      const level = Math.min(4, title[1].length + 1);
      out.push(`<h${level}>${inline(title[2])}</h${level}>`);
    } else if (item) {
      const kind = item[1] ? "ol" : "ul";
      if (para.length || (list && list !== kind)) flush();
      if (!list) {
        list = kind;
        out.push(`<${kind}>`);
      }
      out.push(`<li>${inline(item[2])}</li>`);
    } else if (!line.trim()) {
      flush();
    } else {
      if (list) flush();
      para.push(line);
    }
  }
  if (fence) out.push(`<pre><code>${h(fence.join("\n"))}</code></pre>`);
  flush();
  return out.join("");
}
