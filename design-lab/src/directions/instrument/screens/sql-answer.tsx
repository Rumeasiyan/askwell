import { Shell, Chrome, Split, Rail, Main, Q, Steps, Prose, ClaimRow, SourceCard, Sql, Chip, Table, Badge, Micro, Composer, railWith } from '../ui'

export default function SqlAnswer() {
  return (
    <Shell>
      <Chrome right={<Badge>local · Qwen3.5 9B</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Q>Which customers owe us the most right now?</Q>
          <Steps items={['looked up schema', 'queried billing_prod', 'checked 3 memory facts']} />

          <ClaimRow
            claim={<Prose><strong>Meridian Foods owes the most</strong> at £84,210 across 7 open invoices, followed by Harlow Group at £51,900.</Prose>}
            card={<SourceCard file="billing_prod · invoices" loc="5 rows · 180 ms" quote="Live query — the SQL is shown below, unedited." />}
          />

          <Table
            head={['customer', 'open invoices', 'total (GBP)', 'oldest']}
            rows={[
              ['Meridian Foods', '7', '84,210.00', '12 May 2026'],
              ['Harlow Group', '4', '51,900.00', '28 May 2026'],
              ['Castleton Ltd', '2', '18,400.00', '3 Jun 2026'],
              ['Ferndale Supply', '1', '9,750.00', '11 Jun 2026'],
              ['Ashby & Co', '1', '2,140.00', '14 Jun 2026'],
            ]}
          />

          <Sql note="LIMIT  1000    -- added by Askwell; showing the first 5 of possibly more">{`SELECT customer, COUNT(*) AS open_invoices,
       SUM(amount_gbp) AS total_gbp, MIN(issued_on) AS oldest
FROM   invoices
WHERE  st_cd = 'O'
GROUP  BY customer
ORDER  BY total_gbp DESC`}</Sql>

          <div className="flex flex-wrap items-center gap-2">
            <Chip known>st_cd = invoice status code</Chip>
            <Chip known>issued_on = day first (3 April)</Chip>
            <Chip>amount_gbp = pounds sterling · I guessed</Chip>
          </div>
          <Micro>read-only connection · the query ran unchanged and is shown exactly as executed</Micro>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
