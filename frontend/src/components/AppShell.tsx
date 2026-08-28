import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import type { AuthConfiguration, CurrentUser, InstrumentSnapshot } from "../lib/types";
import { LoginPage } from "./LoginPage";

const EXPLICIT_LOGOUT_KEY = "most-sprite.explicit-logout";
const AUTH_SYNC_KEY = "most-sprite.auth-sync";

export interface ShellOutletContext {
  user: CurrentUser;
  auth: AuthConfiguration;
  instrument?: InstrumentSnapshot;
  serviceHealthy: boolean;
  authBusy: boolean;
  login: (accountId: string) => Promise<void>;
  logout: () => Promise<void>;
}

function wasExplicitlyLoggedOut(): boolean {
  return window.localStorage.getItem(EXPLICIT_LOGOUT_KEY) === "true";
}

export function AppShell() {
  const queryClient = useQueryClient();
  const [explicitlyLoggedOut, setExplicitlyLoggedOut] = useState(wasExplicitlyLoggedOut);
  const auth = useQuery({
    queryKey: ["auth-configuration"],
    queryFn: api.authConfiguration,
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
  const user = useQuery<CurrentUser | null>({
    queryKey: ["me"],
    enabled: Boolean(auth.data) && !explicitlyLoggedOut,
    retry: false,
    refetchOnWindowFocus: true,
    queryFn: async () => {
      try {
        return await api.me();
      } catch (error) {
        if (
          error instanceof ApiError
          && error.status === 401
          && auth.data?.auth_mode === "dev"
          && auth.data.default_account_id
        ) {
          return api.login(auth.data.default_account_id);
        }
        throw error;
      }
    },
  });

  useEffect(() => {
    const synchronizeSession = (event: StorageEvent) => {
      if (event.key !== EXPLICIT_LOGOUT_KEY && event.key !== AUTH_SYNC_KEY) return;
      const signedOut = wasExplicitlyLoggedOut();
      setExplicitlyLoggedOut(signedOut);
      if (signedOut) {
        queryClient.setQueryData(["me"], null);
      } else {
        void queryClient.invalidateQueries({ queryKey: ["me"] });
      }
    };
    window.addEventListener("storage", synchronizeSession);
    return () => window.removeEventListener("storage", synchronizeSession);
  }, [queryClient]);

  const notifyOtherTabs = () => {
    window.localStorage.setItem(AUTH_SYNC_KEY, `${Date.now()}-${crypto.randomUUID()}`);
  };

  const instrument = useQuery({
    queryKey: ["instrument"],
    queryFn: api.instrument,
    enabled: Boolean(user.data),
    refetchInterval: 1500,
  });
  const login = useMutation({
    mutationFn: api.login,
    onSuccess: (identity) => {
      window.localStorage.removeItem(EXPLICIT_LOGOUT_KEY);
      queryClient.setQueryData(["me"], identity);
      setExplicitlyLoggedOut(false);
      notifyOtherTabs();
    },
  });
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      window.localStorage.setItem(EXPLICIT_LOGOUT_KEY, "true");
      queryClient.setQueryData(["me"], null);
      setExplicitlyLoggedOut(true);
      notifyOtherTabs();
    },
  });

  const authError = login.error instanceof Error
    ? login.error.message
    : auth.error instanceof Error || user.error instanceof Error
      ? "authentication unavailable"
      : undefined;

  if (!auth.data || !user.data) {
    return (
      <LoginPage
        configuration={auth.data}
        loading={auth.isPending || (!explicitlyLoggedOut && user.isPending)}
        busy={login.isPending}
        error={authError}
        onLogin={async (accountId) => { await login.mutateAsync(accountId); }}
      />
    );
  }

  const context: ShellOutletContext = {
    user: user.data,
    auth: auth.data,
    instrument: instrument.data,
    serviceHealthy: Boolean(instrument.data?.fresh && !instrument.isError),
    authBusy: login.isPending || logout.isPending,
    login: async (accountId) => { await login.mutateAsync(accountId); },
    logout: async () => { await logout.mutateAsync(); },
  };

  return <Outlet context={context} />;
}
