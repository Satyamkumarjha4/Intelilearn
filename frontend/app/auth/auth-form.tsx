"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, type FieldErrors } from "@/lib/api";

type Mode = "login" | "register";

const COPY: Record<Mode, { title: string; description: string; submit: string }> = {
  login: { title: "Welcome back", description: "Sign in to continue learning.", submit: "Sign in" },
  register: {
    title: "Create your account",
    description: "We'll find out what you already know, then teach you the rest.",
    submit: "Create account",
  },
};

export function AuthForm({ initialMode, next }: { initialMode: Mode; next: string }) {
  const router = useRouter();
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);

  const switchMode = (value: Mode) => {
    setMode(value);
    setError(null);
    setFields({});
  };

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");

    setSubmitting(true);
    setError(null);
    setFields({});
    try {
      const user =
        mode === "login" ? await login(email, password) : await register(String(form.get("name") ?? ""), email, password);
      router.push(user.profile_complete ? next : "/onboarding");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        setFields(err.fields);
      } else {
        setError("Something went wrong. Check your connection and try again.");
      }
      setSubmitting(false);
    }
  };

  const copy = COPY[mode];
  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <Tabs value={mode} onValueChange={(value) => switchMode(value as Mode)} className="mb-4">
          <TabsList className="w-full">
            <TabsTrigger value="login">Sign in</TabsTrigger>
            <TabsTrigger value="register">Create account</TabsTrigger>
          </TabsList>
        </Tabs>
        <CardTitle className="text-xl">
          <h1>{copy.title}</h1>
        </CardTitle>
        <CardDescription>{copy.description}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {mode === "register" && (
            <FormField id="name" label="Name" errors={fields.name}>
              <Input id="name" name="name" autoComplete="name" required aria-invalid={!!fields.name} />
            </FormField>
          )}
          <FormField id="email" label="Email" errors={fields.email}>
            <Input id="email" name="email" type="email" autoComplete="email" required aria-invalid={!!fields.email} />
          </FormField>
          <FormField
            id="password"
            label="Password"
            hint={mode === "register" ? "At least 8 characters, not too common." : undefined}
            errors={fields.password}
          >
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              aria-invalid={!!fields.password}
            />
          </FormField>
          <Button type="submit" disabled={submitting} className="mt-2">
            {submitting ? "Please wait…" : copy.submit}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
