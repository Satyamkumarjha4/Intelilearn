import type { Metadata } from "next";

import { AuthRules } from "@/lib/auth-form";
import { RedirectPolicy } from "@/lib/safe-redirect";

import { FinishForm } from "./finish-form";

export const metadata: Metadata = { title: AuthRules.FINISH.pageTitle };

export default async function FinishPage({ searchParams }: PageProps<"/auth/finish">) {
  const params = await searchParams;

  return <FinishForm next={RedirectPolicy.safeNext(params.next, AuthRules.DEFAULT_NEXT)} />;
}
