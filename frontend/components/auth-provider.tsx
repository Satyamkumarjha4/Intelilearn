"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { apiClient, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (name: string, email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  setUser: (user: User) => void;
};

const AuthContext = createContext<AuthState | null>(null);

async function fetchMe(): Promise<User | null> {
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

  const login = useCallback(async (email: string, password: string) => {
    const { user } = await apiClient.request<{ user: User }>("/auth/login", {
      method: "POST",
      body: { email, password },
    });
    setUser(user);
    return user;
  }, []);

  const register = useCallback(async (name: string, email: string, password: string) => {
    const { user } = await apiClient.request<{ user: User }>("/auth/register", {
      method: "POST",
      body: { name, email, password },
    });
    setUser(user);
    return user;
  }, []);

  const logout = useCallback(async () => {
    await apiClient.request("/auth/logout", { method: "POST" });
    setUser(null);
    router.push("/auth");
    router.refresh();
  }, [router]);

  const value = useMemo(
    () => ({ user, loading, login, register, logout, setUser }),
    [user, loading, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
