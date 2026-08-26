import { Shell, Chrome, Split, Rail, Main, H, Micro, Btn, Badge, Panel, Prose, Row, railWith } from '../ui'

export default function SettingsData() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Settings')} />
        <Main>
          <H>Your data</H>
          <Prose className="text-[15px] text-[var(--ask-muted)]">
            All of it is yours and none of it is locked in. Everything below writes open formats you can read without
            Askwell.
          </Prose>

          <Panel title="take it with you">
            <Row k="Everything" v="sources list, memory, questions, answers, log" />
            <Row k="Just the log" v="with its verification file" />
            <Row k="Backup" v="restorable onto a different machine" />
            <div className="mt-3 flex flex-wrap gap-3">
              <Btn sm>Export everything</Btn><Btn sm>Export the log</Btn><Btn sm>Back up</Btn>
            </div>
            <Micro>large exports run in the background — you can keep working</Micro>
          </Panel>

          <Panel title="check the log has not been altered">
            <Prose className="text-[14.5px]">
              Each entry is sealed against the one before it. If anything outside Askwell has edited or removed a record,
              this check finds exactly where.
            </Prose>
            <Prose className="mt-2 text-[14px] text-[var(--ask-muted)]">
              Askwell never rewrites its own history, and tampering is detectable. It is not immutable — you own this
              machine and can always delete a file. That is the honest version.
            </Prose>
            <div className="mt-3"><Btn sm>Verify the log</Btn></div>
          </Panel>

          <Panel title="remove things">
            <Row k="Delete a source" v="contents forgotten, old answers still say where they came from" />
            <Row k="Delete all memory" v="23 facts · cannot be undone" />
            <Row k="Reset Askwell" v="everything Askwell holds" />
            <Prose className="mt-2 text-[14px] text-[var(--ask-muted)]">
              None of this touches your original files. Askwell only ever forgets its own copy of what it read.
            </Prose>
            <div className="mt-3 flex flex-wrap gap-3">
              <Btn sm>Delete all memory</Btn><Btn alarm sm>Reset Askwell</Btn>
            </div>
          </Panel>
        </Main>
      </Split>
    </Shell>
  )
}
