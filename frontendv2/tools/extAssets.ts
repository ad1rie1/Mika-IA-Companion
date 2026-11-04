/**
 * Les fichiers que le client lit là où ils sont, sans jamais les copier dans le dépôt (ADR 0187) :
 * la police Inter de la console, les portraits pré-rendus d'Android (et leur manifeste) et la VRM
 * du client web — ces deux derniers sous licence et non versionnés.
 *
 * Le serveur de développement (et `vite preview`) les sert sous des adresses stables :
 *
 *   /ext/fonts/<fichier>   backendv2/src/mika/inspector/static/fonts/
 *   /ext/avatar/<fichier>  frontend/Android/app/src/main/assets/avatar/
 *   /ext/models/<fichier>  frontend/Web/public/models/
 *
 * Un nom seulement, sans dossier, avec une extension attendue : rien d'autre du disque ne sort.
 * `vite build` ne les embarque pas (voir le README).
 */
import { createReadStream, statSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

export interface ExtRoot {
  /** Le début de l'adresse, avec ses deux barres : `/ext/fonts/`. */
  prefix: string;
  /** Le dossier servi, absolu. */
  dir: string;
  /** Les noms admis. */
  files: RegExp;
}

/** Les trois dossiers, depuis la racine du dépôt. */
export function extRoots(repo: string): ExtRoot[] {
  const at = (rel: string) => `${repo.replace(/\/+$/, "")}/${rel}`;
  return [
    { prefix: "/ext/fonts/", dir: at("backendv2/src/mika/inspector/static/fonts"), files: /^[\w.-]+\.(woff2|txt)$/ },
    { prefix: "/ext/avatar/", dir: at("frontend/Android/app/src/main/assets/avatar"), files: /^[\w.-]+\.(webp|json)$/ },
    { prefix: "/ext/models/", dir: at("frontend/Web/public/models"), files: /^[\w.-]+\.vrm$/ },
  ];
}

/**
 * Le fichier qu'une adresse désigne, ou `null` : pas sous un préfixe connu, plus d'un segment, un
 * nom hors de la liste admise, un `..`, un encodage illisible. La requête (`?v=…`) est ignorée.
 */
export function resolveExt(url: string | undefined, roots: readonly ExtRoot[]): string | null {
  if (!url) return null;
  const path = url.split(/[?#]/, 1)[0];
  for (const root of roots) {
    if (!path.startsWith(root.prefix)) continue;
    let name: string;
    try {
      name = decodeURIComponent(path.slice(root.prefix.length));
    } catch {
      return null;
    }
    if (!name || name.includes("/") || name.includes("\\") || name.includes("\0")) return null;
    if (name.startsWith(".")) return null;
    if (!root.files.test(name)) return null;
    return `${root.dir}/${name}`;
  }
  return null;
}

const TYPES: Record<string, string> = {
  woff2: "font/woff2",
  txt: "text/plain; charset=utf-8",
  webp: "image/webp",
  json: "application/json; charset=utf-8",
  vrm: "model/gltf-binary",
};

export function contentType(file: string): string {
  const ext = file.slice(file.lastIndexOf(".") + 1).toLowerCase();
  return TYPES[ext] ?? "application/octet-stream";
}

function serve(roots: readonly ExtRoot[]) {
  return (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const file = resolveExt(req.url, roots);
    if (!file) {
      next();
      return;
    }
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.statusCode = 405;
      res.end();
      return;
    }
    let size: number;
    let mtime: number;
    try {
      const st = statSync(file);
      if (!st.isFile()) throw new Error("pas un fichier");
      size = st.size;
      mtime = st.mtimeMs;
    } catch {
      res.statusCode = 404;
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      res.end("Introuvable sur cette machine.");
      return;
    }
    const etag = `"${size.toString(36)}-${Math.floor(mtime).toString(36)}"`;
    res.setHeader("ETag", etag);
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("X-Content-Type-Options", "nosniff");
    if (req.headers["if-none-match"] === etag) {
      res.statusCode = 304;
      res.end();
      return;
    }
    res.statusCode = 200;
    res.setHeader("Content-Type", contentType(file));
    res.setHeader("Content-Length", String(size));
    if (req.method === "HEAD") {
      res.end();
      return;
    }
    createReadStream(file)
      .on("error", () => res.destroy())
      .pipe(res);
  };
}

/** Le greffon : les mêmes adresses en développement et en aperçu. */
export function extAssets(repo: string): Plugin {
  const roots = extRoots(repo);
  return {
    name: "mika-ext-assets",
    configureServer(server) {
      server.middlewares.use(serve(roots));
    },
    configurePreviewServer(server) {
      server.middlewares.use(serve(roots));
    },
  };
}
