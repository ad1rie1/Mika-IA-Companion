import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import { extAssets } from "./tools/extAssets";

const here = fileURLToPath(new URL(".", import.meta.url));
const repo = fileURLToPath(new URL("..", import.meta.url));
/** Les modules purs du client web, réutilisés sans copie (ADR 0187). */
const webSrc = fileURLToPath(new URL("../frontend/Web/src", import.meta.url));

export default defineConfig({
  resolve: {
    alias: { "@web": webSrc },
    // Un module du client web qui importerait three le trouverait sinon dans frontend/Web/node_modules :
    // deux three dans la même page.
    dedupe: ["three", "@pixiv/three-vrm"],
  },
  plugins: [extAssets(repo)],
  server: {
    // Le port admis d'office par le moteur (DEV_ORIGINS, adapters/web/app.py) : échouer plutôt que glisser
    // sur un autre, dont chaque appel authentifié serait refusé.
    port: 4173,
    strictPort: true,
    fs: {
      // ce projet et les modules du client web, rien d'autre du dépôt
      allow: [here, webSrc],
    },
  },
  preview: {
    port: 4173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    // la VRM et ses dépendances forment leur propre morceau, chargé après l'écran
    chunkSizeWarningLimit: 1200,
  },
  test: {
    include: ["src/**/*.test.ts", "tools/**/*.test.ts"],
    environment: "node",
  },
});
