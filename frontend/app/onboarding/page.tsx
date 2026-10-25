import { RedirectPolicy } from "@/lib/safe-redirect";

import { OnboardingView } from "./onboarding-view";

// `?next=` is where the learner was headed before onboarding came in the way (see `AuthRules.destination`).
export default async function OnboardingPage({ searchParams }: PageProps<"/onboarding">) {
  const { next } = await searchParams;
  return <OnboardingView next={RedirectPolicy.safeNext(next, "/lessons")} />;
}
