import { Shell, Chrome, Split, Rail, Main, H, Micro, Badge, Prose, Btn, railWith } from '../ui'

function Step({ n, title, ms, detail, expand }: any) {
  return (
    <div className="grid grid-cols-[22px_minmax(0,1fr)_auto] items-baseline gap-x-3 border-b border-[var(--ask-rule)] py-3 last:border-0">
      <span className="text-[12px] tabular-nums text-[var(--ask-muted)]">{n}</span>
      <span className="text-[13px]">{title}</span>
      <span className="text-[12px] tabular-nums text-[var(--ask-muted)]">{ms}</span>
      <span />
      <div className="col-span-2 mt-1 flex flex-col gap-1">
        <span className="text-[12.5px] text-[var(--ask-muted)]">{detail}</span>
        {expand && <span className="text-[12px] text-[var(--ask-provenance)]">▸ {expand}</span>}
      </div>
    </div>
  )
}

export default function Trace() {
  return (
    <Shell>
      <Chrome right={<Badge>local · Qwen3.5 9B</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <div className="flex flex-wrap items-baseline gap-3">
            <H>How did you get this?</H>
            <Micro>8.9 seconds total · 4 steps · 3 claims, all cited</Micro>
            <div className="ml-auto"><Btn sm>Copy trace</Btn></div>
          </div>

          <div className="rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)] px-4">
            <Step n="1" title="Searched your files" ms="340 ms"
              detail={<>“Meridian payment terms” → 8 passages, best 0.81, threshold 0.65</>}
              expand="show all 8 with scores" />
            <Step n="2" title="Read 2 documents" ms="120 ms"
              detail="supplier-agreement-2024.pdf p.14 · procurement-policy-v3.docx p.6"
              expand="show retrieved text" />
            <Step n="3" title="Looked up schema" ms="40 ms"
              detail={<>invoices · used your note on <span className="text-[var(--ask-provenance)]">st_cd</span></>}
              expand="show what the model was given" />
            <Step n="4" title="Queried sales-2024" ms="240 ms"
              detail={<>7 rows · <span className="text-[var(--ask-inferred)]">LIMIT 1000 added by Askwell</span> · validation passed</>}
              expand="show query and validation" />
            <Step n="5" title="Wrote the answer" ms="8.2 s" detail="3 claims, all cited" />
          </div>

          <div className="rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-sunk)] p-4">
            <Micro>retrieved passages</Micro>
            <div className="mt-2 flex flex-col gap-2">
              {[['0.81', 'supplier-agreement-2024.pdf p.14', true],
                ['0.74', 'procurement-policy-v3.docx p.6', true],
                ['0.68', 'supplier-handbook-2024.pdf p.11', true],
                ['0.61', 'meeting-notes-2025-03.md', false],
                ['0.54', 'insurance-schedule-2023.pdf p.2', false]].map(([s, f, used]: any) => (
                <div key={f} className="flex items-baseline gap-3 text-[12.5px]">
                  <span className={`w-10 tabular-nums ${used ? 'text-[var(--ask-provenance)]' : 'text-[var(--ask-muted)]'}`}>{s}</span>
                  <span className={used ? '' : 'text-[var(--ask-muted)]'}>{f}</span>
                  <span className="ml-auto text-[11px] text-[var(--ask-muted)]">{used ? 'used' : 'below threshold'}</span>
                </div>
              ))}
            </div>
          </div>

          <Prose className="text-[14px] text-[var(--ask-muted)]">
            Scores and the threshold are stored as they were at the time, not recalculated — so this still explains the
            answer after you change either.
          </Prose>
        </Main>
      </Split>
    </Shell>
  )
}
