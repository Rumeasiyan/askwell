import { Shell, Chrome, Split, Rail, Main, H, Micro, Btn, Badge, Panel, Prose, Row, railWith } from '../ui'

export default function SettingsOnline() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Settings')} />
        <Main>
          <div className="flex flex-wrap items-baseline gap-3">
            <H>Online AI</H>
            <Badge>off</Badge>
          </div>

          <Prose>
            Askwell runs entirely on this machine. If you ever want a larger cloud model for a hard question, you can buy
            credits and turn this on for a single conversation at a time.
          </Prose>

          <Panel title="what would leave this machine">
            <Prose className="text-[14.5px]">
              Your question, and the passages Askwell retrieved to answer it. Nothing else — not your other files, not
              your database, not your memory of past answers.
            </Prose>
            <Prose className="mt-2 text-[14.5px] text-[var(--ask-muted)]">
              You will see exactly this, again, before anything is sent for the first time in a conversation.
            </Prose>
          </Panel>

          <Panel title="credits">
            <Row k="Balance" v="none" />
            <Row k="Spending limit" v="not set" />
            <Prose className="mt-2 text-[14px] text-[var(--ask-muted)]">
              Bought from us, not from a provider. You never hand Askwell an API key, and a limit you set means a bad
              afternoon cannot produce a surprise bill.
            </Prose>
            <div className="mt-3 flex gap-3"><Btn sm>Buy credits</Btn><Btn sm>Set a limit</Btn></div>
          </Panel>

          <div className="rounded-[var(--ask-radius)] border border-dashed border-[var(--ask-rule)] p-4">
            <Micro>not built yet</Micro>
            <Prose className="mt-1 text-[14px] text-[var(--ask-muted)]">
              This is the last thing Askwell will add, and everything before it is free. It is shown now, switched off, so
              you know it is coming rather than finding it appear one day.
            </Prose>
          </div>
        </Main>
      </Split>
    </Shell>
  )
}
