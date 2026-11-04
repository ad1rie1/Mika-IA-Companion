/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Le moteur visé (défaut : http://localhost:8001), lu par `@web/network/api.ts`. */
  readonly VITE_BACKEND_ORIGIN?: string;
  /** La VRM de Mika (défaut : /ext/models/default.vrm). */
  readonly VITE_MIKA_VRM_URL?: string;
  /** Le dossier de ses portraits et de leur manifeste (défaut : /ext/avatar/). */
  readonly VITE_MIKA_AVATAR_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
