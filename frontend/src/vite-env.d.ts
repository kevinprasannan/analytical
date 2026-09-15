/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_LOCAL_API_TOKEN?: string;
  readonly VITE_API_TARGET?: string;
  readonly VITE_SHARE_MODE?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
