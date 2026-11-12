import type { Metadata } from "next";

import { AuthRules } from "@/lib/auth-form";
import { RedirectPolicy } from "@/lib/safe-redirect";

import { ForgotForm } from "./forgot-form";

export const metadata: Metadata = { title: AuthRules.FORGOT.pageTitle };

export default async function ForgotPage({ searchParams }: PageProps<"/auth/forgot">) {
  const params = await searchParams;

  return <ForgotForm next={RedirectPolicy.safeNext(params.next, AuthRules.DEFAULT_NEXT)} />;
}
