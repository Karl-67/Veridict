import { createContext, useContext, useState, useCallback, useEffect, useRef, ReactNode } from "react";
import type { AuthUser } from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";
const ACCESS_TOKEN_TTL_MS = 14 * 60 * 1000; // refresh 1 min before 15-min expiry

interface AuthContextValue {
  user: AuthUser | null;
  login: (user: AuthUser) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => {
    try {
      const raw = localStorage.getItem("veridict_user");
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const login = useCallback((u: AuthUser) => {
    localStorage.setItem("veridict_token", u.token);
    localStorage.setItem("veridict_user", JSON.stringify(u));
    setUser(u);
  }, []);

  const logout = useCallback(async () => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    try {
      await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" });
    } catch { /* ignore */ }
    localStorage.removeItem("veridict_token");
    localStorage.removeItem("veridict_user");
    setUser(null);
  }, []);

  const silentRefresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) { logout(); return; }
      const data = await res.json();
      const updated: AuthUser = {
        user_id: data.user_id,
        email: data.email,
        display_name: data.display_name,
        job_title: data.job_title,
        department: data.department,
        avatar_color: data.avatar_color,
        org_id: data.org_id,
        org_role: data.org_role,
        org_name: data.org_name,
        token: data.access_token,
      };
      login(updated);
    } catch {
      logout();
    }
  }, [login, logout]);

  // Schedule silent refresh whenever user token changes
  useEffect(() => {
    if (!user) return;
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(silentRefresh, ACCESS_TOKEN_TTL_MS);
    return () => { if (refreshTimer.current) clearTimeout(refreshTimer.current); };
  }, [user?.token, silentRefresh]);

  // On mount, if we have a stored user try to refresh immediately to validate session
  useEffect(() => {
    if (user) silentRefresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
