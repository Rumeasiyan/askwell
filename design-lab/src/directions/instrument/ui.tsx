/* Shared primitives for the "instrument" direction.
   Every visual value binds to a token in src/tokens.css — no hardcoded hex, radius or font.
   See ../../../docs/ux/design-system.md; that document is the source of truth. */
import { useState, type ReactNode } from 'react'

export const paper = 'bg-[var(--ask-paper)] text-[var(--ask-ink)]'
export const mono = 'font-[var(--ask-font-app)]'
export const serif = 'font-[var(--ask-font-text)]'

/* ---------- shell ---------- */

/* Askwell's theme is controlled inside the frame, not by the OS, so a direction can be
   judged in both without changing system settings. Light is the default. */
export function Shell({ children }: { children: ReactNode }) {
  const [dark, setDark] = useState(false)
  return (
    <div
      className={`askwell ${paper} ${mono} relative h-full w-full overflow-auto text-[13px] leading-normal`}
      data-theme={dark ? 'dark' : 'light'}
    >
      <button
        onClick={() => setDark((v) => !v)}
        title="Askwell light / dark — not the lab's own theme"
        className="absolute right-2 top-2 z-50 rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)] px-2 py-1 text-[10px] uppercase tracking-[0.08em] text-[var(--ask-muted)] opacity-40 transition-opacity hover:opacity-100 focus-visible:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ask-provenance)]"
      >
        {dark ? 'dark' : 'light'}
      </button>
      {children}
    </div>
  )
}

export function Chrome({ right, label = 'Askwell' }: { right?: ReactNode; label?: string }) {
  return (
    <div className="flex items-center gap-3 border-b border-[var(--ask-rule)] bg-[var(--ask-sunk)] px-3 py-2">
      <span className="h-2 w-2 rounded-full bg-[var(--ask-rule)]" />
      <span className="text-[11px] uppercase tracking-[0.08em] text-[var(--ask-muted)]">{label}</span>
      <div className="ml-auto flex items-center gap-3">{right}</div>
    </div>
  )
}

export function Badge({ children, tone }: { children: ReactNode; tone?: 'prov' | 'inf' | 'alarm' }) {
  const c =
    tone === 'prov' ? 'text-[var(--ask-provenance)] border-[var(--ask-provenance)]'
    : tone === 'inf' ? 'text-[var(--ask-inferred)] border-[var(--ask-inferred)]'
    : tone === 'alarm' ? 'text-[var(--ask-alarm)] border-[var(--ask-alarm)]'
    : 'text-[var(--ask-muted)] border-[var(--ask-rule)]'
  return <span className={`rounded-[var(--ask-radius)] border px-1.5 py-0.5 text-[11px] ${c}`}>{children}</span>
}

/* ---------- left rail ---------- */

export type RailItem = { label: string; count?: string; live?: boolean; on?: boolean }

export function Rail({ groups }: { groups: { title: string; items: RailItem[] }[] }) {
  return (
    <nav className="flex w-[180px] shrink-0 flex-col gap-6 border-r border-[var(--ask-rule)] bg-[var(--ask-sunk)] px-3 py-4">
      {groups.map((g) => (
        <div key={g.title} className="flex flex-col gap-1">
          <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--ask-muted)]">{g.title}</div>
          {g.items.map((it) => (
            <div
              key={it.label}
              className={`flex items-center gap-2 rounded-[var(--ask-radius)] px-1 py-[3px] text-[13px] ${
                it.on ? 'bg-[var(--ask-surface)] outline outline-1 outline-[var(--ask-rule)]' : ''
              }`}
            >
              {it.label}
              {it.count && (
                <span className={`ml-auto text-[11px] ${it.live ? 'text-[var(--ask-inferred)]' : 'text-[var(--ask-muted)]'}`}>
                  {it.count}
                </span>
              )}
            </div>
          ))}
        </div>
      ))}
    </nav>
  )
}

