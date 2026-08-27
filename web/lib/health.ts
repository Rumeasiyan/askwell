/**
 * What the API says about itself.
 *
 * Two surfaces, deliberately separate. `/health` reports each component;
 * `/assistant` reports why the assistant cannot answer and what still works.
 * Collapsing them would lose the distinction M0-MODEL-BE-020 exists to keep.
 */

export type ComponentState = "reachable" | "unreachable" | "unknown";

export interface Component {
  component: string;
  state: ComponentState;
  reason: string | null;
  address: string;
  detail?: Record<string, unknown> | null;
}

export interface Health {
  version: string;
  environment: string;
  profile: string;
  components: Component[];
}

export interface Assistant {
  available: boolean;
  cause: string | null;
  headline: string;
  fix: string | null;
  still_works: string[];
  model: string | null;
  acceleration: string | null;
  restarts: number;
}

/**
 * What the shell knows. `unreachable` is its own case rather than an empty
 * health object: Askwell not answering at all and Askwell answering with bad
 * news are different things, and the shell must never render the first as the
 * second — or as healthy.
 */
export type Reachability =
  | { kind: "loading" }
  | { kind: "unreachable"; error: string }
  | { kind: "reporting"; health: Health; assistant: Assistant };

/** Names the user recognises. `egress_proxy` is not one of them. */
export const COMPONENT_LABELS: Record<string, string> = {
  database: "Your data",
  queue: "Background work",
  worker: "Indexing",
  inference: "The assistant",
  egress_proxy: "Network guard",
};

export function label(component: string): string {
  return COMPONENT_LABELS[component] ?? component;
}
