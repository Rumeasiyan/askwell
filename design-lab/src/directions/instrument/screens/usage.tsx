import { Shell, Chrome, Split, Rail, Main, H, Micro, Badge, Panel, Bar, Prose, Btn, Table, railWith } from '../ui'

export default function Usage() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Settings')} />
        <Main>
          <div className="flex flex-wrap items-baseline gap-3">
            <H>How it's going</H>
            <Micro>computed here, on this machine · nothing is sent anywhere</Micro>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <Panel title="didn’t know — 12%">
              <div className="mb-2"><Bar pct={12} /></div>
              <div className="flex justify-between text-[11px] text-[var(--ask-muted)]">
                <span>0%</span><span className="text-[var(--ask-provenance)]">healthy band 5–20%</span><span>40%</span>
              </div>
              <Prose className="mt-3 text-[14px] text-[var(--ask-muted)]">
                Inside the healthy band. Below 5% would be suspicious rather than good — it usually means the threshold
                has been lowered and Askwell has started guessing.
              </Prose>
            </Panel>

            <Panel title="claims traced to a source — 100%">
              <div className="mb-2"><Bar pct={100} /></div>
              <div className="flex justify-between text-[11px] text-[var(--ask-muted)]">
                <span>sampled 40 answers</span><span className="text-[var(--ask-provenance)]">target 100%</span>
              </div>
              <Prose className="mt-3 text-[14px] text-[var(--ask-muted)]">
                Read alongside the number on the left, never on its own. Both falling together is the pattern that
                matters, and either one alone looks fine.
              </Prose>
            </Panel>
          </div>

          <Panel title="asked and not found — this is what to add next">
            <Table
              head={['question', 'asked', 'closest match']}
              rows={[
                ['professional indemnity excess', '4 times', 'insurance-schedule-2023.pdf · 0.61'],
                ['current travel expense limit', '3 times', 'nothing above 0.4'],
                ['who signed the Harlow amendment', '2 times', 'harlow-msa.pdf · 0.58'],
              ]}
            />
            <div className="mt-3"><Btn sm>Add a source</Btn></div>
          </Panel>

          <div className="grid gap-3 md:grid-cols-3">
            <Panel title="questions this week"><div className="text-[20px] tabular-nums">37</div></Panel>
            <Panel title="typical answer"><div className="text-[20px] tabular-nums">14s</div></Panel>
            <Panel title="facts remembered"><div className="text-[20px] tabular-nums">23</div></Panel>
          </div>
        </Main>
      </Split>
    </Shell>
  )
}
