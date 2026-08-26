// eslint-config-next 16 ships flat config directly. The FlatCompat shim that
// older Next projects use is for the legacy `.eslintrc` shape and fails
// against this one, so it is deliberately not here.
import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  ...coreWebVitals,
  ...typescript,
  { ignores: ["out/**", ".next/**", "node_modules/**"] },
];

export default config;
