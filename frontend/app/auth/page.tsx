import type { Metadata } from "next";

import { AuthRules } from "@/lib/auth-form";
import { RedirectPolicy } from "@/lib/safe-redirect";

import { AuthForm } from "./auth-form";

export async function generateMetadata({ searchParams }: PageProps<"/auth">): Promise<Metadata> {
  const { mode } = await searchParams;
  return { title: AuthRules.COPY[mode === "register" ? "register" : "login"].pageTitle };
}

export default async function AuthPage({ searchParams }: PageProps<"/auth">) {
  const params = await searchParams;
  const mode = params.mode === "register" ? "register" : "login";

  return <AuthForm initialMode={mode} next={RedirectPolicy.safeNext(params.next, AuthRules.DEFAULT_NEXT)} />;
}
