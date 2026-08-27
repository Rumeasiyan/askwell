"use client";

import { useCallback, useEffect, useState } from "react";

import type { Assistant, Health, Reachability } from "@/lib/health";

/**
 * Poll the two status surfaces.
 *
 * Every failure becomes `unreachable`, never a partially-filled healthy state.
 * A shell that renders as if everything is fine because a fetch threw is a
 * shell that lies at the exact moment the user needs it not to.
 */
export function useStatus(intervalMs = 5000): Reachability {
  const [status, setStatus] = useState<Reachability>({ kind: "loading" });

  const read = useCallback(async (): Promise<void> => {
    try {
      const [healthResponse, assistantResponse] = await Promise.all([
        fetch("/health", { cache: "no-store" }),
        fetch("/assistant", { cache: "no-store" }),
      ]);
      if (!healthResponse.ok || !assistantResponse.ok) {
        setStatus({
          kind: "unreachable",
          error: `Askwell answered with ${healthResponse.status}.`,
        });
        return;
      }
      const health = (await healthResponse.json()) as Health;
      const assistant = (await assistantResponse.json()) as Assistant;
      setStatus({ kind: "reporting", health, assistant });
    } catch {
      setStatus({
        kind: "unreachable",
        error: "Askwell is not answering at this address.",
      });
    }
  }, []);

  useEffect(() => {
    // Scheduled rather than called straight away. `read` resolves into
    // `setState`, and starting it synchronously inside the effect is what
    // `react-hooks/set-state-in-effect` objects to — correctly, since it can
    // cascade renders. A zero timeout is still immediate to a person and puts
    // the first update after the effect has finished.
    const first = setTimeout(() => void read(), 0);
    const repeating = setInterval(() => void read(), intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(repeating);
    };
  }, [read, intervalMs]);

  return status;
}