export const railStd = [
  { title: 'Sources', items: [{ label: 'Contracts', count: '14' }, { label: 'Policies', count: '6' }, { label: 'sales-2024', count: 'db' }] },
  { title: 'Library', items: [{ label: 'Ask', on: true }, { label: 'Clarifications', count: '5', live: true }, { label: 'Memory', count: '23' }, { label: 'Settings' }] },
]
export function railWith(active: string) {
  return [
    railStd[0],
    { title: 'Library', items: railStd[1].items.map((i) => ({ ...i, on: i.label === active })) },
  ]
}

/* ---------- type ---------- */

export function Q({ children }: { children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-[11px] uppercase tracking-[0.08em] text-[var(--ask-muted)]">you asked</div>
      <div className={`${serif} max-w-[70ch] text-[17px] font-semibold leading-snug`}>{children}</div>
    </div>
  )
}

export function Prose({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <p className={`${serif} m-0 max-w-[var(--ask-measure)] text-[16px] leading-[1.62] ${className}`}>{children}</p>
}

export function H({ children }: { children: ReactNode }) {
  return <h3 className={`${serif} m-0 text-[20px] font-semibold`}>{children}</h3>
}

export function Meta({ children }: { children: ReactNode }) {
  return <div className="text-[12px] text-[var(--ask-muted)]">{children}</div>
}

export function Micro({ children }: { children: ReactNode }) {
  return <div className="text-[11px] uppercase tracking-[0.08em] text-[var(--ask-muted)]">{children}</div>
}

/* ---------- the signature: claim / leader / source card ---------- */

export function ClaimRow({ claim, card }: { claim: ReactNode; card: ReactNode }) {
  return (
    <div className="group grid grid-cols-[minmax(0,1fr)_28px_268px] items-start">
      <div>{claim}</div>
      <div className="mt-[13px] h-px bg-[var(--ask-rule)] transition-colors group-hover:bg-[var(--ask-provenance)]" />
      {card}
    </div>
  )
}

export function SourceCard({
  file, loc, quote, dead,
}: { file: string; loc: string; quote: string; dead?: boolean }) {
  return (
    <div
      className={`flex flex-col gap-1.5 rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)] p-3 transition-colors ${
        dead ? 'border-l-2 border-l-[var(--ask-rule)] opacity-60' : 'border-l-2 border-l-[var(--ask-provenance)] group-hover:border-[var(--ask-provenance)]'
      }`}
    >
      <div className={`break-all text-[12px] ${dead ? 'text-[var(--ask-muted)] line-through' : 'text-[var(--ask-provenance)]'}`}>{file}</div>
      <div className="text-[11px] uppercase tracking-[0.06em] text-[var(--ask-muted)]">{loc}</div>
      <div className={`${serif} border-t border-[var(--ask-rule)] pt-1.5 text-[13px] leading-snug`}>{quote}</div>
    </div>
  )
}

export function EmptyMargin({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[var(--ask-radius)] border border-dashed border-[var(--ask-rule)] p-3 text-center text-[12px] text-[var(--ask-muted)]">
      {children}
    </div>
  )
}

/* ---------- confidence marker: fill differs as well as hue (a11y §8) ---------- */

export function Mark({ known }: { known?: boolean }) {
  return (
    <span
      className={`inline-block h-1.5 w-1.5 shrink-0 ${
        known ? 'bg-[var(--ask-provenance)]' : 'border border-[var(--ask-inferred)] bg-transparent'
      }`}
    />
  )
}

export function Chip({ children, known }: { children: ReactNode; known?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)] px-2 py-[3px] text-[12px]">
      <Mark known={known} />
      {children}
    </span>
  )
}

/* ---------- controls ---------- */

