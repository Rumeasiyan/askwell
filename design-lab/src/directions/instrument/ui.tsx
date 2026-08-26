/* Shared primitives for the "instrument" direction.
   Every visual value binds to a token in src/tokens.css — no hardcoded hex, radius or font.
   See ../../../docs/ux/design-system.md; that document is the source of truth. */
import type { ReactNode } from 'react'
import { go } from '../../lib/nav'
import { usePanelOpen, setPanelOpen, togglePanel } from '../../lib/panel'

export const paper = 'bg-[var(--ask-paper)] text-[var(--ask-ink)]'
export const mono = 'font-[var(--ask-font-app)]'
export const serif = 'font-[var(--ask-font-text)]'

/* ---------- shell ---------- */

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className={`askwell ${paper} ${mono} flex h-full w-full flex-col overflow-hidden text-[13px] leading-normal`}>
      {children}
    </div>
  )
}

export function Chrome({ right, label = 'Askwell' }: { right?: ReactNode; label?: string }) {
  return (
    <div className="flex shrink-0 items-center gap-3 border-b border-[var(--ask-rule)] bg-[var(--ask-sunk)] px-3 py-2">
      <button
        onClick={togglePanel}
        aria-label="Open sources and library"
        title="Sources and library"
        className="-ml-1 flex h-7 w-7 cursor-pointer items-center justify-center rounded-[var(--ask-radius)] text-[var(--ask-muted)] hover:bg-[var(--ask-paper)] hover:text-[var(--ask-ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ask-provenance)] @2xl:hidden"
      >
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M2 4h12M2 8h12M2 12h12" />
        </svg>
      </button>
      <span className="h-2 w-2 rounded-full bg-[var(--ask-rule)] max-@2xl:hidden" />
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

export type RailItem = { label: string; count?: string; live?: boolean; on?: boolean; to?: string }

export function Rail({ groups }: { groups: { title: string; items: RailItem[] }[] }) {
  const open = usePanelOpen()
  return (
    <>
      {/* below the breakpoint the rail becomes a drawer. It is reachable, not removed —
          the library is the only route to sources, memory and settings. */}
      {open && (
        <button
          aria-label="Close panel"
          onClick={() => setPanelOpen(false)}
          className="absolute inset-0 z-30 cursor-default bg-[var(--ask-ink)]/25 @2xl:hidden"
        />
      )}
      <nav
        className={`w-[180px] shrink-0 flex-col gap-6 overflow-y-auto border-r border-[var(--ask-rule)] bg-[var(--ask-sunk)] px-3 py-4 @2xl:flex ${
          open ? 'absolute inset-y-0 left-0 z-40 flex shadow-[2px_0_8px_var(--ask-drop)] @2xl:static @2xl:shadow-none' : 'hidden'
        }`}
      >
      {groups.map((g) => (
        <div key={g.title} className="flex flex-col gap-1">
          <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--ask-muted)]">{g.title}</div>
          {g.items.map((it) => (
            <button
              key={it.label}
              onClick={() => { setPanelOpen(false); if (it.to) go(it.to) }}
              className={`flex w-full items-center gap-2 rounded-[var(--ask-radius)] px-2 py-[5px] text-left text-[13px] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ask-provenance)] ${
                it.on
                  ? 'bg-[var(--ask-paper)] font-medium shadow-[inset_2px_0_0_var(--ask-provenance)]'
                  : 'hover:bg-[var(--ask-paper)]/60'
              }`}
            >
              {it.label}
              {it.count && (
                <span className={`ml-auto text-[11px] tabular-nums ${it.live ? 'text-[var(--ask-inferred)]' : 'text-[var(--ask-muted)]'}`}>
                  {it.count}
                </span>
              )}
            </button>
          ))}
        </div>
      ))}
      </nav>
    </>
  )
}

