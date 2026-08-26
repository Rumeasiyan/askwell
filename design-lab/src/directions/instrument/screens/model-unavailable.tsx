import { Shell, Chrome, Split, Rail, Main, H, Prose, Micro, Btn, Badge, Panel, Field, railWith } from '../ui'

export default function ModelUnavailable() {
  return (
    <Shell>
      <Chrome right={<Badge tone="alarm">assistant unavailable</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <H>The assistant isn't running.</H>
          <Prose>
            Askwell can't answer questions right now. Everything else still works — your sources are indexed and you can
            search them directly while this is sorted out.
          </Prose>

          <Panel title="what happened">
            <Prose className="text-[14.5px]">
              The model process stopped shortly after starting. This usually means the machine ran out of memory for the
              model that is currently selected.
            </Prose>
            <div className="mt-3 flex flex-wrap gap-3">
              <Btn primary sm>Start it again</Btn>
              <Btn sm>Switch to a smaller model</Btn>
              <Btn sm>See the details</Btn>
            </div>
          </Panel>

          <div className="flex flex-col gap-2 border-t border-[var(--ask-rule)] pt-4">
            <Micro>meanwhile — search your sources directly</Micro>
            <div className="max-w-[420px]"><Field>Search 38 documents and 2 databases…</Field></div>
            <Prose className="text-[14px] text-[var(--ask-muted)]">
              Plain search, no assistant. It finds passages rather than writing an answer, and every result still points
              at its source.
            </Prose>
          </div>
        </Main>
      </Split>
    </Shell>
  )
}
