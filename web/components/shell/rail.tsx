"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The left rail: the only route to sources, memory and settings.
 *
 * `docs/ux/design-system.md` §4 — hiding it without a way back strands the
 * user, which is why the drawer in `M0-SHELL-FE-017a` makes it reachable
 * rather than removing it.
 */
export const DESTINATIONS = [
  { href: "/", label: "Ask", hint: "Ask a question of your own material" },
  { href: "/library/", label: "Library", hint: "Every source you have added" },
  { href: "/memory/", label: "Memory", hint: "What Askwell has learned about your material" },
  { href: "/settings/", label: "Settings", hint: "Profile, retention, network activity" },
] as const;

/**
 * `onNavigate` defaults to a no-op rather than being optional at the call
 * site. With `exactOptionalPropertyTypes`, an optional handler cannot be
 * handed straight to `onClick` — and a default is clearer than a cast anyway.
 * The drawer in M0-SHELL-FE-017a passes its own, to close itself.
 */
export function Rail({ onNavigate = () => {} }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav aria-label="Askwell" className="flex flex-col gap-1 p-3">
      {DESTINATIONS.map((destination) => {
        // Exact match for the root; prefix for the rest, so a source viewer
        // under /library/ still shows Library as where you are.
        const active =
          destination.href === "/"
            ? pathname === "/"
            : pathname.startsWith(destination.href);
        return (
          <Link
            key={destination.href}
            href={destination.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            title={destination.hint}
            className="ask-navigates px-3 py-2"
            style={{
              background: active ? "var(--sunk)" : "transparent",
              color: active ? "var(--ink)" : "var(--muted)",
              fontSize: "var(--t-ui)",
              // A control that navigates states where it goes; the active one
              // is marked by more than colour, because colour is never the
              // only signal (§8).
              borderLeft: active ? "2px solid var(--provenance)" : "2px solid transparent",
            }}
          >
            {destination.label}
          </Link>
        );
      })}
    </nav>
  );
}
