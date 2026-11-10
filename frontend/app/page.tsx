import type { Metadata } from "next";
import { cookies, headers } from "next/headers";

import { Adapts } from "@/components/landing/adapts";
import { CtaBand } from "@/components/landing/cta-band";
import { Faq } from "@/components/landing/faq";
import { Hero } from "@/components/landing/hero";
import { HowItWorks } from "@/components/landing/how-it-works";
import { LandingFooter } from "@/components/landing/landing-footer";
import { LandingHeader } from "@/components/landing/landing-header";
import { Pricing } from "@/components/landing/pricing";
import { Progress } from "@/components/landing/progress";
import { Revise } from "@/components/landing/revise";
import { Voices } from "@/components/landing/voices";
import { LANDING_META, SESSION_COOKIE } from "@/lib/landing-content";
import { PublicLanding } from "@/lib/landing/public-landing";

import "./landing.css";

export const metadata: Metadata = {
  title: { absolute: LANDING_META.title },
  description: LANDING_META.description,
  openGraph: { title: LANDING_META.title, description: LANDING_META.description, type: "website", siteName: "Socra" },
  twitter: { card: "summary", title: LANDING_META.title, description: LANDING_META.description },
};

// The public landing page. It reads the testimonials and the prices on the server for every load (never cached by Next: a
// change made in the console shows on the next one), so the page arrives whole, with no flash and nothing to wait for. If
// either cannot be read the page still loads: the maker's note instead of quotes, and no numbers in the pricing.
export default async function Home() {
  const clientIp = (await headers()).get("x-forwarded-for")?.split(",")[0]?.trim();
  const signedIn = (await cookies()).has(SESSION_COOKIE);
  const landing = PublicLanding.forServer();
  const [testimonials, pricing] = await Promise.all([landing.testimonials({ clientIp }), landing.pricing({ clientIp })]);

  return (
    <>
      <LandingHeader />
      <main className="flex flex-1 flex-col">
        <Hero pricing={pricing} />
        <HowItWorks quickCheckQuestions={pricing?.quick_check_questions ?? null} />
        <Voices testimonials={testimonials} />
        <Adapts />
        <Progress />
        <Revise />
        <Pricing pricing={pricing} signedIn={signedIn} />
        <Faq pricing={pricing} />
        <CtaBand pricing={pricing} />
      </main>
      <LandingFooter />
    </>
  );
}
