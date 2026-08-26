import { Shell, Chrome, Split, Rail, Main, H, Micro, Badge, Prose, Btn, Panel, railWith } from '../ui'

export default function TraceAbstention() {
  return (
    <Shell>
      <Chrome right={<Badge>local · Qwen3.5 9B</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <div className="flex flex-wrap items-baseline gap-3">
            <H>Why Askwell said it didn't know</H>
            <Micro>“What is our current professional indemnity excess?”</Micro>
          </div>

          <Panel title="what was searched">
            <div className="flex flex-col gap-1.5 text-[13px]">
              <span>1,240 passages · 38 documents · 2 databases</span>
              <span className="text-[var(--ask-muted)]">threshold in force: 0.65</span>
            </div>
          </Panel>

          <div className="rounded-[var(--ask-radius)] border border-[var(--ask-inferred)] bg-[var(--ask-surface)] p-4">
            <Micro>the closest match, and it missed</Micro>
            <div className="mt-2 flex items-baseline gap-3">
              <span className="w-10 tabular-nums text-[var(--ask-inferred)] text-[13px]">0.61</span>
              <span className="text-[12.5px]">insurance-schedule-2023.pdf p.2</span>
              <span className="ml-auto text-[11px] text-[var(--ask-muted)]">0.04 under the threshold</span>
            </div>
            <Prose className="mt-2 text-[14px] text-[var(--ask-muted)]">
              “Public liability cover is maintained at £5,000,000 per claim…” — related, but it does not mention
              professional indemnity at all.
            </Prose>
          </div>

          <Panel>
            <Prose className="text-[15px]">
              You can lower the threshold so Askwell answers from weaker matches like this one.
            </Prose>
            <Prose className="mt-2 text-[14px] text-[var(--ask-muted)]">
              It will answer more often and be wrong more often. The passage above is a near miss for a reason — it is
              about a different kind of insurance. Lowering the threshold is recorded in your log.
            </Prose>
            <div className="mt-3 flex flex-wrap gap-3">
              <Btn sm>Lower the threshold to 0.60</Btn>
              <Btn primary sm>Add the policy document instead</Btn>
            </div>
          </Panel>

          <Micro>this is the most useful trace there is — it shows what was nearly found, and why nearly wasn't enough</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
