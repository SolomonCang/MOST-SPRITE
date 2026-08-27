import { useQuery } from "@tanstack/react-query";
import { Outlet } from "react-router-dom";
import { api } from "../lib/api";
import type { CurrentUser, InstrumentSnapshot } from "../lib/types";

export interface ShellOutletContext {
  user?: CurrentUser;
  instrument?: InstrumentSnapshot;
  serviceHealthy: boolean;
}

export function AppShell() {
  const user = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60_000 });
  const instrument = useQuery({ queryKey: ["instrument"], queryFn: api.instrument, refetchInterval: 1500 });

  return (
    <Outlet
      context={{
        user: user.data,
        instrument: instrument.data,
        serviceHealthy: Boolean(instrument.data?.fresh && !instrument.isError),
      } satisfies ShellOutletContext}
    />
  );
}
