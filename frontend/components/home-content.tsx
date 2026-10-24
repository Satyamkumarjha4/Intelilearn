"use client";

import { BookOpenCheckIcon, ClipboardListIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const STEPS = [
  { icon: ClipboardListIcon, title: "Quick diagnostic", text: "Ten questions show what you already know." },
  { icon: SparklesIcon, title: "A lesson at your level", text: "Prerequisites, core ideas and advanced concepts." },
  { icon: BookOpenCheckIcon, title: "Already know it?", text: "Get a cheat sheet, revision notes or practice set." },
];

export function HomeContent() {
  const { user, loading } = useAuth();

  if (loading) return <div className="h-40" aria-busy="true" />;

  return (
    <section className="flex flex-col gap-8">
      <header className="flex flex-col gap-3">
        <h1 className="text-4xl font-semibold tracking-tight">
          {user ? `Hi ${user.name.split(" ")[0]}, what do you want to learn?` : "Learn only what you don't know yet."}
        </h1>
        <p className="text-muted-foreground">
          {user
            ? "Start with a quick quiz. We'll find out what you already know and build the rest."
            : "Lesson Crafter finds out what you already know about a topic, then builds a lesson for the rest."}
        </p>
        <div className="flex gap-2">
          {user ? (
            <>
              <Link href="/lessons/new" className={buttonVariants()}>
                New lesson
              </Link>
              <Link href="/lessons" className={buttonVariants({ variant: "outline" })}>
                Your lessons
              </Link>
            </>
          ) : (
            <>
              <Link href="/auth?mode=register" className={buttonVariants()}>
                Get started
              </Link>
              <Link href="/auth" className={buttonVariants({ variant: "outline" })}>
                Sign in
              </Link>
            </>
          )}
        </div>
      </header>

      <div className="grid gap-4 sm:grid-cols-3">
        {STEPS.map(({ icon: Icon, title, text }) => (
          <Card key={title} size="sm">
            <CardHeader>
              <Icon className="mb-1 size-5 text-muted-foreground" />
              <CardTitle>{title}</CardTitle>
              <CardDescription>{text}</CardDescription>
            </CardHeader>
          </Card>
        ))}
      </div>
    </section>
  );
}
