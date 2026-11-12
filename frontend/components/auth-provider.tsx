"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { apiClient, ApiError } from "@/lib/api";
import { AuthApi, type CodePurpose } from "@/lib/auth-api";
import { AuthRules } from "@/lib/auth-form";
import { BrowserTimezone } from "@/lib/browser-timezone";
import { SessionProbe } from "@/lib/session-probe";
import type { User } from "@/lib/types";

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  /** Starts a sign-up: a code is emailed and nothing exists yet, so there is no user until `verify`. */
  register: (name: string, email: string, password: string, acceptTerms: boolean) => Promise<void>;
  /** Chooses a new password with the emailed code, which also signs the person in. */
  reset: (email: string, code: string, newPassword: string) => Promise<User>;
  /** Enters the emailed code: the account is made (a sign-up) or verified (a sign-in) and the person is signed in. */
  verify: (email: string, code: string, purpose: CodePurpose) => Promise<User>;
  logout: () => Promise<void>;
  setUser: (user: User) => void;
};

const AuthContext = createContext<AuthState | null>(null);

async function fetchMe(): Promise<User | null> {
  if (!(await SessionProbe.ask())) return null; // no session: asking would only print a 401 (and a failed refresh)
  try {
    return await apiClient.request<User>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetchMe()
      .catch(() => null)
      .then((me) => {
        if (!active) return;
        setUser(me);
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const api = useMemo(() => new AuthApi(apiClient), []);

  const login = useCallback(
    async (email: string, password: string) => {
      const user = await api.login(email, password);
      setUser(user);
      return user;
    },
    [api],
  );

  const register = useCallback(
    (name: string, email: string, password: string, acceptTerms: boolean) =>
      api.register(AuthRules.registerBody({ name, email, password }, acceptTerms, BrowserTimezone.detect())),
    [api],
  );

  const verify = useCallback(
    async (email: string, code: string, purpose: CodePurpose) => {
      const user = await api.verify(email, code, purpose);
      setUser(user);
      return user;
    },
    [api],
  );

  const reset = useCallback(
    async (email: string, code: string, newPassword: string) => {
      const user = await api.reset(email, code, newPassword);
      setUser(user);
      return user;
    },
    [api],
  );

  const logout = useCallback(async () => {
    await apiClient.request("/auth/logout", { method: "POST" });
    setUser(null);
    router.push("/");
    router.refresh();
  }, [router]);

  const value = useMemo(
    () => ({ user, loading, login, register, verify, reset, logout, setUser }),
    [user, loading, login, register, verify, reset, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
