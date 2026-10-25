import type { Metadata } from "next";

export const metadata: Metadata = { title: "Welcome" };

export default function OnboardingLayout({ children }: LayoutProps<"/onboarding">) {
  return children;
}