export const railStd: { title: string; items: RailItem[] }[] = [
  {
    title: 'Sources',
    items: [
      { label: 'Contracts', count: '14', to: 'library' },
      { label: 'Policies', count: '6', to: 'library' },
      { label: 'sales-2024', count: 'db', to: 'library' },
      { label: 'All sources', to: 'library' },
      { label: '+ Add a source', to: 'add-source' },
    ],
  },
  {
    title: 'Library',
    items: [
      { label: 'Ask', on: true, to: 'ask-answered' },
      { label: 'History', to: 'conversations' },
      { label: 'Clarifications', count: '5', live: true, to: 'clarifications' },
      { label: 'Memory', count: '23', to: 'memory' },
      { label: 'Settings', to: 'settings-model' },
    ],
  },
]
/* Marks whichever item matches, in either group. Passing a label that exists in neither
   marks nothing — correct for screens reached from outside the rail. */
export function railWith(active: string) {
  return railStd.map((g) => ({
    ...g,
    items: g.items.map((i) => ({ ...i, on: i.label === active })),
  }))
}

/* ---------- type ---------- */

/* A past turn: collapsed to its question and a one-line summary of what answered it, so a
   long conversation stays scannable. Expanding restores the full answer with its margin. */
export function PastTurn({ q, summary, sources }: { q: string; summary: string; sources: string }) {
  return (
    <button className="group flex w-full cursor-pointer flex-col gap-1 rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)]/60 px-3 py-2 text-left transition-colors hover:bg-[var(--ask-surface)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ask-provenance)]">
      <div className="flex items-baseline gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-[var(--ask-muted)]">asked</span>
        <span className={`${serif} min-w-0 flex-1 truncate text-[14px]`}>{q}</span>
        <span className="text-[11px] text-[var(--ask-muted)] opacity-0 transition-opacity group-hover:opacity-100">expand ▾</span>
      </div>
      <div className="flex items-baseline gap-2 pl-1">
        <span className={`${serif} min-w-0 flex-1 truncate text-[13px] text-[var(--ask-muted)]`}>{summary}</span>
        <span className="shrink-0 text-[11px] text-[var(--ask-provenance)]">{sources}</span>
      </div>
    </button>
  )
}

export function TurnDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-1">
      <span className="h-px flex-1 bg-[var(--ask-rule)]" />
      <span className="text-[10px] uppercase tracking-[0.08em] text-[var(--ask-muted)]">{label}</span>
      <span className="h-px flex-1 bg-[var(--ask-rule)]" />
    </div>
  )
}

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
    <div className="group grid grid-cols-1 items-start gap-3 @3xl:grid-cols-[minmax(0,1fr)_28px_268px] @3xl:gap-0">
      <div>{claim}</div>
      {/* leader is the desktop affordance; below the breakpoint the card sits inline under
          the claim it supports. It is never removed — citations are not conditional on width. */}
      <div className="mt-[13px] hidden h-px bg-[var(--ask-rule-strong)] transition-colors group-hover:bg-[var(--ask-provenance)] @3xl:block" />
      <div className="border-l-2 border-l-[var(--ask-rule-strong)] pl-3 @3xl:border-l-0 @3xl:pl-0">{card}</div>
    </div>
  )
}

export function SourceCard({
  file, loc, quote, dead,
}: { file: string; loc: string; quote: string; dead?: boolean }) {
  return (
    <button
      onClick={() => !dead && go(dead ? 'source-missing' : 'source-viewer')}
      disabled={dead}
      className={`flex w-full flex-col gap-1.5 rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)] p-3 text-left shadow-[0_1px_0_var(--ask-rule)] transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ask-provenance)] ${
        dead
          ? 'cursor-not-allowed border-l-2 border-l-[var(--ask-rule)] opacity-60'
          : 'cursor-pointer border-l-2 border-l-[var(--ask-provenance)] hover:-translate-y-px hover:border-[var(--ask-provenance)] hover:shadow-[0_2px_0_var(--ask-rule)] group-hover:border-[var(--ask-provenance)]'
      }`}
    >
      <div className={`break-words text-[12px] ${dead ? 'text-[var(--ask-muted)] line-through' : 'text-[var(--ask-provenance)]'}`}>{file}</div>
      <div className="text-[11px] uppercase tracking-[0.06em] text-[var(--ask-muted)]">{loc}</div>
      <div className={`${serif} border-t border-[var(--ask-rule)] pt-1.5 text-[13px] leading-snug`}>{quote}</div>
      {!dead && (
        <div className="text-[10px] uppercase tracking-[0.08em] text-[var(--ask-muted)] opacity-0 transition-opacity group-hover:opacity-100">
          open at this page ▸
        </div>
      )}
    </button>
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
  children, primary, alarm, sm, to, onClick,
}: {
  children: ReactNode; primary?: boolean; alarm?: boolean; sm?: boolean
  to?: string; onClick?: () => void
}) {
  const tone = primary
    ? 'border-[var(--ask-provenance)] bg-[var(--ask-provenance)] text-[var(--ask-paper)] hover:brightness-110'
    : alarm
      ? 'border-[var(--ask-alarm)] bg-transparent text-[var(--ask-alarm)] hover:bg-[var(--ask-alarm)]/10'
      : 'border-[var(--ask-rule)] bg-[var(--ask-paper)] text-[var(--ask-ink)] hover:border-[var(--ask-ink)] hover:bg-[var(--ask-surface)]'
  return (
    <button
      onClick={() => { onClick?.(); if (to) go(to) }}
      className={`${mono} cursor-pointer rounded-[var(--ask-radius)] border transition-all active:translate-y-px ${tone} ${
        sm ? 'min-h-[32px] px-3 py-1.5 text-[12.5px]' : 'min-h-[36px] px-3.5 py-2 text-[13px]'
      } focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ask-provenance)]`}
    >
      {children}
    </button>
  )
}

