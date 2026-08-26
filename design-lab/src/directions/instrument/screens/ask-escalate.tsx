import { Shell, Chrome, Split, Rail, Main, Composer, Q, H, Prose, Btn, Micro, Badge, EmptyMargin, Panel, railWith } from '../ui'

export default function AskEscalate() {
  return (
    <Shell>
      <Chrome right={<Badge>local · Qwen3.5 9B</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Q>What is the standard notice period for a UK commercial lease?</Q>

          <div className="grid grid-cols-1 items-start gap-3 @3xl:grid-cols-[minmax(0,1fr)_28px_268px] @3xl:gap-0">
            <div className="flex flex-col gap-3 py-4">
              <H>Nothing in your files answers this.</H>
              <Prose>
                I searched 1,240 passages across 38 documents and 2 databases. Your leases are all specific
                agreements — none of them states what is standard generally.
              </Prose>
              <Prose className="text-[15px] text-[var(--ask-muted)]">
                This looks like a general question rather than one about your material. I have not gone looking.
              </Prose>
            </div>
            <div />
            <EmptyMargin>No sources —<br />nothing matched</EmptyMargin>
          </div>

          <Panel title="if you want, I can look further">
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <Btn primary sm to="ask-web-answer">Search the web</Btn>
                <span className="text-[12.5px] text-[var(--ask-muted)]">sends your question out · this question only</span>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Btn sm>Ask a larger model</Btn>
                <span className="text-[12.5px] text-[var(--ask-muted)]">uses credits · you have none</span>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Btn sm to="add-source">Add a source instead</Btn>
                <span className="text-[12.5px] text-[var(--ask-muted)]">keeps the answer in your own material</span>
              </div>
            </div>
          </Panel>

          <Micro>Askwell never searches on its own — not when retrieval is thin, not when an answer looks unhelpful</Micro>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
