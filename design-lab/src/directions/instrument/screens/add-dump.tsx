import { Shell, Chrome, Split, Rail, Main, H, Prose, Micro, Btn, Panel, Bar, Badge, Row, railWith } from '../ui'

export default function AddDump() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('+ Add a source')} />
        <Main>
          <div className="flex flex-col gap-2">
            <H>sales-2024.sql</H>
            <Micro>PostgreSQL dump · 840 MB</Micro>
          </div>

          <Panel>
            <Prose className="text-[15px]">
              <strong>This file contains commands, not just data.</strong> Askwell runs it inside a sealed
              database that cannot reach your other sources, the internet, or Askwell's own files. If the dump is
              broken or malicious, only that sealed copy is affected.
            </Prose>
          </Panel>

          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between">
              <span className="text-[13px]">Loading into a sealed copy</span>
              <span className="text-[12px] tabular-nums text-[var(--ask-muted)]">312 MB of 840 MB · 2m 10s elapsed</span>
            </div>
            <Bar pct={37} />
          </div>

          <Panel title="containment">
            <Row k="Sealed database" v="one, for this source only" tone="prov" />
            <Row k="Reachable from it" v="nothing — no network, no other source" tone="prov" />
            <Row k="Runs as" v="restricted account, not an administrator" tone="prov" />
            <Row k="Size cap" v="5 GB — import aborts beyond it" />
            <Row k="Time cap" v="10 minutes — import aborts beyond it" />
          </Panel>

          <div className="flex gap-3"><Btn alarm sm>Stop and discard</Btn></div>
          <Micro>MySQL or SQL Server dump? Connect to the database directly, or export the tables as CSV — both work, and CSV usually gives better answers.</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
