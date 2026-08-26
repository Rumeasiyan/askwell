import { Shell, Chrome, Split, Rail, Main, H, Micro, Btn, Badge, Panel, Prose, Bar, Row, Table, railWith } from '../ui'

export default function SettingsStorage() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Settings')} />
        <Main>
          <H>Storage</H>

          <Panel title="record of what you asked — 1.6 GB of 2 GB">
            <div className="mb-2"><Bar pct={80} tone="inf" /></div>
            <Prose className="text-[14.5px]">
              You are near the limit you set. Export and prune the older half, or raise the limit — Askwell keeps working
              either way.
            </Prose>
            <Prose className="mt-2 text-[14px] text-[var(--ask-muted)]">
              At the limit, adding new sources stops first and asking questions keeps working. Reading is what you opened
              Askwell for; indexing is what fills the disk.
            </Prose>
            <div className="mt-3 flex flex-wrap gap-3">
              <Btn primary sm>Export and prune</Btn><Btn sm>Raise the limit</Btn>
            </div>
          </Panel>

          <Panel title="what is kept">
            <Row k="Decisions and memory" v="forever · never pruned" tone="prov" />
            <Row k="Questions and answers" v="12 months, then archived" />
            <Row k="Detailed working" v="most recent only · rotates" />
          </Panel>

          <Panel title="index">
            <Table
              head={['source', 'documents', 'index size']}
              rows={[
                ['Contracts', '14', '210 MB'],
                ['Policies', '6', '84 MB'],
                ['sales-2024', 'imported dump', '1.1 GB'],
                ['scanned-invoices', '12', '46 MB'],
              ]}
            />
          </Panel>
          <Micro>your original files are not counted here — Askwell reads them where they are</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
