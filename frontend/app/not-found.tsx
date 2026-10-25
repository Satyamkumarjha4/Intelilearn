import { CompassIcon } from "lucide-react";
import Link from "next/link";

import { StatusCard } from "@/components/status-card";
import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-4 py-10">
      <StatusCard
        icon={CompassIcon}
        title="We couldn't find that page"
        actions={
          <Link href="/lessons" className={buttonVariants()}>
            Back to my lessons
          </Link>
        }
      >
        <p>The link may be old, or the lesson may have been deleted.</p>
      </StatusCard>
    </main>
  );
}
