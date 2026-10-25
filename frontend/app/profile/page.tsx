"use client";

import { toast } from "sonner";

import { useAuth } from "@/components/auth-provider";
import { ProfileEditor } from "@/components/profile/profile-editor";
import { useProfile } from "@/components/use-profile";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CONTACT, CONTACT_TOPICS } from "@/content/legal/contact";
import { Mailto } from "@/lib/mailto";

export default function ProfilePage() {
  const { user, setUser } = useAuth();
  const { profile, error } = useProfile();

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="font-heading text-3xl font-semibold tracking-tight">Your profile</h1>
        <p className="text-muted-foreground">New lessons use these details to match your level and the way you learn.</p>
      </header>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {!profile && !error && <Skeleton className="h-96 rounded-[22px]" />}
      {profile && (
        <ProfileEditor
          initial={profile}
          onSaved={(saved) => {
            if (user) setUser({ ...user, name: saved.name, profile_complete: saved.profile_complete });
            toast.success("Profile saved");
          }}
        />
      )}

      {user && (
        <section aria-labelledby="delete-heading" className="flex flex-col gap-3 rounded-2xl border-[1.5px] border-destructive/40 p-5">
          <h2 id="delete-heading" className="font-heading text-xl font-semibold">
            Delete my account
          </h2>
          <p className="text-muted-foreground">
            You can ask us to delete your account and everything in it: your profile, lessons, answers and scores. For now we do this by email. Write from
            the address you signed up with, and we&apos;ll delete it within 30 days. You can also ask for a copy of your data first.
          </p>
          <a
            href={Mailto.link(CONTACT.email, CONTACT_TOPICS.find((topic) => topic.id === "privacy")!.subject, `Please delete my Socra account and its data.\nAccount email: ${user.email}\n`)}
            className={buttonVariants({ variant: "destructive", className: "self-start" })}
          >
            Email us to delete my account
          </a>
          <p className="text-sm text-muted-foreground">
            No mail app? Write to <span className="font-bold select-all">{CONTACT.email}</span> with the subject <span className="font-bold select-all">[Socra] Privacy request</span>.
          </p>
        </section>
      )}
    </main>
  );
}
