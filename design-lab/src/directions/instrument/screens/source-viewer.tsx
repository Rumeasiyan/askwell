import { Shell, Chrome, Split, Rail, Main, Micro, Btn, Badge, Prose, railWith } from '../ui'

export default function SourceViewer() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('All sources')} />
        <div className="grid min-w-0 grid-cols-1 overflow-y-auto @3xl:grid-cols-[minmax(0,1fr)_260px] @3xl:overflow-visible">
          <Main className="gap-4">
            <div className="flex items-baseline gap-3">
              <span className="text-[12.5px] text-[var(--ask-provenance)]">supplier-agreement-2024.pdf</span>
              <Micro>page 14 of 31</Micro>
              <div className="ml-auto flex gap-2"><Btn sm>◂ previous citation</Btn><Btn sm>next citation ▸</Btn></div>
            </div>

            <div className="rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)] p-6">
              <Micro>7. Payment</Micro>
              <Prose className="mt-3 text-[15px] text-[var(--ask-muted)]">
                7.1 The Supplier shall issue invoices monthly in arrears, itemised by purchase order reference.
              </Prose>
              <Prose className="mt-3 bg-[var(--ask-provenance)]/15 px-1 text-[15px]">
                7.2 Payment shall fall due forty-five (45) days from the date of a valid invoice. A valid invoice is one
                bearing a purchase order reference and delivered to the address in Schedule 2.
              </Prose>
              <Prose className="mt-3 text-[15px] text-[var(--ask-muted)]">
                7.3 Late payment shall bear interest at 2% above base rate, accruing daily.
              </Prose>
            </div>
          </Main>

          <aside className="flex flex-col gap-4 border-t border-[var(--ask-rule)] bg-[var(--ask-sunk)] p-4 @3xl:border-l @3xl:border-t-0">
            <div>
              <Micro>you came from</Micro>
              <Prose className="mt-2 text-[14px]">
                “Meridian Foods is on 45-day payment terms from date of invoice…”
              </Prose>
              <div className="mt-3"><Btn sm>◂ back to the answer</Btn></div>
            </div>
            <div className="border-t border-[var(--ask-rule)] pt-4">
              <Micro>this document</Micro>
              <div className="mt-2 flex flex-col gap-1 text-[12.5px] text-[var(--ask-muted)]">
                <span>31 pages · added 3 June</span>
                <span>cited in 9 answers</span>
              </div>
              <div className="mt-3 flex flex-col gap-2">
                <Btn sm>Search inside</Btn>
                <Btn sm>Ask about this file</Btn>
                <Btn sm>Open in system viewer</Btn>
              </div>
            </div>
          </aside>
        </div>
      </Split>
    </Shell>
  )
}
