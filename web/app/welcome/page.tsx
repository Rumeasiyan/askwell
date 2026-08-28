import { WelcomeScreen } from "@/components/welcome/welcome-screen";

/**
 * Route: `/welcome` — shown until a first source is indexed, then never
 * again. `docs/ux/first-run.md`, `M1-LIB-FE-052`.
 */
export default function WelcomePage() {
  return <WelcomeScreen />;
}