export function Field({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-paper)] px-2.5 py-2 text-[13px] text-[var(--ask-muted)] shadow-[inset_0_1px_2px_var(--ask-inset)]">
      {children}
    </div>
  )
}

/* Simple glyphs rather than an icon font — nothing is fetched at runtime (C1). */
export function MicIcon({ on }: { on?: boolean }) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden fill="none"
      stroke={on ? 'var(--ask-paper)' : 'currentColor'} strokeWidth="1.4" strokeLinecap="round">
      <rect x="6" y="2" width="4" height="7" rx="2" />
      <path d="M3.5 7.5a4.5 4.5 0 0 0 9 0M8 12v2" />
    </svg>
  )
}

export function Composer({ voice }: { voice?: boolean }) {
  return (
    <div className="flex shrink-0 items-center gap-2 border-t border-[var(--ask-rule)] bg-[var(--ask-sunk)] px-4 py-3 @2xl:px-6">
      <button
        onClick={() => go('voice')}
        title="Ask out loud"
        aria-label="Ask out loud"
        className={`flex h-[34px] w-[34px] shrink-0 cursor-pointer items-center justify-center rounded-[var(--ask-radius)] border transition-all active:translate-y-px focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ask-provenance)] ${
          voice
            ? 'border-[var(--ask-provenance)] bg-[var(--ask-provenance)] text-[var(--ask-paper)]'
            : 'border-[var(--ask-rule)] bg-[var(--ask-paper)] text-[var(--ask-muted)] hover:border-[var(--ask-ink)] hover:text-[var(--ask-ink)]'
        }`}
      >
        <MicIcon on={voice} />
      </button>
      <div className="flex-1"><Field>Ask about your files…</Field></div>
      <Btn primary sm>Ask</Btn>
    </div>
  )
}

/* ---------- layout helpers ---------- */

export function Split({ children }: { children: ReactNode }) {
  return <div className="relative flex min-h-0 flex-1">{children}</div>
}

export function Main({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex min-w-0 flex-1 flex-col gap-5 overflow-x-hidden overflow-y-auto p-4 @2xl:gap-6 @2xl:p-6 ${className}`}>
      {children}
    </div>
  )
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
    <div className="rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)] p-3 @2xl:p-4">
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
    <div className="overflow-x-auto rounded-[var(--ask-radius)] border border-[var(--ask-rule)]">
      <table className="w-full min-w-[520px] border-collapse text-[12.5px]">
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
      <button onClick={() => go('trace')} className="w-full cursor-pointer px-3 py-2 text-left text-[12px] text-[var(--ask-provenance)] hover:underline">
        ▾ the query that produced this
      </button>
      <pre className="m-0 overflow-x-auto px-3 pb-3 text-[12.5px] leading-[1.6]">{children}
        {note && <span className="text-[var(--ask-inferred)]">{'\n'}{note}</span>}
      </pre>
    </div>
  )
}
