"use client";

import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { ProfileForm } from "@/components/profile-form";
import { useProfile } from "@/components/use-profile";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function OnboardingPage() {
  const router = useRouter();
  const { user, setUser } = useAuth();
  const { profile, error } = useProfile();

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-10">
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">
            <h1>{user ? `Welcome, ${user.name.split(" ")[0]}!` : "Welcome!"}</h1>
          </CardTitle>
          <CardDescription>
            Tell us a little about yourself. Every quiz and lesson is pitched at your level, in the way you learn best.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {profile && (
            <ProfileForm
              initial={profile}
              submitLabel="Continue"
              onSaved={(saved) => {
                if (user) setUser({ ...user, profile_complete: saved.profile_complete });
                router.push("/");
                router.refresh();
              }}
            />
          )}
        </CardContent>
      </Card>
    </main>
  );
}
