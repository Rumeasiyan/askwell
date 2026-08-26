import { Shell, Chrome, Split, Rail, Main, H, Micro, Btn, Badge, Prose, Mark, railWith } from '../ui'

function Card({ n, subject, q, evidence, guess, children }: any) {
  return (
    <div className="flex flex-col gap-3 rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-surface)] p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[12.5px]">{subject}</span>
        <Micro>{n} of 5</Micro>
      </div>
      <Prose className="text-[16px] font-semibold">{q}</Prose>
      <div className="flex flex-wrap items-center gap-2 text-[12.5px] tabular-nums text-[var(--ask-muted)]">{evidence}</div>
      {children}
      <div className="flex flex-wrap items-center gap-3">
        <Btn primary sm>Save</Btn>
        <Btn sm>Skip</Btn>
        <span className="ml-auto inline-flex items-center gap-1.5 text-[12px] text-[var(--ask-muted)]">
          {guess ? <><Mark />{guess}</> : 'no guess — I won’t infer this one'}
        </span>
      </div>
    </div>
  )
}

export default function Clarifications() {
  return (
    <Shell>
      <Chrome right={<Badge>5 pending</Badge>} />
      <Split>
        <Rail groups={railWith('Clarifications')} />
        <Main>
          <div className="flex flex-wrap items-baseline gap-3">
            <H>5 things I couldn't work out</H>
            <Micro>sales-2024.sql · imported 4 minutes ago · already searchable</Micro>
          </div>

          <Card
            n={1}
            subject="invoices.st_cd"
            q="What does st_cd mean?"
            guess="I guessed: status code"
            evidence={<><span><b className="font-normal text-[var(--ask-ink)]">40,112</b> rows</span><span>·</span><span>O <b className="font-normal text-[var(--ask-ink)]">31,204</b></span><span>P <b className="font-normal text-[var(--ask-ink)]">6,890</b></span><span>W <b className="font-normal text-[var(--ask-ink)]">2,018</b></span></>}
          >
            <div className="rounded-[var(--ask-radius)] border border-[var(--ask-provenance)] bg-[var(--ask-paper)] px-2.5 py-2 font-[var(--ask-font-text)] text-[14.5px]">
              Invoice status: O=open, P=paid, W=written off
            </div>
          </Card>

          <Card
            n={2}
            subject="invoices.issued_on"
            q="Is 03/04/2026 the 3rd of April, or the 4th of March?"
            evidence={<><span>1,240 values are ambiguous</span><span>·</span><span>nothing in the data settles it</span></>}
          >
            <div className="flex gap-3"><Btn primary sm>Day first (3 April)</Btn><Btn sm>Month first (4 March)</Btn></div>
          </Card>

          <Card
            n={3}
            subject="contracts · 2 documents disagree"
            q="Which of these is current?"
            guess="I guessed: the 2026 revision"
            evidence={<><span>procurement-policy-v3.docx says 90 days</span><span>·</span><span>supplier-handbook-2024.pdf says 60</span></>}
          >
            <div className="flex gap-3"><Btn sm>The 2026 policy</Btn><Btn sm>The 2024 handbook</Btn><Btn sm>Both, in different cases</Btn></div>
          </Card>

          <Micro>answering is optional — Askwell works without it, just less well</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
