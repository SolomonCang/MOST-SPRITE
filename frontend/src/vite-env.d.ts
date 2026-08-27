/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_WS_URL?: string;
  readonly VITE_DEV_USER?: string;
  readonly VITE_DEV_ROLE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
