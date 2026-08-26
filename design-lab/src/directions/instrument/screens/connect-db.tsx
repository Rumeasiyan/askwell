import { Shell, Chrome, Split, Rail, Main, H, Prose, Micro, Btn, Field, Panel, Badge, railWith } from '../ui'

export default function ConnectDb() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Settings')} />
        <Main>
          <div className="flex flex-col gap-2">
            <H>Connect a database</H>
            <Prose className="text-[15px] text-[var(--muted)]">
              Askwell only connects with read-only access, and checks before it saves anything.
            </Prose>
          </div>

          <div className="grid max-w-[520px] gap-3 md:grid-cols-2">
            <div><Micro>host</Micro><div className="mt-1"><Field>localhost</Field></div></div>
            <div><Micro>port</Micro><div className="mt-1"><Field>5432</Field></div></div>
            <div><Micro>database</Micro><div className="mt-1"><Field>billing_prod</Field></div></div>
            <div><Micro>user</Micro><div className="mt-1"><Field>postgres</Field></div></div>
          </div>

          <Panel>
            <div className="flex items-baseline gap-2">
              <span className="h-1.5 w-1.5 shrink-0 bg-[var(--alarm)]" />
              <span className="text-[13px] text-[var(--alarm)]">These credentials can modify your database</span>
            </div>
            <Prose className="mt-2 text-[14px]">
              The account <strong>postgres</strong> can write to <strong>orders</strong>, <strong>invoices</strong> and 11 other tables.
              Askwell will not hold credentials that can damage your data, so this connection was not saved.
            </Prose>
            <Prose className="mt-2 text-[14px] text-[var(--muted)]">
              Create a read-only account and try again. Askwell can show you exactly what to run.
            </Prose>
            <div className="mt-3 flex gap-3">
              <Btn primary sm>Show me the commands</Btn>
              <Btn sm>Use a different account</Btn>
            </div>
          </Panel>

          <Micro>this is a refusal, not a warning — there is no override</Micro>
        </Main>
      </Split>
    </Shell>
  )
}
