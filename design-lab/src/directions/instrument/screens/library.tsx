import { Shell, Chrome, Split, Rail, Main, H, Micro, Btn, Badge, Table, Mark, railWith } from '../ui'

export default function Library() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Settings')} />
        <Main>
          <div className="flex items-baseline gap-3">
            <H>Sources</H>
            <Micro>38 documents · 2 databases · 1 needs attention</Micro>
            <div className="ml-auto"><Btn primary sm to="add-source">Add a source</Btn></div>
          </div>

          <Table
            head={['name', 'kind', 'added', 'status', 'questions']}
            rows={[
              ['Contracts', '14 files', '3 Jun', <span key="st" className="inline-flex items-center gap-1.5"><Mark known />indexed</span>, '—'],
              ['Policies', '6 files', '3 Jun', <span key="st" className="inline-flex items-center gap-1.5"><Mark known />indexed</span>, '—'],
              ['sales-2024', 'imported dump', '4 Jun', <span key="st" className="inline-flex items-center gap-1.5"><Mark known />indexed</span>, <span key="q" className="text-[var(--ask-inferred)]">5 open</span>],
              ['billing_prod', 'live connection', '4 Jun', <span key="st" className="inline-flex items-center gap-1.5"><Mark known />connected</span>, '—'],
              ['scanned-invoices', '12 files', '5 Jun', <span key="st" className="inline-flex items-center gap-1.5 text-[var(--ask-alarm)]"><span className="h-1.5 w-1.5 bg-[var(--ask-alarm)]" />needs attention</span>, '—'],
              [<span key="n" className="text-[var(--ask-muted)] line-through">old-handbook.pdf</span>, '1 file', '1 Jun', <span key="st" className="text-[var(--ask-muted)]">deleted 6 Jun</span>, '—'],
            ]}
          />

          <div className="rounded-[var(--ask-radius)] border border-[var(--ask-alarm)] bg-[var(--ask-surface)] p-4">
            <div className="text-[13px] text-[var(--ask-alarm)]">scanned-invoices — 3 of 12 files barely readable</div>
            <div className="mt-2 max-w-[var(--ask-measure)] text-[14px] leading-relaxed">
              Optical character recognition found almost no text on these pages. They are indexed but will retrieve
              badly, so answers may miss them entirely.
            </div>
            <div className="mt-3 flex gap-3"><Btn sm>See which files</Btn><Btn sm>Try reading them again</Btn></div>
          </div>

          <Micro>your original files are untouched — Askwell reads them where they are</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
