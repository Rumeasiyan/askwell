import { Shell, Chrome, Main, H, Prose, Micro, Btn, Badge } from '../ui'

const steps = [
  { n: '1', t: 'What this is', s: 'done' },
  { n: '2', t: 'Check this machine', s: 'done' },
  { n: '3', t: 'Get the model', s: 'now' },
  { n: '4', t: 'Add something and ask', s: 'next' },
]

export default function FirstRun() {
  return (
    <Shell>
      <Chrome right={<Badge>first run</Badge>} />
      <div className="mx-auto flex max-w-[720px] flex-col">
        <Main>
          <div className="flex gap-6 border-b border-[var(--rule)] pb-4">
            {steps.map((s) => (
              <div key={s.n} className="flex items-baseline gap-2">
                <span className={`text-[11px] tabular-nums ${s.s === 'now' ? 'text-[var(--provenance)]' : 'text-[var(--muted)]'}`}>{s.n}</span>
                <span className={`text-[12.5px] ${s.s === 'next' ? 'text-[var(--muted)]' : s.s === 'now' ? '' : 'text-[var(--muted)] line-through'}`}>{s.t}</span>
              </div>
            ))}
          </div>

          <H>Askwell reads your own files and answers questions about them.</H>
          <Prose>
            Point it at documents, spreadsheets, a database dump or a database you already run. It reads them here, on
            this machine. Nothing is uploaded, and there is no account.
          </Prose>
          <Prose>
            When it finds something it genuinely cannot work out — an unlabelled column, a date that could go two ways,
            two documents that disagree — it asks you, and remembers what you say.
          </Prose>
          <Prose className="text-[15px] text-[var(--muted)]">
            Two things worth knowing now: it works with no internet connection, and it reads your files where they are
            rather than copying them into a library of its own.
          </Prose>

          <div className="flex flex-wrap gap-3 pt-2">
            <Btn primary>Continue</Btn>
            <Btn>Skip setup</Btn>
          </div>
          <Micro>everything here is reachable later from Settings</Micro>
        </Main>
      </div>
    </Shell>
  )
}
