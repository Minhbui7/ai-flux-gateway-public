import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { InteractionRequiredAuthError, PublicClientApplication, type AccountInfo } from "@azure/msal-browser";
import { ApiError, ControlApi } from "./client";
import { loadConfig, type PortalConfig } from "./config";
import { SessionProvider } from "./session";
import type { Me, Role } from "./types";
import { BrandMark } from "./components/ui";

interface Props {
  portalName: string;
  allowedRoles: Role[];
  env: Record<string, string | boolean | undefined>;
  children: ReactNode;
}

type Phase =
  | { kind: "init" }
  | { kind: "signed-out"; notice?: string }
  | { kind: "busy"; label: string }
  | { kind: "denied"; title: string; detail: string }
  | { kind: "ready"; me: Me };

function Screen({ portalName, children }: { portalName: string; children: ReactNode }) {
  return (
    <main className="gate" id="main">
      <div className="gate-card">
        <BrandMark />
        <p className="eyebrow">{portalName}</p>
        {children}
      </div>
    </main>
  );
}

/** Deny-by-default gate: nothing renders until config is valid, the user signs in and the backend authorizes them. */
export function AuthGate({ portalName, allowedRoles, env, children }: Props) {
  const cfg = useMemo(() => loadConfig(env), [env]);
  if (!cfg.ok) {
    return (
      <Screen portalName={portalName}>
        <h1>Portal not configured</h1>
        <p>Access is denied because required public configuration is missing or invalid. Rebuild the portal with these values corrected:</p>
        <ul className="problems">{cfg.problems.map((p) => <li key={p}>{p}</li>)}</ul>
      </Screen>
    );
  }
  return <ConfiguredGate config={cfg.config} portalName={portalName} allowedRoles={allowedRoles}>{children}</ConfiguredGate>;
}

function ConfiguredGate({ config, portalName, allowedRoles, children }: { config: PortalConfig; portalName: string; allowedRoles: Role[]; children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>({ kind: "init" });
  const msal = useRef<PublicClientApplication | null>(null);
  const account = useRef<AccountInfo | null>(null);
  const scopes = useMemo(() => [config.apiScope], [config.apiScope]);

  useEffect(() => {
    let live = true;
    const app = new PublicClientApplication({
      auth: {
        clientId: config.clientId,
        authority: config.authority,
        redirectUri: `${window.location.origin}${import.meta.env.BASE_URL}redirect.html`,
        postLogoutRedirectUri: `${window.location.origin}${import.meta.env.BASE_URL}`,
        navigateToLoginRequestUrl: false,
      },
      cache: { cacheLocation: "memoryStorage" },
      system: { loggerOptions: { loggerCallback: () => undefined, piiLoggingEnabled: false } },
    });
    app
      .initialize()
      .then(() => {
        if (!live) return;
        msal.current = app;
        setPhase({ kind: "signed-out" });
      })
      .catch(() => live && setPhase({ kind: "denied", title: "Sign-in unavailable", detail: "The sign-in library could not start in this browser." }));
    return () => {
      live = false;
    };
  }, [config]);

  const getToken = useCallback(async (): Promise<string> => {
    const app = msal.current;
    const acct = account.current;
    if (!app || !acct) throw new ApiError(401, "You are not signed in.");
    try {
      return (await app.acquireTokenSilent({ scopes, account: acct })).accessToken;
    } catch (e) {
      if (e instanceof InteractionRequiredAuthError) return (await app.acquireTokenPopup({ scopes, account: acct })).accessToken;
      throw new ApiError(401, "Your session expired. Sign in again.");
    }
  }, [scopes]);

  const api = useMemo(() => new ControlApi(config.controlApiUrl, getToken), [config.controlApiUrl, getToken]);

  const signIn = useCallback(async () => {
    const app = msal.current;
    if (!app) return;
    setPhase({ kind: "busy", label: "Signing in…" });
    try {
      const res = await app.loginPopup({ scopes, prompt: "select_account" });
      account.current = res.account;
      setPhase({ kind: "busy", label: "Checking organization membership…" });
      const me = await api.me();
      if (!allowedRoles.includes(me.role)) {
        setPhase({ kind: "denied", title: "Not authorized for this portal", detail: "Your account is approved but does not have the role required for this portal." });
        return;
      }
      if (res.account.tenantId && me.tenant_id.toLowerCase() !== res.account.tenantId.toLowerCase()) {
        setPhase({ kind: "denied", title: "Identity mismatch", detail: "The signed-in tenant does not match your approved organization." });
        return;
      }
      setPhase({ kind: "ready", me });
    } catch (e) {
      account.current = null;
      if (e instanceof ApiError && (e.status === 401 || e.status === 403 || e.status === 404)) {
        setPhase({ kind: "denied", title: "Access denied", detail: e.detail || "Your organization or account has not been approved for AIFLUX." });
      } else if (e instanceof ApiError) {
        setPhase({ kind: "denied", title: "Control plane unavailable", detail: e.detail });
      } else {
        setPhase({ kind: "signed-out", notice: "Sign-in was cancelled or failed. Try again." });
      }
    }
  }, [api, scopes, allowedRoles]);

  const signOut = useCallback(() => {
    const app = msal.current;
    const acct = account.current;
    account.current = null;
    setPhase({ kind: "signed-out", notice: "You have been signed out. Revealed keys were cleared from memory." });
    if (app && acct) void app.logoutPopup({ account: acct, mainWindowRedirectUri: `${window.location.origin}${import.meta.env.BASE_URL}` }).catch(() => undefined);
  }, []);

  if (phase.kind === "ready") {
    return <SessionProvider me={phase.me} api={api} config={config} onSignOut={signOut}>{children}</SessionProvider>;
  }
  return (
    <Screen portalName={portalName}>
      {phase.kind === "init" && <p role="status">Starting…</p>}
      {phase.kind === "busy" && <p role="status">{phase.label}</p>}
      {phase.kind === "signed-out" && (
        <>
          <h1>Access AI, intelligently routed</h1>
          <p>Sign in with your organizational Microsoft Entra account. Access requires an approved tenant and an approved user.</p>
          {phase.notice && <p role="status" className="notice">{phase.notice}</p>}
          <button className="btn primary" onClick={() => void signIn()}>Sign in with Microsoft</button>
        </>
      )}
      {phase.kind === "denied" && (
        <>
          <h1>{phase.title}</h1>
          <p role="alert">{phase.detail}</p>
          <button className="btn" onClick={() => setPhase({ kind: "signed-out" })}>Back to sign in</button>
        </>
      )}
    </Screen>
  );
}