import type { Metadata } from "next";

import { SettingsView } from "@/components/console/settings/settings-view";

export const metadata: Metadata = { title: "Lesson settings" };

export default function SettingsPage() {
  return <SettingsView />;
}
