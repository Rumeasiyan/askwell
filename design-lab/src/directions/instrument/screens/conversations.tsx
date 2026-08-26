import { Shell, Chrome, Split, Rail, Main, H, Micro, Btn, Badge, Table, Mark, Field, railWith } from '../ui'

export default function Conversations() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <div className="flex flex-wrap items-baseline gap-3">
            <H>Everything you've asked</H>
            <Micro>184 questions · since 3 June</Micro>
            <div className="ml-auto w-[220px]"><Field>Search your questions…</Field></div>
          </div>

          <Table
            head={['question', 'when', 'sources', 'answer']}
            rows={[
              ['Which customers owe us the most right now?', '11:42', 'billing_prod', <span className="inline-flex items-center gap-1.5"><Mark known />5 rows, cited</span>],
              ['What payment terms did we agree with Meridian?', '11:38', '2 documents', <span className="inline-flex items-center gap-1.5"><Mark known />3 claims, cited</span>],
              ['What is our professional indemnity excess?', '11:31', '—', <span className="text-[var(--ask-muted)]">didn’t know</span>],
              ['Have we ever invoked the notice period?', '10:57', '1 document', <span className="text-[var(--ask-inferred)]">partly answered</span>],
              ['Clear out written-off invoices', '10:44', '—', <span className="text-[var(--ask-alarm)]">refused — not a read query</span>],
              ['Summarise the Q2 board pack', '09:15', '1 document', <span className="inline-flex items-center gap-1.5"><Mark known />6 claims, cited</span>],
            ]}
          />

          <div className="flex flex-wrap gap-3">
            <Btn sm>Filter: didn’t know</Btn>
            <Btn sm>Filter: by source</Btn>
            <Btn sm>Export</Btn>
          </div>
          <Micro>the questions Askwell couldn’t answer are the most useful list here — they are what to add next</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
