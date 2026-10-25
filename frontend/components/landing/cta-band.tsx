"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Reveal } from "@/components/landing/reveal";
import { Button } from "@/components/ui/button";
import { CTA, REGISTER_HREF } from "@/lib/landing-content";
import { PendingTopic } from "@/lib/pending-topic";

/** The last push: name a topic and go sign up. The topic waits in `sessionStorage` for the screens after sign-up. */
export function CtaBand() {
  const router = useRouter();
  const [topic, setTopic] = useState("");

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    new PendingTopic(undefined, CTA.maxLength).save(topic);
    router.push(REGISTER_HREF);
  };

  return (
    <section aria-labelledby="cta-title" className="mx-auto w-full max-w-[1180px] px-4">
      <Reveal tilt className="mt-4 mb-9 rounded-[28px] bg-primary px-6 py-12 text-center text-primary-foreground shadow-[0_6px_0_var(--primary-deep)]">
        <h2 id="cta-title" className="text-[34px] max-[560px]:text-[26px]">
          {CTA.title}
        </h2>
        <p className="mt-2 mb-6 text-[17px] font-semibold opacity-90">{CTA.text}</p>
        <form onSubmit={submit} className="mx-auto flex max-w-[580px] gap-2 rounded-[18px] bg-card p-1.5 max-[560px]:flex-col">
          <input
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            maxLength={CTA.maxLength}
            placeholder={CTA.placeholder}
            aria-label="Topic"
            className="min-w-0 flex-1 rounded-xl bg-transparent px-3.5 py-2.5 text-[17px] text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          <Button type="submit" variant="marigold" size="xl">
            Get started
          </Button>
        </form>
      </Reveal>
    </section>
  );
}
