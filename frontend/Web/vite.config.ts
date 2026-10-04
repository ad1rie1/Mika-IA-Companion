import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 3000,
    // Échouer bruyamment plutôt que glisser sur 3001 : seul le port déclaré
    // est dans CORS_ALLOWED_ORIGINS / CSRF_TRUSTED_ORIGINS côté backend, donc
    // un repli silencieux donne une app qui s'affiche mais dont chaque appel
    // authentifié est jeté par le navigateur.
    strictPort: true,
    open: true,
  },
  build: {
    outDir: "dist",
  },
});
