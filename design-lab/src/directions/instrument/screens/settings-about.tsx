import { Shell, Chrome, Split, Rail, Main, H, Micro, Btn, Badge, Panel, Prose, Row, railWith } from '../ui'

export default function SettingsAbout() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Settings')} />
        <Main>
          <H>About</H>

          <Panel>
            <Row k="Version" v="0.1.0" />
            <Row k="Licence" v="Apache-2.0 · free to use, fork and audit" tone="prov" />
            <Row k="Source" v="github.com/Rumeasiyan/askwell" tone="prov" />
            <Row k="Models in use" v="Qwen3.5 4B · bge-m3 · whisper small · Kokoro" />
            <Prose className="mt-3 text-[14px] text-[var(--muted)]">
              Every model Askwell ships can be redistributed freely. That is a requirement, not a coincidence — it is why
              some otherwise better models are not here.
            </Prose>
          </Panel>

          <Panel title="updates">
            <Row k="Checking" v="off" />
            <Prose className="mt-2 text-[14.5px]">
              Askwell can check weekly for a new version. That is one request carrying your version number and nothing
              else — no identifier, no usage, no files.
            </Prose>
            <Prose className="mt-2 text-[14px] text-[var(--muted)]">
              It is off because “no network connections” should mean exactly that. If you leave it off, watch the
              repository instead — security fixes are worth knowing about.
            </Prose>
            <div className="mt-3 flex gap-3"><Btn sm>Turn on weekly checks</Btn><Btn sm>Check once now</Btn></div>
          </Panel>

          <Panel title="something wrong?">
            <Prose className="text-[14.5px]">
              Askwell is maintained by one person. Issues are read, all of them. Security reports are answered within a
              week. Nothing else is promised, and that boundary is written down rather than left for you to discover.
            </Prose>
            <div className="mt-3 flex flex-wrap gap-3">
              <Btn sm>Report a problem</Btn><Btn sm>Report something security-related</Btn>
            </div>
          </Panel>
          <Micro>no telemetry · Askwell does not know you are running it</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
