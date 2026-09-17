"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useClarificationsTotal } from "@/lib/use-clarifications-count";

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
  {
    href: "/clarifications/",
    label: "Clarifications",
    hint: "Questions Askwell could not work out on its own",
  },
  { href: "/memory/", label: "Memory", hint: "What Askwell has learned about your material" },
  {
    href: "/settings/",
    label: "Settings",
    hint: "Folders Askwell may read, profile, retention, network activity",
  },
] as const;

/**
 * `onNavigate` defaults to a no-op rather than being optional at the call
 * site. With `exactOptionalPropertyTypes`, an optional handler cannot be
 * handed straight to `onClick` — and a default is clearer than a cast anyway.
 * The drawer in M0-SHELL-FE-017a passes its own, to close itself.
 */
export function Rail({ onNavigate = () => {} }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const clarificationsTotal = useClarificationsTotal();

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
            className="ask-navigates flex items-center justify-between px-3 py-2"
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
            <span>{destination.label}</span>
            {destination.href === "/clarifications/" &&
            clarificationsTotal !== null &&
            clarificationsTotal > 0 ? (
              <RailBadge count={clarificationsTotal} />
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * A count, never an alarm. `docs/ux/clarifications.md` §6 rules out a red
 * dot implying something is broken — this reads a plain number in the same
 * ink as everything else in the rail, not `--alarm`.
 */
function RailBadge({ count }: { count: number }) {
  return (
    <span
      className="ask-micro"
      style={{
        background: "var(--sunk)",
        borderRadius: "var(--radius)",
        padding: "0 6px",
        color: "var(--ink)",
      }}
    >
      {count}
    </span>
  );
}
