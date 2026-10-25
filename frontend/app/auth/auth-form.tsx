"use client";

import { CheckIcon, CircleDashedIcon, CircleIcon, EyeIcon, EyeOffIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/brand/logo";
import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, type FieldErrors } from "@/lib/api";
import { AuthRules, type Mode } from "@/lib/auth-form";
import { cn } from "@/lib/utils";

export function AuthForm({ initialMode, next }: { initialMode: Mode; next: string }) {
  const router = useRouter();
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const id = useId();
  const copy = AuthRules.COPY[mode];

  // The address and the tab title follow the tab, without a reload.
  useEffect(() => {
    document.title = `${copy.pageTitle} · Socra`;
  }, [copy.pageTitle]);

  const switchMode = (value: Mode) => {
    if (value === mode) return;
    setMode(value);
    setError(null);
    setFields({});
    window.history.replaceState(null, "", AuthRules.href(value, next));
  };

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const values = { name: String(form.get("name") ?? ""), email: String(form.get("email") ?? "").trim(), password, acceptedTerms };
    const problems = AuthRules.validate(mode, values);
    setError(null);
    setFields(problems);
    if (Object.keys(problems).length > 0) return;

    setSubmitting(true);
    try {
      const user = mode === "login" ? await login(values.email, values.password) : await register(values.name.trim(), values.email, values.password, acceptedTerms);
      router.push(AuthRules.destination(user.profile_complete, next));
      router.refresh();
    } catch (err) {
      setError(AuthRules.errorMessage(err));
      setFields(err instanceof ApiError ? err.fields : {});
      setSubmitting(false);
    }
  };

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-6 sm:py-10">
      <div className="grid w-full max-w-4xl overflow-hidden rounded-[28px] border-[1.5px] border-border bg-card shadow-card min-[900px]:grid-cols-[1fr_1.05fr]">
        <BrandPanel mode={mode} />

        <div className="flex flex-col gap-5 p-6 sm:p-9">
          <div role="tablist" aria-label="Sign in or create an account" className="grid grid-cols-2 gap-1 rounded-xl bg-muted p-1">
            {(["login", "register"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                id={`${id}-${value}`}
                aria-selected={mode === value}
                aria-controls={`${id}-panel`}
                onClick={() => switchMode(value)}
                className={cn(
                  "rounded-lg px-3 py-2 text-sm font-extrabold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  mode === value ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {AuthRules.COPY[value].submit}
              </button>
            ))}
          </div>

          <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${mode}`} className="flex flex-col gap-5">
            <div className="flex flex-col gap-1">
              <h1 className="font-heading text-2xl font-semibold tracking-tight">{copy.title}</h1>
              <p className="text-muted-foreground">{copy.description}</p>
            </div>

            <form
              onSubmit={onSubmit}
              onChange={(event) => {
                // An error about a field goes away as soon as the learner starts putting it right.
                const name = (event.target as unknown as HTMLInputElement).name;
                if (name && fields[name]) setFields((current) => Object.fromEntries(Object.entries(current).filter(([key]) => key !== name)));
              }}
              className="flex flex-col gap-4"
              noValidate
            >
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              {mode === "register" && (
                <FormField id="name" label="Name" errors={fields.name}>
                  <Input id="name" name="name" autoComplete="name" aria-invalid={!!fields.name} aria-describedby={fields.name ? "name-error" : undefined} />
                </FormField>
              )}
              <FormField id="email" label="Email" errors={fields.email}>
                <Input id="email" name="email" type="email" autoComplete="email" aria-invalid={!!fields.email} aria-describedby={fields.email ? "email-error" : undefined} />
              </FormField>
              <FormField id="password" label="Password" errors={fields.password}>
                <div className="relative">
                  <Input
                    id="password"
                    name="password"
                    type={shown ? "text" : "password"}
                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    aria-invalid={!!fields.password}
                    aria-describedby={fields.password ? "password-error" : mode === "register" ? "password-rules" : undefined}
                    className="pr-16"
                  />
                  <button
                    type="button"
                    onClick={() => setShown((value) => !value)}
                    aria-pressed={shown}
                    className="absolute inset-y-0 right-1 my-auto flex h-7 items-center gap-1 rounded-md px-2 text-xs font-extrabold text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    {shown ? <EyeOffIcon className="size-3.5" aria-hidden="true" /> : <EyeIcon className="size-3.5" aria-hidden="true" />}
                    {shown ? "Hide" : "Show"}
                    <span className="sr-only"> password</span>
                  </button>
                </div>
                {mode === "register" && (
                  <ul id="password-rules" aria-live="polite" className="flex flex-col gap-1 text-sm">
                    {AuthRules.checklist(password).map((item) => (
                      <li key={item.label} className={cn("flex items-center gap-2", item.met ? "text-success-text" : "text-muted-foreground")}>
                        {item.met ? (
                          <CheckIcon className="size-4 shrink-0" aria-label="done" />
                        ) : item.met === null ? (
                          <CircleDashedIcon className="size-4 shrink-0" aria-hidden="true" />
                        ) : (
                          <CircleIcon className="size-4 shrink-0" aria-hidden="true" />
                        )}
                        {item.label}
                      </li>
                    ))}
                  </ul>
                )}
              </FormField>
              {mode === "register" && (
                <div className="flex flex-col gap-1.5">
                  <label className="flex items-start gap-3 text-sm">
                    <input
                      type="checkbox"
                      name="accept_terms"
                      checked={acceptedTerms}
                      onChange={(e) => setAcceptedTerms(e.target.checked)}
                      aria-invalid={!!fields.accept_terms}
                      aria-describedby={fields.accept_terms ? "accept_terms-error" : undefined}
                      className="mt-0.5 size-5 shrink-0 accent-primary focus-visible:ring-3 focus-visible:ring-ring/50"
                    />
                    <span>
                      {AuthRules.CONSENT_LABEL}{" "}
                      <Link href="/terms" target="_blank" className="font-bold underline underline-offset-4">
                        Terms of Use
                      </Link>{" "}
                      and{" "}
                      <Link href="/privacy" target="_blank" className="font-bold underline underline-offset-4">
                        Privacy Policy
                      </Link>
                      .
                    </span>
                  </label>
                  {fields.accept_terms && (
                    <p id="accept_terms-error" className="text-sm text-destructive">
                      {fields.accept_terms.join(" ")}
                    </p>
                  )}
                </div>
              )}
              <Button type="submit" size="lg" disabled={submitting} className="mt-1 h-11">
                {submitting ? copy.pending : copy.submit}
              </Button>
            </form>

            <p className="text-center text-sm">
              <button
                type="button"
                onClick={() => switchMode(mode === "login" ? "register" : "login")}
                className="rounded-md font-extrabold text-primary-text underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {copy.switchLink}
              </button>
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}

/** The brand side: a strip on a phone, a full panel (headline, the three steps, tilted cards) from 900px. */
function BrandPanel({ mode }: { mode: Mode }) {
  return (
    <aside className="relative flex flex-col gap-6 overflow-hidden bg-primary p-6 text-primary-foreground sm:p-9 min-[900px]:justify-between">
      <Link href="/" aria-label="Socra home" className="w-fit rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-primary-foreground/60">
        <Logo tone="marigold" size="md" />
      </Link>

      <div className="relative z-10 flex flex-col gap-6">
        <p className="font-heading text-2xl leading-tight font-semibold min-[900px]:text-4xl">{AuthRules.COPY[mode].panel}</p>
        <ol className="flex flex-col gap-3 font-bold max-[899px]:hidden">
          {AuthRules.STEPS.map((step, index) => (
            <li key={step} className="flex items-center gap-3">
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary-foreground/25 font-mono text-sm">{index + 1}</span>
              {step}
            </li>
          ))}
        </ol>
      </div>

      <div aria-hidden="true" className="pointer-events-none absolute -right-24 -bottom-20 h-56 w-72 max-[899px]:hidden">
        <div className="absolute right-6 bottom-12 h-32 w-52 -rotate-[8deg] rounded-2xl bg-primary-foreground/15 p-4">
          <div className="mb-3 h-2.5 w-24 rounded-full bg-primary-foreground/40" />
          <div className="flex flex-col gap-2">
            <div className="h-6 rounded-lg bg-primary-foreground/25" />
            <div className="h-6 rounded-lg bg-primary-foreground/25" />
          </div>
        </div>
        <div className="absolute right-0 bottom-0 h-28 w-48 rotate-[6deg] rounded-2xl bg-primary-foreground/20 p-4">
          <div className="mb-3 h-2.5 w-20 rounded-full bg-primary-foreground/50" />
          <div className="h-2 w-36 rounded-full bg-primary-foreground/30" />
        </div>
      </div>
    </aside>
  );
}
