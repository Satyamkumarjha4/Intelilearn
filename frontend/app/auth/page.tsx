import type { Metadata } from "next";

import { AuthForm } from "./auth-form";

export const metadata: Metadata = { title: "Sign in · Lesson Crafter" };

// Only same-site relative paths are allowed as post-login destinations (no open redirects).
function safeNext(value: string | string[] | undefined): string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

export default async function AuthPage({ searchParams }: PageProps<"/auth">) {
  const params = await searchParams;
  const mode = params.mode === "register" ? "register" : "login";

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <AuthForm initialMode={mode} next={safeNext(params.next)} />
    </main>
  );
}
