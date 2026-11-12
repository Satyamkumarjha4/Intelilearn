import type { Metadata } from "next";

import { AuthRules } from "@/lib/auth-form";
import { RedirectPolicy } from "@/lib/safe-redirect";

import { ResetForm } from "./reset-form";

export const metadata: Metadata = { title: AuthRules.RESET.pageTitle };

export default async function ResetPage({ searchParams }: PageProps<"/auth/reset">) {
  const params = await searchParams;

  return <ResetForm next={RedirectPolicy.safeNext(params.next, AuthRules.DEFAULT_NEXT)} />;
}
