import { Shell, Chrome, Split, Rail, Main, H, Prose, Micro, Btn, Panel, Badge, railWith } from '../ui'

const routes = [
  { t: 'Files', d: 'PDF, Word, Excel, PowerPoint, text, images. Scanned pages are read too.' },
  { t: 'Spreadsheet or CSV', d: 'Tabular exports. Askwell asks about anything it cannot infer.' },
  { t: 'Database dump', d: 'PostgreSQL .sql or .dump. Loaded into a sealed copy.' },
  { t: 'Connect a database', d: 'PostgreSQL, MySQL/MariaDB, SQL Server. Read-only access only.' },
]

export default function AddSource() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('+ Add a source')} />
        <Main>
          <div className="flex flex-col gap-2">
            <H>Add a source</H>
            <Prose className="text-[15px] text-[var(--ask-muted)]">
              Askwell reads your files where they are. Nothing is copied into a library and nothing leaves this machine.
            </Prose>
          </div>

          <div className="flex min-h-[140px] flex-col items-center justify-center gap-2 rounded-[var(--ask-radius)] border border-dashed border-[var(--ask-rule)] bg-[var(--ask-surface)] py-8">
            <div className="text-[13px]">Drop files anywhere in Askwell</div>
            <Micro>or</Micro>
            <Btn primary sm to="add-indexing">Browse…</Btn>
          </div>

          <div className="grid gap-3 @2xl:grid-cols-2">
            {routes.map((r) => (
              <Panel key={r.t}>
                <div className="text-[13px]">{r.t}</div>
                <Prose className="mt-1 text-[13.5px] text-[var(--ask-muted)]">{r.d}</Prose>
              </Panel>
            ))}
          </div>

          <Micro>PDF · DOCX · XLSX · PPTX · TXT · MD · HTML · PNG · JPG · CSV · SQL dump</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