export function Btn({
  children, primary, alarm, sm,
}: { children: ReactNode; primary?: boolean; alarm?: boolean; sm?: boolean }) {
  const tone = primary
    ? 'border-[var(--ask-provenance)] text-[var(--ask-provenance)]'
    : alarm ? 'border-[var(--ask-alarm)] text-[var(--ask-alarm)]'
    : 'border-[var(--ask-ink)] text-[var(--ask-ink)]'
  return (
    <button
      className={`${mono} rounded-[var(--ask-radius)] border bg-transparent ${tone} ${
        sm ? 'min-h-[32px] px-3 py-1.5 text-[12.5px]' : 'min-h-[36px] px-3.5 py-2 text-[13px]'
      } focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ask-provenance)]`}
    >
      {children}
    </button>
  )
}

export function Field({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)] px-2.5 py-2 text-[13px] text-[var(--ask-muted)]">
      {children}
    </div>
  )
}

export function Composer() {
  return (
    <div className="flex items-center gap-3 border-t border-[var(--ask-rule)] bg-[var(--ask-sunk)] px-6 py-3">
      <div className="flex-1"><Field>Ask about your files…</Field></div>
      <Btn sm>Ask</Btn>
    </div>
  )
}

/* ---------- layout helpers ---------- */

export function Split({ children }: { children: ReactNode }) {
  return <div className="grid min-h-0 flex-1 grid-cols-[180px_1fr]">{children}</div>
}

export function Main({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`flex min-w-0 flex-col gap-6 p-6 ${className}`}>{children}</div>
}

export function Steps({ items }: { items: string[] }) {
  return (
    <div className="flex flex-wrap gap-2 text-[12px] text-[var(--ask-muted)]">
      {items.map((s, i) => (
        <span key={s} className="inline-flex items-center gap-1.5">
          {i > 0 && <span className="text-[var(--ask-rule)]">·</span>}
          {s}
        </span>
      ))}
    </div>
  )
}

export function Panel({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)] p-4">
      {title && <div className="mb-3 text-[11px] uppercase tracking-[0.08em] text-[var(--ask-muted)]">{title}</div>}
      {children}
    </div>
  )
}

export function Row({ k, v, tone }: { k: ReactNode; v: ReactNode; tone?: 'prov' | 'inf' | 'alarm' }) {
  const c = tone === 'prov' ? 'text-[var(--ask-provenance)]' : tone === 'inf' ? 'text-[var(--ask-inferred)]' : tone === 'alarm' ? 'text-[var(--ask-alarm)]' : ''
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-[var(--ask-rule)] py-2 last:border-0">
      <span className="text-[13px]">{k}</span>
      <span className={`text-right text-[12.5px] ${c || 'text-[var(--ask-muted)]'}`}>{v}</span>
    </div>
  )
}

export function Bar({ pct, tone }: { pct: number; tone?: 'inf' | 'alarm' }) {
  const c = tone === 'inf' ? 'bg-[var(--ask-inferred)]' : tone === 'alarm' ? 'bg-[var(--ask-alarm)]' : 'bg-[var(--ask-provenance)]'
  return (
    <div className="h-1 w-full overflow-hidden rounded-[var(--ask-radius)] bg-[var(--ask-rule)]">
      <div className={`h-full ${c}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[12.5px]">
        <thead>
          <tr>{head.map((h) => (
            <th key={h} className="border-b border-[var(--ask-rule)] px-2 py-1.5 text-left text-[11px] uppercase tracking-[0.06em] font-normal text-[var(--ask-muted)]">{h}</th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{r.map((c, j) => (
              <td key={j} className="border-b border-[var(--ask-rule)] px-2 py-1.5 align-top tabular-nums">{c}</td>
            ))}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Sql({ children, note }: { children: ReactNode; note?: string }) {
  return (
    <div className="rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-sunk)]">
      <div className="px-3 py-2 text-[12px] text-[var(--ask-provenance)]">▾ the query that produced this</div>
      <pre className="m-0 overflow-x-auto px-3 pb-3 text-[12.5px] leading-[1.6]">{children}
        {note && <span className="text-[var(--ask-inferred)]">{'\n'}{note}</span>}
      </pre>
    </div>
  )
}
