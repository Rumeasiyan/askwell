import { Shell, Chrome, Split, Rail, Main, Composer, Q, Prose, Micro, Btn, Badge, EmptyMargin, railWith } from '../ui'

export default function AskClarifyInline() {
  return (
    <Shell>
      <Chrome right={<Badge>local · Qwen3.5 9B</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Q>How many invoices were raised in March?</Q>

          <div className="grid grid-cols-[minmax(0,1fr)_28px_268px] items-start">
            <div className="flex max-w-[var(--ask-measure)] flex-col gap-3 rounded-[var(--ask-radius)] border border-[var(--ask-inferred)] bg-[var(--ask-surface)] p-4">
              <Micro>I need one thing before I can answer</Micro>
              <Prose className="text-[17px] font-semibold">
                Is 03/04/2026 the 3rd of April, or the 4th of March?
              </Prose>
              <div className="text-[12.5px] tabular-nums text-[var(--ask-muted)]">
                1,240 dates in <span className="text-[var(--ask-ink)]">invoices.issued_on</span> are ambiguous · nothing in the data settles it
              </div>
              <Prose className="text-[14px] text-[var(--ask-muted)]">
                Guessing here would move your answer by up to eleven months, so I will not infer it.
              </Prose>
              <div className="flex flex-wrap gap-3 pt-1">
                <Btn primary sm>Day first — 3 April</Btn>
                <Btn sm>Month first — 4 March</Btn>
              </div>
              <Micro>I will remember this for every file from this source</Micro>
            </div>
            <div />
            <EmptyMargin>answer pending<br />your reply</EmptyMargin>
          </div>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
