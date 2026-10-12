import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { ControlApi } from "./client";
import type { PortalConfig } from "./config";
import type { KeyName, Me } from "./types";

export type RevealedKeys = Record<string, Partial<Record<KeyName, string>>>;

export interface Session {
  me: Me;
  api: ControlApi;
  config: PortalConfig;
  /** Subscription keys explicitly revealed by the user. Memory only; cleared on sign-out. */
  keys: RevealedKeys;
  setKey: (subscriptionId: string, name: KeyName, value: string) => void;
  clearKeys: (subscriptionId?: string) => void;
  signOut: () => void;
}

const Ctx = createContext<Session | null>(null);

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession must be used inside an authenticated session.");
  return s;
}

interface Props {
  me: Me;
  api: ControlApi;
  config: PortalConfig;
  onSignOut: () => void;
  children: ReactNode;
}

export function SessionProvider({ me, api, config, onSignOut, children }: Props) {
  const [keys, setKeys] = useState<RevealedKeys>({});
  const setKey = useCallback((id: string, name: KeyName, value: string) => setKeys((k) => ({ ...k, [id]: { ...k[id], [name]: value } })), []);
  const clearKeys = useCallback((id?: string) => {
    setKeys((k) => {
      if (!id) return {};
      const { [id]: _drop, ...rest } = k;
      return rest;
    });
  }, []);
  const signOut = useCallback(() => {
    setKeys({});
    onSignOut();
  }, [onSignOut]);
  const value = useMemo(() => ({ me, api, config, keys, setKey, clearKeys, signOut }), [me, api, config, keys, setKey, clearKeys, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}