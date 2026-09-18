/**
 * Connecting Askwell to a database the user already runs. `M4-CONN-FE-096`.
 *
 * `docs/data-sources.md` §4: host, port, database, user, password, then
 * connect, probe for write access, introspect the schema. The write probe
 * (`M4-CONN-SEC-097`) is not wired yet — a write-capable credential is
 * accepted by this wizard today, exactly as that ticket's own "Known gaps"
 * line says.
 */

export const ENGINES = [
  { value: "postgresql", label: "PostgreSQL", defaultPort: 5432 },
  { value: "mysql", label: "MySQL", defaultPort: 3306 },
  { value: "mariadb", label: "MariaDB", defaultPort: 3306 },
  { value: "sqlserver", label: "SQL Server", defaultPort: 1433 },
] as const;

export type Engine = (typeof ENGINES)[number]["value"];

export interface ConnectionSource {
  id: string;
  name: string | null;
  status: string;
}

export interface ConnectionOutcome {
  ok: boolean;
  /** Which of the distinguishable failures this was — null on success.
   * `docs/data-sources.md` §4: a wrong host, a refused connection, wrong
   * credentials and a network the egress proxy blocks are four different
   * fixes, and this is how the wizard tells them apart. */
  reason_code: string | null;
  message: string;
  source: ConnectionSource | null;
}

export interface ConnectionFields {
  engine: Engine;
  host: string;
  port: number;
  database: string;
  user: string;
  password: string;
}

/**
 * Attempt one connection. Never throws for a refused or unreachable
 * database — every one of those comes back as `ConnectionOutcome` with
 * `ok: false` and a `reason_code` the wizard renders. Only a response the
 * server did not produce at all (a network failure reaching Askwell's own
 * API, or a body that is not JSON) becomes a thrown error.
 */
export async function addConnectionSource(fields: ConnectionFields): Promise<ConnectionOutcome> {
  const response = await fetch("/sources/connection", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(fields),
  });
  const body = (await response.json().catch(() => null)) as ConnectionOutcome | null;
  if (body === null) {
    throw new Error(`Askwell answered with ${response.status}.`);
  }
  return body;
}
