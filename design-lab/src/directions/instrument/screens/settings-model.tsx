import { Shell, Chrome, Split, Rail, Main, H, Micro, Btn, Badge, Panel, Row, Prose, Mark, railWith } from '../ui'

export default function SettingsModel() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Settings')} />
        <Main>
          <H>Model and speed</H>

          <Panel title="this machine">
            <Row k="Profile" v="standard · 16 GB, no graphics card" />
            <Row k="Expect" v="answers in about 15 seconds" />
            <Row k="Measured" v="14.2 tokens per second" />
            <Row k="Memory in use" v="3.1 GB of 16 GB" />
            <div className="mt-3"><Btn sm>Check this machine again</Btn></div>
          </Panel>

          <Panel title="model">
            <div className="flex items-baseline gap-2 border-b border-[var(--ask-rule)] py-2">
              <Mark known />
              <span className="text-[13px]">Qwen3.5 4B</span>
              <span className="ml-auto text-[12px] text-[var(--ask-provenance)]">checked · shipped with Askwell</span>
            </div>
            <div className="flex items-baseline gap-2 py-2">
              <Mark />
              <span className="text-[13px] text-[var(--ask-muted)]">a model you place yourself</span>
              <span className="ml-auto text-[12px] text-[var(--ask-inferred)]">not checked</span>
            </div>
            <Prose className="mt-3 text-[14px] text-[var(--ask-muted)]">
              Askwell tests the models it ships — that they cite their sources, and that they say “I don’t know” rather
              than inventing an answer. A model you supply has not been through that, and Askwell cannot promise either
              behaviour for it. You can still use one; answers from it are marked.
            </Prose>
            <div className="mt-3 flex flex-wrap gap-3"><Btn sm>Use a different model</Btn></div>
            <Micro>swapping takes about twenty seconds, and search keeps working while it happens</Micro>
          </Panel>

          <Panel title="how sure it has to be before answering">
            <Row k="Current threshold" v="0.65" />
            <Prose className="mt-2 text-[14px] text-[var(--ask-muted)]">
              Lower this and Askwell answers from weaker matches — more answers, more of them wrong. Raise it and it says
              “I don’t know” more often. Changes are recorded in your log.
            </Prose>
            <div className="mt-3"><Btn sm>Change it</Btn></div>
          </Panel>
        </Main>
      </Split>
    </Shell>
  )
}
