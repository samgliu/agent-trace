import { useCallback, useEffect, useState } from "react";
import { getAuthStatus, loginWithToken, logout, type AuthStatus } from "../utils/apiClient";
import type { AuthRole } from "../utils/authz";

export type AuthState =
  | { status: "checking" }
  | { status: "ready"; enabled: boolean; authenticated: boolean; role: AuthRole | null }
  | { status: "error"; message: string };

export function useAuth() {
  const [state, setState] = useState<AuthState>({ status: "checking" });

  const refresh = useCallback(async () => {
    try {
      const status: AuthStatus = await getAuthStatus();
      setState({ status: "ready", enabled: status.enabled, authenticated: status.authenticated, role: status.role ?? null });
    } catch (error) {
      setState({ status: "error", message: error instanceof Error ? error.message : "Could not check authentication." });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (token: string) => {
    await loginWithToken(token);
    await refresh();
  }, [refresh]);

  const logoutAndRefresh = useCallback(async () => {
    await logout();
    await refresh();
  }, [refresh]);

  return { state, login, logout: logoutAndRefresh };
}
