export interface PortalConfig {
  clientId: string;
  authority: string;
  apiScope: string;
  controlApiUrl: string;
  gatewayUrl: string;
}

export type ConfigResult =
  | { ok: true; config: PortalConfig }
  | { ok: false; problems: string[] };

type Env = Record<string, string | boolean | undefined>;

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function str(v: unknown): string {
  return typeof v === "string" ? v.trim() : "";
}

function isSecureOrLocal(url: URL): boolean {
  return url.protocol === "https:" || (url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname));
}

/** Validates compile-time public configuration. Anything missing or invalid denies access. */
export function loadConfig(env: Env): ConfigResult {
  const problems: string[] = [];
  const clientId = str(env.VITE_ENTRA_CLIENT_ID);
  const authority = str(env.VITE_ENTRA_AUTHORITY) || "https://login.microsoftonline.com/organizations";
  const apiScope = str(env.VITE_API_SCOPE);
  const controlApiUrl = str(env.VITE_CONTROL_API_URL) || "/api";
  const gatewayUrl = str(env.VITE_GATEWAY_URL);

  if (!GUID.test(clientId)) problems.push("VITE_ENTRA_CLIENT_ID must be an application (client) ID GUID.");
  let authorityUrl: URL | undefined;
  try {
    authorityUrl = new URL(authority);
  } catch {
    problems.push("VITE_ENTRA_AUTHORITY must use organizations or a tenant GUID on login.microsoftonline.com.");
  }
  if (
    authorityUrl &&
    (authorityUrl.origin !== "https://login.microsoftonline.com" ||
      authorityUrl.username ||
      authorityUrl.password ||
      !/^\/(?:organizations|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/?$/i.test(authorityUrl.pathname) ||
      authorityUrl.search ||
      authorityUrl.hash)
  ) {
    problems.push("VITE_ENTRA_AUTHORITY must use organizations or a tenant GUID on login.microsoftonline.com.");
  }
  if (!apiScope || /\s/.test(apiScope)) problems.push("VITE_API_SCOPE must be a single API scope, for example api://<app-id>/access_as_user.");

  if (controlApiUrl !== "/api" && !controlApiUrl.startsWith("/")) {
    try {
      if (!isSecureOrLocal(new URL(controlApiUrl))) problems.push("VITE_CONTROL_API_URL must be https (or localhost for development).");
    } catch {
      problems.push("VITE_CONTROL_API_URL must be a path such as /api or an absolute URL.");
    }
  }

  try {
    const u = new URL(gatewayUrl);
    if (!isSecureOrLocal(u)) problems.push("VITE_GATEWAY_URL must be https (or localhost for development).");
    if (u.username || u.password || u.search || u.hash) problems.push("VITE_GATEWAY_URL must not contain credentials, query or fragment.");
  } catch {
    problems.push("VITE_GATEWAY_URL must be the public Front Door base URL ending in /v1.");
  }

  if (problems.length) return { ok: false, problems };
  return {
    ok: true,
    config: {
      clientId,
      authority: authority.replace(/\/+$/, ""),
      apiScope,
      controlApiUrl: controlApiUrl.replace(/\/+$/, ""),
      gatewayUrl: gatewayUrl.replace(/\/+$/, ""),
    },
  };
}