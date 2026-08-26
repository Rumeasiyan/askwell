import { Shell, Chrome, Split, Rail, Main, H, Prose, Micro, Btn, Panel, Badge, railWith } from '../ui'

export default function VoiceStates() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <H>Voice — the states that are not the happy path</H>

          <Panel title="microphone not allowed">
            <Prose className="text-[15px]">
              Your browser has not given Askwell access to the microphone. Voice is switched off until it does — nothing
              is broken, and typing works exactly as before.
            </Prose>
            <div className="mt-3"><Btn sm>How to allow it</Btn></div>
          </Panel>

          <Panel title="that took longer than it should">
            <Prose className="text-[15px]">
              Still working — about four seconds so far.
            </Prose>
            <Prose className="mt-1 text-[14px] text-[var(--muted)]">
              This appears only once an answer passes its budget. On a healthy turn you never see it, and its whole job is
              to stop you concluding it has hung and trying again.
            </Prose>
          </Panel>

          <Panel title="I heard you, but not clearly">
            <Prose className="text-[16px] font-semibold">“What payment terms did we agree with Meridian?”</Prose>
            <Prose className="mt-1 text-[14px] text-[var(--muted)]">
              Confidence was low on this one. Answering the wrong question confidently is worse than one extra tap.
            </Prose>
            <div className="mt-3 flex gap-3"><Btn primary sm>Yes, ask that</Btn><Btn sm>Let me say it again</Btn></div>
          </Panel>

          <Panel title="speech is unavailable">
            <Prose className="text-[15px]">
              The voice hasn't loaded, so this answer is text only. Everything else works — voice is a way in and out, not
              a separate product.
            </Prose>
          </Panel>

          <Micro>no barge-in: speaking over an answer does nothing, the stop control is the way out</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
