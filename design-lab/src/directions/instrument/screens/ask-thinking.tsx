import { Shell, Chrome, Split, Rail, Main, Composer, Q, Prose, Badge, Bar, EmptyMargin, railWith } from '../ui'

export default function AskThinking() {
  const steps = [
    { label: 'searching your files', done: true, detail: '1,240 passages' },
    { label: 'reading 4 sources', done: true, detail: 'top score 0.81' },
    { label: 'querying sales-2024', done: false, detail: 'running…' },
    { label: 'writing the answer', done: false, detail: '' },
  ]
  return (
    <Shell>
      <Chrome right={<Badge>local · Qwen3.5 4B</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Q>Which suppliers are past their agreed payment terms right now?</Q>

          <div className="grid grid-cols-1 items-start gap-3 @3xl:grid-cols-[minmax(0,1fr)_28px_268px] @3xl:gap-0">
            <div className="flex max-w-[var(--ask-measure)] flex-col gap-3">
              {steps.map((s) => (
                <div key={s.label} className="flex items-baseline gap-3">
                  <span className={`w-1.5 shrink-0 text-[11px] ${s.done ? 'text-[var(--ask-provenance)]' : 'text-[var(--ask-rule)]'}`}>
                    {s.done ? '▪' : '▫'}
                  </span>
                  <span className={`text-[13px] ${s.done ? '' : 'text-[var(--ask-muted)]'}`}>{s.label}</span>
                  <span className="ml-auto text-[12px] text-[var(--ask-muted)]">{s.detail}</span>
                </div>
              ))}
              <div className="mt-1"><Bar pct={62} /></div>
              <Prose className="text-[var(--ask-muted)] text-[15px]">
                Answers take about fifteen seconds on this machine. The steps keep moving so you can tell working from hung.
              </Prose>
            </div>
            <div />
            <EmptyMargin>sources appear here<br />as claims are cited</EmptyMargin>
          </div>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
