import type { Metadata } from "next";

import { safeNext } from "@/lib/safe-redirect";

import { AuthForm } from "./auth-form";

export const metadata: Metadata = { title: "Sign in · Lesson Crafter" };

export default async function AuthPage({ searchParams }: PageProps<"/auth">) {
  const params = await searchParams;
  const mode = params.mode === "register" ? "register" : "login";

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <AuthForm initialMode={mode} next={safeNext(params.next)} />
    </main>
  );
}
