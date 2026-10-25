"use client";

import { MailIcon } from "lucide-react";
import Link from "next/link";
import { useRef } from "react";

import { CopyButton } from "@/components/contact/copy-button";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { CONTACT, CONTACT_TOPICS, type ContactTopic } from "@/content/legal/contact";
import { Mailto } from "@/lib/mailto";

/** The Contact page: the address (to copy or to open in the mail app), a card per kind of message with its subject line
 *  ready to copy (mail links do not work for everyone), and the grievance officer. */
export function ContactPage() {
  const address = useRef<HTMLSpanElement>(null);
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-4xl font-semibold tracking-tight">{CONTACT.heading}</h1>
        <p className="text-lg text-muted-foreground">{CONTACT.intro}</p>
      </header>

      <Card className="border-primary bg-primary-soft">
        <CardContent className="flex flex-col gap-4 px-5">
          <p className="flex items-center gap-3 font-heading text-2xl font-semibold break-all">
            <MailIcon className="size-6 shrink-0 text-primary-text" aria-hidden="true" />
            <span ref={address} className="select-all">
              {CONTACT.email}
            </span>
          </p>
          <div className="flex flex-wrap gap-3">
            <CopyButton text={CONTACT.email} label="Copy email" what={CONTACT.email} variant="outline" target={address} />
            <a href={`mailto:${CONTACT.email}`} className={buttonVariants()}>
              Open in mail app
            </a>
          </div>
        </CardContent>
      </Card>

      <section aria-labelledby="topics" className="flex flex-col gap-3">
        <h2 id="topics" className="font-heading text-2xl font-semibold">
          {CONTACT.topicsHeading}
        </h2>
        <ul className="grid gap-4 sm:grid-cols-2">
          {CONTACT_TOPICS.map((topic) => (
            <li key={topic.id}>
              <TopicCard topic={topic} />
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="grievance" className="flex flex-col gap-2 rounded-2xl border-[1.5px] border-border bg-card p-5">
        <h2 id="grievance" className="font-heading text-xl font-semibold">
          {CONTACT.grievance.title}
        </h2>
        <p>{CONTACT.grievance.text}</p>
      </section>

      <p className="text-sm text-muted-foreground">
        For anything about your personal data, see the{" "}
        <Link href="/privacy" className="font-bold text-primary-text underline underline-offset-4">
          Privacy Policy
        </Link>
        . For the rules of using Socra, see the{" "}
        <Link href="/terms" className="font-bold text-primary-text underline underline-offset-4">
          Terms of Use
        </Link>
        .
      </p>
    </div>
  );
}

function TopicCard({ topic }: { topic: ContactTopic }) {
  const subject = useRef<HTMLElement>(null);
  return (
    <Card className="h-full">
      <CardContent className="flex h-full flex-col gap-3 px-5">
        <h3 className="font-heading text-lg leading-snug font-semibold">{topic.title}</h3>
        <p className="text-sm text-muted-foreground">{topic.helper}</p>
        <p className="mt-auto flex flex-col gap-1 text-sm">
          <span className="font-extrabold">Subject line</span>
          <code ref={subject} className="w-fit rounded-md bg-muted px-2 py-1 font-mono text-xs select-all">
            {topic.subject}
          </code>
        </p>
        <div className="flex flex-wrap gap-2">
          <a href={Mailto.link(CONTACT.email, topic.subject)} className={buttonVariants({ variant: "marigold", size: "sm" })}>
            Write to us
          </a>
          <CopyButton text={topic.subject} label="Copy subject" what={topic.subject} size="sm" target={subject} />
        </div>
      </CardContent>
    </Card>
  );
}
