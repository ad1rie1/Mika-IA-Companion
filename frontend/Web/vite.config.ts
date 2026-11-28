import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import { extAssets } from "./tools/extAssets";

const here = fileURLToPath(new URL(".", import.meta.url));
const repo = fileURLToPath(new URL("../..", import.meta.url));

export default defineConfig({
  plugins: [extAssets(repo)],
  // L'éditeur des pages de documentation (Milkdown Crepe, chargé à la demande) dessine ses menus avec Vue : ses
  // drapeaux de construction sont dits, pour qu'il n'embarque ni ses outils de développement ni ses diagnostics.
  define: { __VUE_OPTIONS_API__: "true", __VUE_PROD_DEVTOOLS__: "false", __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false" },
  server: {
    // Le port admis d'office par le moteur (DEV_ORIGINS, adapters/web/app.py) : échouer plutôt que glisser
    // sur un autre, dont chaque appel authentifié serait refusé.
    port: 4173,
    strictPort: true,
    fs: {
      // ce projet, rien d'autre du dépôt
      allow: [here],
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
