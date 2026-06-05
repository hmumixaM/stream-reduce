/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MIRROR?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
