import {
  Shell, Chrome, Split, Rail, Main, Composer, Q, Prose, ClaimRow, SourceCard,
  Chip, Badge, Micro, PastTurn, TurnDivider, Btn, Steps, railWith,
} from '../ui'

export default function AskConversation() {
  return (
    <Shell>
      <Chrome right={<><Badge>3 questions</Badge><Badge>local · Qwen3.5 9B</Badge></>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <TurnDivider label="earlier today" />

          <PastTurn
            q="Which suppliers are on non-standard payment terms?"
            summary="Four — Meridian, Harlow, Castleton and Ferndale. All recorded exceptions."
            sources="3 sources"
          />
          <PastTurn
            q="Why was Meridian given 45 days?"
            summary="Volume commitment in the 2024 renewal. The exception is minuted, not just agreed."
            sources="2 sources"
          />

          <TurnDivider label="just now" />

          {/* the live turn keeps its full margin — only past turns collapse */}
          <Q>So are any of them actually late right now?</Q>
          <Steps items={['used your earlier answer', 'queried sales-2024']} />

          <div className="flex flex-col gap-4">
            <ClaimRow
              claim={
                <Prose>
                  <strong>Two of the four are late.</strong> Meridian is 41 days past due on its oldest invoice,
                  and Harlow is 12 days past. Castleton and Ferndale are both inside their agreed terms.
                </Prose>
              }
              card={<SourceCard file="sales-2024 · invoices" loc="4 rows · 190 ms" quote="Live query — expand the SQL to check it." />}
            />
            <ClaimRow
              claim={
                <Prose>
                  Meridian's 45-day term makes it later than it looks against a 30-day default — measured against
                  its own terms it is 41 days over, not 56.
                </Prose>
              }
              card={<SourceCard file="supplier-agreement-2024.pdf" loc="page 14 · §7.2 Payment" quote="“Payment shall fall due forty-five (45) days from the date of a valid invoice.”" />}
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Chip known>st_cd = invoice status code</Chip>
            <Chip known>45-day terms · you confirmed, 5 Jun</Chip>
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            <Micro>ask next</Micro>
          </div>
          <div className="flex flex-wrap gap-2">
            <Btn sm>Show me Meridian's open invoices</Btn>
            <Btn sm to="trace">How did you get this?</Btn>
          </div>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
