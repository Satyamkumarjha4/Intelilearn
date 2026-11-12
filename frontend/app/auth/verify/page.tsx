import type { Metadata } from "next";

import { AuthRules } from "@/lib/auth-form";
import { RedirectPolicy } from "@/lib/safe-redirect";

import { VerifyForm } from "./verify-form";

export const metadata: Metadata = { title: AuthRules.VERIFY.pageTitle };

export default async function VerifyPage({ searchParams }: PageProps<"/auth/verify">) {
  const params = await searchParams;

  return <VerifyForm purpose={AuthRules.purposeOf(params.purpose)} next={RedirectPolicy.safeNext(params.next, AuthRules.DEFAULT_NEXT)} />;
}
