import { Shell, Chrome, Split, Rail, Main, H, Micro, Btn, Badge, Mark, Prose, railWith } from '../ui'

function Fact({ known, subject, source, body, origin, used }: any) {
  return (
    <div className="flex flex-col gap-1.5 border-b border-[var(--rule)] py-3 last:border-0">
      <div className="flex items-baseline gap-2">
        <Mark known={known} />
        <span className="text-[12.5px]">{subject}</span>
        <span className="ml-auto text-[11px] text-[var(--muted)]">{source}</span>
      </div>
      <Prose className="text-[14.5px]">{body}</Prose>
      <div className="flex flex-wrap items-center gap-3 text-[11px] text-[var(--muted)]">
        <span>{origin}</span><span>·</span><span>used in {used} answers</span>
        <span className="ml-auto flex gap-2">
          {!known && <Btn sm>Confirm</Btn>}
          <Btn sm>Edit</Btn><Btn sm>Delete</Btn>
        </span>
      </div>
    </div>
  )
}

export default function Memory() {
  return (
    <Shell>
      <Chrome right={<Badge>23 facts</Badge>} />
      <Split>
        <Rail groups={railWith('Memory')} />
        <Main>
          <div className="flex flex-wrap items-baseline gap-3">
            <H>What Askwell believes about your material</H>
            <div className="ml-auto flex gap-2"><Btn sm>Add a fact</Btn><Btn sm>Filter</Btn></div>
          </div>
          <Micro>guesses first — those are the ones worth correcting</Micro>

          <div className="rounded-[var(--radius)] border border-[var(--rule)] bg-[var(--surface)] px-4">
            <Fact subject="invoices.amount_gbp" source="sales-2024" origin="I guessed · from the column name" used={4}
              body="Amounts are in pounds sterling." />
            <Fact subject="contracts · “RFQ”" source="Contracts" origin="I guessed · from surrounding text" used={11}
              body="RFQ means Request for Quotation." />
            <Fact known subject="invoices.st_cd" source="sales-2024" origin="You told me · 3 June" used={12}
              body="Invoice status: O=open, P=paid, W=written off." />
            <Fact known subject="policy precedence" source="Policies" origin="You told me · 4 June" used={7}
              body="The 2026 procurement policy supersedes the 2024 handbook wherever they disagree." />
            <Fact known subject="Meridian Foods" source="Contracts" origin="You corrected me · 5 June" used={9}
              body="Meridian Foods and Meridian Fresh Ltd are the same supplier under different trading names." />
          </div>

          <Micro>
            nothing here expires on its own · a correction supersedes rather than overwrites, and the old value stays in history
          </Micro>
        </Main>
      </Split>
    </Shell>
  )
}
