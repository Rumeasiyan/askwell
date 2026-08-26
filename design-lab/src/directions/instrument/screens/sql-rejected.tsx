import { Shell, Chrome, Split, Rail, Main, Q, H, Prose, Micro, Btn, Panel, Badge, Composer, EmptyMargin, railWith } from '../ui'

export default function SqlRejected() {
  return (
    <Shell>
      <Chrome right={<Badge>local · Qwen3.5 4B</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Q>Clear out the invoices that were written off last year</Q>

          <div className="grid grid-cols-[minmax(0,1fr)_28px_268px] items-start">
            <div className="flex flex-col gap-3 py-4">
              <H>I can read your database, not change it.</H>
              <Prose>
                Askwell only ever runs read queries. It connected with an account that cannot write, and it checks every
                query before running it — this one was stopped by both.
              </Prose>
              <Prose className="text-[15px] text-[var(--muted)]">
                Nothing ran. Your data is unchanged. If you want to see which invoices were written off, ask for that
                instead and Askwell will show you.
              </Prose>
              <div className="pt-1"><Btn primary>Show me written-off invoices from 2025</Btn></div>
            </div>
            <div />
            <EmptyMargin>no query ran</EmptyMargin>
          </div>

          <Panel title="what was refused">
            <pre className="m-0 overflow-x-auto text-[12.5px] leading-[1.6] text-[var(--muted)]">{`DELETE FROM invoices
WHERE  st_cd = 'W'
  AND  issued_on < '2026-01-01'`}</pre>
            <div className="mt-3 flex flex-col gap-1.5 text-[12.5px]">
              <span className="text-[var(--alarm)]">▪ rejected — not a read query</span>
              <span className="text-[var(--muted)]">the account Askwell uses has no permission to write regardless</span>
            </div>
          </Panel>
          <Micro>refused queries are kept in your log — they are how you notice if answers start degrading</Micro>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
