import { Shell, Chrome, Split, Rail, Main, H, Prose, Micro, Btn, Table, Badge, Mark, railWith } from '../ui'

export default function AddCsvReview() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Settings')} />
        <Main>
          <div className="flex flex-col gap-2">
            <H>invoices-export.csv</H>
            <Prose className="text-[15px] text-[var(--ask-muted)]">
              A CSV carries no types and no constraints. Here is what Askwell worked out — correct anything wrong before it indexes.
            </Prose>
          </div>

          <Table
            head={['column', 'read as', 'sample', 'source']}
            rows={[
              ['invoice_no', 'text', 'INV-40118', <span className="inline-flex items-center gap-1.5"><Mark known /> certain</span>],
              ['issued_on', <span className="text-[var(--ask-inferred)]">date — format unclear</span>, '03/04/2026', <span className="inline-flex items-center gap-1.5"><Mark /> needs you</span>],
              ['amount_gbp', 'number', '1,200.00', <span className="inline-flex items-center gap-1.5"><Mark /> I guessed</span>],
              ['st_cd', <span className="text-[var(--ask-inferred)]">code — meaning unknown</span>, 'O / P / W', <span className="inline-flex items-center gap-1.5"><Mark /> needs you</span>],
              ['column 7', <span className="text-[var(--ask-inferred)]">no header</span>, '2026-05-12', <span className="inline-flex items-center gap-1.5"><Mark /> needs you</span>],
            ]}
          />

          <div className="rounded-[var(--ask-radius)] border border-[var(--ask-inferred)] bg-[var(--ask-surface)] p-4">
            <Micro>Askwell will not guess this one</Micro>
            <Prose className="mt-1 text-[16px] font-semibold">
              Is 03/04/2026 the 3rd of April, or the 4th of March?
            </Prose>
            <Prose className="mt-1 text-[14px] text-[var(--ask-muted)]">
              1,240 rows are ambiguous. Getting it wrong moves every answer by up to eleven months, and looks entirely reasonable while doing it.
            </Prose>
            <div className="mt-3 flex gap-3">
              <Btn primary sm>Day first — 3 April</Btn>
              <Btn sm>Month first — 4 March</Btn>
            </div>
          </div>

          <div className="flex gap-3">
            <Btn primary to="add-indexing">Index it</Btn>
            <Btn to="clarifications">Ask me the rest later</Btn>
          </div>
          <Micro>3 more questions will wait in Clarifications — the source is queryable meanwhile</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
