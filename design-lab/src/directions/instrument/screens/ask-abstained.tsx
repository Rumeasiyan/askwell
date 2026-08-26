import { Shell, Chrome, Split, Rail, Main, Composer, Q, H, Prose, Btn, EmptyMargin, Badge, railWith } from '../ui'

export default function AskAbstained() {
  return (
    <Shell>
      <Chrome right={<Badge>local · Qwen3.5 9B</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Q>What is our current professional indemnity excess?</Q>

          <div className="grid grid-cols-1 items-start gap-3 @3xl:grid-cols-[minmax(0,1fr)_28px_268px] @3xl:gap-0">
            <div className="flex flex-col gap-3 py-6">
              <H>Nothing in your files answers this.</H>
              <Prose>
                I searched 1,240 passages across 38 documents and 2 databases. The closest material was{' '}
                <strong>public liability cover</strong> in <em>insurance-schedule-2023.pdf</em>, which does not mention
                professional indemnity.
              </Prose>
              <Prose className="text-[15px] text-[var(--ask-muted)]">
                Add the policy document you'd expect this in, and ask again.
              </Prose>
              <div className="flex flex-wrap gap-3 pt-1">
                <Btn primary to="add-source">Add a source</Btn>
                <Btn to="ask-escalate">Look outside my files</Btn>
              </div>
            </div>
            <div />
            <EmptyMargin>No sources —<br />nothing matched</EmptyMargin>
          </div>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
