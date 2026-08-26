"use client";

import { useCallback, useSyncExternalStore } from "react";

type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "askwell-theme";
const CHANGED = "askwell:theme-changed";

/**
 * The DOM attribute is the state, not a React copy of it.
 *
 * An inline script in the document head applies the stored theme before
 * hydration, so a `useState` seeded in an effect would be a second, later,
 * competing source of the same truth — which is what the
 * `react-hooks/set-state-in-effect` rule is objecting to, correctly.
 * `useSyncExternalStore` reads the attribute that is already right.
 */
function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    media.removeEventListener("change", onChange);
  };
}

function currentTheme(): Theme {
  const attribute = document.documentElement.getAttribute("data-theme");
  return attribute === "light" || attribute === "dark" ? attribute : "system";
}

/** Static export renders on the build machine, which has no preference. */
function serverTheme(): Theme {
  return "system";
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, currentTheme, serverTheme);

  const choose = useCallback((next: Theme) => {
    const root = document.documentElement;
    if (next === "system") {
      // Removing the attribute rather than writing a resolved value: writing
      // "light" at the moment the OS happened to be light would silently
      // freeze the interface there, and §8 requires the OS setting to keep
      // working.
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", next);
    }
    try {
      if (next === "system") window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage can throw rather than return null in some embedding contexts.
      // The override still applies for this session; only persistence is lost.
    }
    window.dispatchEvent(new Event(CHANGED));
  }, []);

  const options: Theme[] = ["system", "light", "dark"];

  return (
    <div className="flex gap-1" role="group" aria-label="Theme">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => choose(option)}
          aria-pressed={theme === option}
          className="ask-navigates px-2 py-1 capitalize"
          style={{
            fontSize: "var(--t-meta)",
            background: theme === option ? "var(--sunk)" : "transparent",
            border: "1px solid var(--rule)",
            color: theme === option ? "var(--ink)" : "var(--muted)",
          }}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
