import { Shell, Chrome, Main, H, Prose, Micro, Btn, Badge, Panel, Row } from '../ui'

export default function FirstRunProbe() {
  return (
    <Shell>
      <Chrome right={<Badge>first run</Badge>} />
      <div className="mx-auto flex max-w-[720px] flex-col">
        <Main>
          <Micro>step 2 of 4</Micro>
          <H>This machine can run Askwell comfortably.</H>

          <Panel title="what was found">
            <Row k="Memory" v="16 GB" tone="prov" />
            <Row k="Graphics" v="none Askwell can use" />
            <Row k="Disk free" v="212 GB" tone="prov" />
            <Row k="Profile chosen" v="standard" tone="prov" />
          </Panel>

          <Prose>
            Expect answers in about <strong>fifteen seconds</strong>. Voice will work. A machine with a graphics card
            would be roughly four times faster, but nothing here is degraded.
          </Prose>
          <Prose className="text-[15px] text-[var(--ask-muted)]">
            You can change the model later if you want to trade speed for quality in either direction.
          </Prose>

          <div className="flex gap-3 pt-1"><Btn primary>Get the model</Btn><Btn>Check again</Btn></div>
        </Main>
      </div>
    </Shell>
  )
}
