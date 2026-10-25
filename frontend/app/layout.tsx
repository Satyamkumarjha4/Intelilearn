import type { Metadata } from "next";
import { Fredoka, JetBrains_Mono, Nunito } from "next/font/google";
import { ThemeProvider } from "next-themes";

import { AuthProvider } from "@/components/auth-provider";
import { SiteHeader } from "@/components/site-header";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

// Fredoka for headings, Nunito for body text and controls, JetBrains Mono for code. Each gets its own variable
// (mapped to --font-heading / --font-sans / --font-mono in globals.css).
const fredoka = Fredoka({
  variable: "--font-fredoka",
  subsets: ["latin"],
  weight: ["500", "600"],
});

const nunito = Nunito({
  variable: "--font-nunito",
  subsets: ["latin"],
  weight: ["400", "600", "700", "800"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["500"],
});

export const metadata: Metadata = {
  title: { template: "%s · Socra", default: "Socra" },
  description: "Learn only what you don't know yet. Socra asks before it teaches.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning data-scroll-behavior="smooth" className={`${fredoka.variable} ${nunito.variable} ${jetbrainsMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-background font-sans text-foreground">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <AuthProvider>
            <SiteHeader />
            <div className="flex flex-1 flex-col">{children}</div>
            <Toaster richColors position="top-center" />
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
