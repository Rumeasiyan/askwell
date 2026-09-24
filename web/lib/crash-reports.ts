/**
 * Crash reports — `docs/ux/settings.md` §7, `M7-OPS-DOC-165`.
 *
 * When Askwell fails unexpectedly it writes a small report on this machine
 * (`askwell.crash_report`). Nothing sends it anywhere. This lists what is
 * there so the person can download one and attach it to an issue
 * themselves, which is the only way a report ever leaves the machine.
 */

export interface CrashReportFile {
  name: string;
  bytes: number;
}

export interface CrashReports {
  directory: string;
  reports: CrashReportFile[];
}

/** Said beside the list, so the person knows what they would be attaching. */
export const CRASH_REPORT_CONTENTS =
  "A crash report holds the Askwell version, your platform and profile, and where in " +
  "Askwell's own code the failure happened. It leaves out the error message and anything " +
  "from your files, questions or databases. It is saved on this machine and never sent: " +
  "if you want to include one in an issue, download it and attach it yourself.";

export async function fetchCrashReports(signal?: AbortSignal): Promise<CrashReports> {
  const response = await fetch("/crash-reports", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} listing crash reports.`);
  }
  return (await response.json()) as CrashReports;
}

export function crashReportUrl(name: string): string {
  return `/crash-reports/${encodeURIComponent(name)}`;
}

/** `crash-20260924T101500Z-api-1a2b3c4d.json` → `2026-09-24 10:15 UTC, api`. */
export function describeCrashReport(name: string): string {
  const match = /^crash-(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})\d{2}Z-([a-z]+)-/.exec(name);
  if (match === null) return name;
  const [, year, month, day, hour, minute, component] = match;
  return `${year}-${month}-${day} ${hour}:${minute} UTC, ${component}`;
}
