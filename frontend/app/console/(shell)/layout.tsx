import type { Metadata } from "next";

import { ConsoleShell } from "@/components/console/console-shell";

export const metadata: Metadata = {
  title: { default: "Console · Socra", template: "%s · Console · Socra" },
  robots: { index: false, follow: false },
};

export default function ConsoleLayout({ children }: LayoutProps<"/console">) {
  return <ConsoleShell>{children}</ConsoleShell>;
}
