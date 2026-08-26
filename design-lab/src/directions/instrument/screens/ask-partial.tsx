import { Shell, Chrome, Split, Rail, Main, Composer, Q, Prose, ClaimRow, SourceCard, EmptyMargin, Badge, Micro, railWith } from '../ui'

export default function AskPartial() {
  return (
    <Shell>
      <Chrome right={<Badge>local · Qwen3.5 9B</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Q>What notice period applies to Meridian, and have we ever invoked it?</Q>

          <div className="flex flex-col gap-4">
            <ClaimRow
              claim={<Prose>The agreement sets a <strong>90-day notice period</strong> for termination without cause, on either side.</Prose>}
              card={<SourceCard file="supplier-agreement-2024.pdf" loc="page 22 · §14.1 Termination" quote="“Either party may terminate on ninety (90) days' written notice.”" />}
            />
            <ClaimRow
              claim={
                <div className="flex flex-col gap-2">
                  <Micro>not covered by your files</Micro>
                  <Prose className="text-[var(--muted)]">
                    Whether notice has ever been invoked is not something your files record. I found no correspondence,
                    no termination notice and no entry in <em>sales-2024</em> that would show it.
                  </Prose>
                </div>
              }
              card={<EmptyMargin>nothing matched<br />for this part</EmptyMargin>}
            />
          </div>

          <div className="rounded-[var(--radius)] border border-[var(--rule)] bg-[var(--surface)] p-4">
            <Micro>two sources disagree</Micro>
            <div className="mt-2 grid gap-3 md:grid-cols-2">
              <div className="border-l-2 border-l-[var(--provenance)] pl-3">
                <div className="text-[12px] text-[var(--provenance)]">procurement-policy-v3.docx</div>
                <Micro>revised June 2026</Micro>
                <Prose className="mt-1 text-[14px]">Notice periods are 90 days for all tier-1 suppliers.</Prose>
              </div>
              <div className="border-l-2 border-l-[var(--provenance)] pl-3">
                <div className="text-[12px] text-[var(--provenance)]">supplier-handbook-2024.pdf</div>
                <Micro>superseded</Micro>
                <Prose className="mt-1 text-[14px]">Notice periods are 60 days unless separately agreed.</Prose>
              </div>
            </div>
            <Prose className="mt-3 text-[14px] text-[var(--muted)]">
              I have not picked one. Tell me which is current and I will remember it.
            </Prose>
          </div>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
