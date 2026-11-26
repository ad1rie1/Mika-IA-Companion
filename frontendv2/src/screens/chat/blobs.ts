/**
 * Les octets des fichiers du chat, lus une fois par session (ADR 0312). `GET /files/<id>` répond en pièce jointe, sans
 * cache (`no-store`) et à 60 téléchargements par minute : le fil, redessiné à chaque message, ne peut pas y pointer ses
 * vignettes. Ce cache les lit (`fetch`, avec la session), les garde en mémoire sous une adresse `blob:` de la page, et
 * les rend aux vignettes, à la visionneuse et à « Enregistrer ». Une pièce qu'on vient d'envoyer y est posée depuis le
 * navigateur (`putLocal`) : elle se revoit avant que le serveur ne l'ait gardée.
 *
 * Il est borné (`BUDGET_BYTES`) : au-delà, les plus anciennement vus partent (leur adresse est révoquée ; une vignette
 * déjà peinte le reste, la suivante relit le fichier). Un échec se retient aussi : un fichier introuvable ou retiré
 * ne se redemande plus de la session, un refus pour trop de téléchargements pas avant une minute, une panne du réseau
 * pas avant quelques secondes — le fil, redessiné à chaque message, ne relance pas sa lecture à chaque dessin.
 */
import { apiUrl } from "../../api/moi";

/** La mémoire que les fichiers lus peuvent occuper. */
export const BUDGET_BYTES = 96 * 1024 * 1024;
/** Combien de temps un échec se retient avant qu'on réessaie (ms) : trop de téléchargements, le réseau. */
const RETRY_AFTER_429_MS = 60_000;
const RETRY_AFTER_NETWORK_MS = 5_000;

/** Un fichier qui n'a pas pu être lu : son statut HTTP (0 : le réseau). */
export class FileLoadError extends Error {
  constructor(readonly status: number) {
    super(
      status === 410
        ? "Ce fichier a été retiré."
        : status === 404
          ? "Ce fichier est introuvable."
          : status === 429
            ? "Trop de téléchargements d'affilée : réessaie dans une minute."
            : status === 0
              ? "Le serveur est injoignable."
              : `Le fichier n'a pas pu être lu (HTTP ${status}).`,
    );
  }
}

interface Entry {
  blob: Blob;
  url: string;
}

export class FileBlobs {
  /** Dans l'ordre où ils ont été vus : le premier part le premier. */
  private readonly entries = new Map<string, Entry>();
  private readonly loading = new Map<string, Promise<Blob>>();
  private bytes = 0;
  private observer: IntersectionObserver | null = null;
  /** Les vignettes observées : celles qu'un redessin a détachées cessent de l'être (elles retiendraient leur fil). */
  private readonly watched = new Set<HTMLImageElement>();
  /** Les lectures en échec, et jusqu'à quand (ms ; `Infinity` : de toute la session). */
  private readonly failed = new Map<string, { error: FileLoadError; until: number }>();

  constructor(
    private readonly budget = BUDGET_BYTES,
    private readonly read: (url: string) => Promise<Blob> = fetchFile,
    private readonly now: () => number = () => Date.now(),
  ) {}

  /** L'échec retenu pour ce fichier, s'il vaut encore. */
  private failure(key: string): FileLoadError | undefined {
    const f = this.failed.get(key);
    if (!f) return undefined;
    if (f.until > this.now()) return f.error;
    this.failed.delete(key);
    return undefined;
  }

  /** L'adresse `blob:` d'un fichier déjà lu (et il redevient le plus récent), sinon rien. */
  cached(key: string): string | undefined {
    const got = this.entries.get(key);
    if (!got) return undefined;
    this.entries.delete(key);
    this.entries.set(key, got);
    return got.url;
  }

  /** Les octets d'un fichier déjà lu. */
  blob(key: string): Blob | undefined {
    return this.entries.get(key)?.blob;
  }

  has(key: string): boolean {
    return this.entries.has(key);
  }

