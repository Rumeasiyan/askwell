import { Shell, Chrome, Split, Rail, Main, H, Btn, Badge, Panel, Prose, Row, railWith } from '../ui'

export default function SettingsPrivacy() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Settings')} />
        <Main>
          <H>Privacy and security</H>

          <Panel title="network activity">
            <div className="flex items-baseline gap-3">
              <span className="text-[28px] tabular-nums text-[var(--provenance)]">0</span>
              <span className="text-[13px]">outbound requests since install</span>
            </div>
            <Prose className="mt-2 text-[14px] text-[var(--muted)]">
              Not a setting — a count. Everything Askwell runs goes through a gate that refuses outbound connections, and
              this is what that gate has seen. Turning on online AI for a conversation opens exactly one destination, for
              that conversation only.
            </Prose>
            <div className="mt-3"><Btn sm>See what was refused</Btn></div>
          </Panel>

          <Panel title="passphrase">
            <Row k="Status" v="not set" />
            <Prose className="mt-2 text-[14.5px]">
              A passphrase encrypts your indexed library and any saved database credentials, so a stolen laptop is not a
              stolen archive.
            </Prose>
            <Prose className="mt-2 text-[14px] text-[var(--muted)]">
              It protects a powered-off machine. It does nothing against someone sitting at an unlocked one — and if you
              lose it, there is no recovery, because a recovery path would defeat the point.
            </Prose>
            <div className="mt-3"><Btn sm>Set a passphrase</Btn></div>
          </Panel>

          <Panel title="connected databases">
            <Row k="billing_prod" v="read-only · checked 4 June" tone="prov" />
            <Row k="sales-2024" v="imported copy · sealed, no network" tone="prov" />
            <Prose className="mt-2 text-[14px] text-[var(--muted)]">
              Askwell refuses credentials that can modify a database, and re-checks when it reconnects.
            </Prose>
          </Panel>
        </Main>
      </Split>
    </Shell>
  )
}
