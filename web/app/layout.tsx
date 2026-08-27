import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { Shell } from "@/components/shell/shell";
import { THEME_SCRIPT } from "./theme-script";

export const metadata: Metadata = {
  title: "Askwell",
  description: "A personal AI over your own files and databases.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // suppressHydrationWarning: a theme override read from local storage is
    // applied to <html> before React hydrates, so the server-rendered
    // attribute and the client one legitimately differ on first paint.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Runs before first paint so the interface never renders in the wrong
            theme and then corrects itself. The content is a constant defined
            in this repository — no user input reaches it. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
