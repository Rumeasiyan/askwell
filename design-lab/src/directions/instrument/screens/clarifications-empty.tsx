import { Shell, Chrome, Split, Rail, Main, H, Prose, Micro, Badge, Panel, railWith } from '../ui'

export default function ClarificationsEmpty() {
  return (
    <Shell>
      <Chrome right={<Badge>nothing pending</Badge>} />
      <Split>
        <Rail groups={railWith('Clarifications')} />
        <Main className="justify-center">
          <div className="flex max-w-[var(--measure)] flex-col gap-4 py-8">
            <H>Nothing to clarify.</H>
            <Prose>
              Askwell asks when it finds something it genuinely cannot work out — an unlabelled column, a date format
              that could go either way, two documents that disagree, a scan it could barely read.
            </Prose>
            <Prose className="text-[15px] text-[var(--muted)]">
              It asks about five things per source at most, and only when your answer would change future results.
            </Prose>

            <Panel title="last session">
              <div className="flex flex-col gap-1.5 text-[13px]">
                <span>5 answered · 2 tables and 14 documents re-read</span>
                <span className="text-[var(--muted)]">23 facts remembered so far</span>
              </div>
            </Panel>
            <Micro>a count in the sidebar is the only prompt you will get — there is no nagging</Micro>
          </div>
        </Main>
      </Split>
    </Shell>
  )
}