  /** Lire un fichier du serveur (`/files/<id>`), une fois même demandé plusieurs fois à la fois. */
  load(key: string): Promise<Blob> {
    const known = this.entries.get(key);
    if (known) return Promise.resolve(known.blob);
    if (key.startsWith("local:")) return Promise.reject(new FileLoadError(404));
    const refused = this.failure(key);
    if (refused) return Promise.reject(refused);
    const pending = this.loading.get(key);
    if (pending) return pending;
    const started = this.read(key)
      .then((blob) => {
        this.failed.delete(key);
        this.keep(key, blob);
        return blob;
      })
      .catch((err: unknown) => {
        const error = err instanceof FileLoadError ? err : new FileLoadError(0);
        const wait = error.status === 429 ? RETRY_AFTER_429_MS : error.status === 0 || error.status >= 500 ? RETRY_AFTER_NETWORK_MS : Infinity;
        this.failed.set(key, { error, until: this.now() + wait });
        throw error;
      })
      .finally(() => this.loading.delete(key));
    this.loading.set(key, started);
    return started;
  }

  /** La copie d'une pièce qu'on vient d'envoyer, tant que la page vit. */
  putLocal(key: string, blob: Blob): void {
    this.keep(key, blob);
  }

  private keep(key: string, blob: Blob): void {
    const old = this.entries.get(key);
    if (old) {
      URL.revokeObjectURL(old.url);
      this.bytes -= old.blob.size;
      this.entries.delete(key);
    }
    this.entries.set(key, { blob, url: URL.createObjectURL(blob) });
    this.bytes += blob.size;
    for (const [k, e] of this.entries) {
      if (this.bytes <= this.budget || k === key) break;
      URL.revokeObjectURL(e.url);
      this.bytes -= e.blob.size;
      this.entries.delete(k);
    }
  }

  /**
   * Peindre les vignettes d'un morceau de page (`img[data-file]`) : un fichier déjà lu tout de suite, les autres quand
   * ils paraissent à l'écran. Un fichier illisible marque sa vignette (`.broken`), qui garde son nom.
   */
  fill(root: ParentNode): void {
    for (const img of this.watched) {
      if (img.isConnected) continue;
      this.observer?.unobserve(img);
      this.watched.delete(img);
    }
    for (const img of Array.from(root.querySelectorAll<HTMLImageElement>("img[data-file]"))) {
      if (img.getAttribute("src")) continue;
      const key = img.dataset.file ?? "";
      const url = this.cached(key);
      const failed = url ? undefined : this.failure(key);
      if (url) img.src = url;
      else if (failed) broken(img, failed);
      else if (typeof IntersectionObserver === "undefined") void this.paint(img);
      else {
        this.watched.add(img);
        this.watch().observe(img);
      }
    }
  }

  private watch(): IntersectionObserver {
    this.observer ??= new IntersectionObserver(
      (seen) => {
        for (const e of seen) {
          if (!e.isIntersecting) continue;
          this.observer?.unobserve(e.target);
          this.watched.delete(e.target as HTMLImageElement);
          void this.paint(e.target as HTMLImageElement);
        }
      },
      { rootMargin: "200px" },
    );
    return this.observer;
  }

  private async paint(img: HTMLImageElement): Promise<void> {
    const key = img.dataset.file ?? "";
    try {
      await this.load(key);
      const url = this.cached(key);
      if (url && img.isConnected) img.src = url;
    } catch (err) {
      broken(img, err instanceof FileLoadError ? err : undefined);
    }
  }
}

/** Une vignette illisible : marquée, avec la raison au survol ; elle garde son nom. */
function broken(img: HTMLImageElement, err: FileLoadError | undefined): void {
  const box = img.closest<HTMLElement>("[data-thumb]");
  if (!box) return;
  box.classList.add("broken");
  if (err) box.title = err.message;
}

/** Lire un fichier du serveur avec la session ; un refus devient une `FileLoadError`. */
async function fetchFile(path: string): Promise<Blob> {
  let resp: Response;
  try {
    resp = await fetch(apiUrl(path), { credentials: "include", cache: "no-store" });
  } catch {
    throw new FileLoadError(0);
  }
  if (!resp.ok) throw new FileLoadError(resp.status);
  return resp.blob();
}

/** Enregistrer des octets sous un nom, par un lien de téléchargement (jamais en ouvrant le fichier dans la page). */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name || "fichier";
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
