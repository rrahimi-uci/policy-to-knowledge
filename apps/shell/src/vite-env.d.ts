/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_KG_FRONTEND_URL?: string;
  readonly VITE_CA_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
