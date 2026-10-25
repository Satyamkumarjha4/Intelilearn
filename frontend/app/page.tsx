import type { Metadata } from "next";
import { headers } from "next/headers";

import { Band } from "@/components/landing/band";
import { CtaBand } from "@/components/landing/cta-band";
import { Hero } from "@/components/landing/hero";
import { LandingFooter } from "@/components/landing/landing-footer";
import { LandingHeader } from "@/components/landing/landing-header";
import { PathsCarousel } from "@/components/landing/paths-carousel";
import { ProofStrip } from "@/components/landing/proof-strip";
import { WalkthroughSection } from "@/components/landing/walkthrough";
import { DemoQuestionFetcher, DemoQuestions } from "@/lib/demo-question";
import { LANDING_META, PATH_INTRO } from "@/lib/landing-content";

import "./landing.css";

export const metadata: Metadata = {
  title: { absolute: LANDING_META.title },
  description: LANDING_META.description,
  openGraph: { title: LANDING_META.title, description: LANDING_META.description, type: "website" },
};

// The public landing page, for visitors who are not signed in (proxy.ts sends everyone else on to the app).
// The hero's question is picked at random on the server for every load (never cached), so the page arrives with it:
// no flash, and no question at all is a built-in one, not an error.
export default async function Home() {
  const clientIp = (await headers()).get("x-forwarded-for")?.split(",")[0]?.trim();
  const question = (await DemoQuestionFetcher.forServer().fetch({ clientIp })) ?? DemoQuestions.fallback();

  return (
    <>
      <LandingHeader />
      <main className="flex flex-1 flex-col">
        <Hero question={question} />
        <Band id="how" eyebrow="How it works" title="It starts by finding out what you already know." text="Most courses start at page one. Socra starts where you are.">
          <WalkthroughSection />
        </Band>
        <Band id="paths" eyebrow="Three ways forward" title="Your score decides what happens next." text={PATH_INTRO}>
          <PathsCarousel />
        </Band>
        <ProofStrip />
        <CtaBand />
      </main>
      <LandingFooter />
    </>
  );
}
