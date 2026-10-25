"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";

export default function NewLessonPage() {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const [context, setContext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { lesson_id } = await lessonsApi.create(topic, context);
      router.push(`/lessons/${lesson_id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err);
        if (err.status === 429) toast.error("You've started a lot of lessons. Try again later.");
      } else {
        toast.error("Could not start the lesson.");
      }
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-10">
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">
            <h1>What do you want to learn?</h1>
          </CardTitle>
          <CardDescription>
            We&apos;ll start with a short quiz to find out what you already know, then build the rest.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
            {error && !error.fields.topic && !error.fields.user_context && (
              <Alert variant="destructive">
                <AlertDescription>{error.message}</AlertDescription>
              </Alert>
            )}
            <FormField id="topic" label="Topic" errors={error?.fields.topic}>
              <Input
                id="topic"
                value={topic}
                maxLength={200}
                placeholder="Binary search, Asexual reproduction, Coordinate geometry…"
                onChange={(e) => setTopic(e.target.value)}
                required
                autoFocus
              />
            </FormField>
            <FormField
              id="context"
              label="Anything we should know? (optional)"
              errors={error?.fields.user_context}
            >
              <Textarea
                id="context"
                value={context}
                maxLength={1000}
                rows={3}
                placeholder="For my DSA exam. I already know arrays."
                onChange={(e) => setContext(e.target.value)}
              />
            </FormField>
            <Button type="submit" disabled={busy || topic.trim().length < 2} className="self-start">
              {busy ? "Starting…" : "Start the quiz"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
