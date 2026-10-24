"use client";

import { toast } from "sonner";

import { useAuth } from "@/components/auth-provider";
import { ProfileForm } from "@/components/profile-form";
import { useProfile } from "@/components/use-profile";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function ProfilePage() {
  const { user, setUser } = useAuth();
  const { profile, error } = useProfile();

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-10">
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">
            <h1>Your profile</h1>
          </CardTitle>
          <CardDescription>New lessons use these details to match your level and learning style.</CardDescription>
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
              submitLabel="Save changes"
              showAccountFields
              onSaved={(saved) => {
                if (user) setUser({ ...user, name: saved.name, profile_complete: saved.profile_complete });
                toast.success("Profile saved");
              }}
            />
          )}
        </CardContent>
      </Card>
    </main>
  );
}
