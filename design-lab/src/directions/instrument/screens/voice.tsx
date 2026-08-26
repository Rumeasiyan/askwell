import { Shell, Chrome, Split, Rail, Main, Q, Prose, ClaimRow, SourceCard, Micro, Btn, Badge, railWith } from '../ui'

export default function Voice() {
  return (
    <Shell>
      <Chrome right={<><Badge tone="prov">listening</Badge><Badge>local · Qwen3.5 9B</Badge></>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <div className="flex flex-col gap-2">
            <Micro>you said · transcribed on this machine</Micro>
            <Q>What payment terms did we agree with Meridian?</Q>
          </div>

          <ClaimRow
            claim={
              <div className="flex flex-col gap-2">
                <Prose>Meridian Foods is on <strong>45-day payment terms</strong> from date of invoice.</Prose>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] uppercase tracking-[0.08em] text-[var(--provenance)]">speaking</span>
                  <div className="flex h-3 items-end gap-[2px]">
                    {[6, 11, 4, 9, 12, 5, 8].map((h, i) => (
                      <span key={i} className="w-[3px] bg-[var(--provenance)]" style={{ height: h }} />
                    ))}
                  </div>
                  <span className="ml-2"><Btn sm>Stop</Btn></span>
                </div>
              </div>
            }
            card={<SourceCard file="supplier-agreement-2024.pdf" loc="page 14 · §7.2" quote="“Payment shall fall due forty-five (45) days…”" />}
          />

          <Prose className="text-[14px] text-[var(--muted)]">
            Citations are not read aloud — “supplier-agreement-2024.pdf, page fourteen” is unbearable to listen to.
            They stay on screen, and the spoken answer says “from the 2024 supply agreement” where it matters.
          </Prose>

          <div className="flex items-center gap-3 border-t border-[var(--rule)] bg-[var(--sunk)] px-4 py-3">
            <div className="flex h-4 items-end gap-[3px]">
              {[3, 7, 12, 16, 9, 5, 11, 14, 6, 3].map((h, i) => (
                <span key={i} className="w-[3px] bg-[var(--muted)]" style={{ height: h }} />
              ))}
            </div>
            <Micro>hold to speak · release when done</Micro>
            <div className="ml-auto flex gap-2"><Btn sm>Switch to typing</Btn></div>
          </div>
        </Main>
      </Split>
    </Shell>
  )
}
