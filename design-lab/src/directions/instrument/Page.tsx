import { Shell, Chrome, Split, Rail, Main, Composer, Q, Steps, Prose, ClaimRow, SourceCard, Chip, Sql, Badge, railWith } from './ui'

export default function AskAnswered() {
  return (
    <Shell>
      <Chrome right={<Badge>local · Qwen3.5 9B</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Q>What payment terms did we agree with Meridian Foods, and how many invoices are still open?</Q>
          <Steps items={['searched 1,240 passages', 'read 2 documents', 'queried sales-2024']} />

          <div className="flex flex-col gap-4">
            <ClaimRow
              claim={<Prose>Meridian Foods is on <strong>45-day payment terms</strong> from date of invoice, agreed in the 2024 supply agreement and unchanged since.</Prose>}
              card={<SourceCard file="supplier-agreement-2024.pdf" loc="page 14 · §7.2 Payment" quote="“Payment shall fall due forty-five (45) days from the date of a valid invoice.”" />}
            />
            <ClaimRow
              claim={<Prose>That is an exception to your standard terms, which are 30 days for suppliers under £250k annual spend.</Prose>}
              card={<SourceCard file="procurement-policy-v3.docx" loc="page 6 · Standard terms" quote="“Default payment terms are 30 days unless a written exception is recorded.”" />}
            />
            <ClaimRow
              claim={<Prose><strong>7 invoices are still open</strong>, totalling £84,210. The oldest was raised on 12 May 2026 and is 41 days out.</Prose>}
              card={<SourceCard file="sales-2024 · invoices" loc="7 rows · 240 ms" quote="Live query — expand the SQL below to check it." />}
            />
          </div>

          <Sql note="LIMIT  1000    -- added by Askwell; no limit was specified">{`SELECT invoice_no, issued_on, amount_gbp
FROM   invoices
WHERE  customer = 'Meridian Foods'
  AND  st_cd = 'O'
ORDER  BY issued_on`}</Sql>

          <div className="flex flex-wrap items-center gap-2">
            <Chip known>st_cd <span className="text-[var(--muted)]">= invoice status code · you told me, 3 Jun</span></Chip>
            <Chip>amount_gbp <span className="text-[var(--muted)]">= pounds sterling · I guessed</span></Chip>
          </div>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
