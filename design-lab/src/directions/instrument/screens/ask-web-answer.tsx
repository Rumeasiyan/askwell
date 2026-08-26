import {
  Shell, Chrome, Split, Rail, Main, Composer, Q, Prose, Steps, Badge, Micro,
  NotYourMaterial, WebResult, Btn, railWith,
} from '../ui'

export default function AskWebAnswer() {
  return (
    <Shell>
      <Chrome right={<><Badge tone="inf">web · this question only</Badge><Badge>local · Qwen3.5 9B</Badge></>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Q>What is the standard notice period for a UK commercial lease?</Q>
          <Steps items={['your files: nothing matched', 'you asked me to search the web', 'read 3 pages']} />

          <NotYourMaterial>
            <Prose>
              There is no single standard. Break clauses commonly require <strong>six months' notice</strong>, and a
              tenant ending a lease at expiry under the 1954 Act must give between six and twelve months.
            </Prose>
            <Prose className="text-[14px] text-[var(--ask-muted)]">
              This is general information from the pages below. It is not advice, and it says nothing about your own
              leases — I could not find anything in your files that speaks to it.
            </Prose>

            <div className="flex flex-col gap-2">
              <WebResult
                site="gov.uk"
                title="Renewing and ending business leases: a tenant's guide"
                quote="“…must be given not more than 12 nor less than 6 months before the date specified.”"
                fetched="today, 11:52"
              />
              <WebResult
                site="legislation.gov.uk"
                title="Landlord and Tenant Act 1954, Part II, s.25"
                quote="“The notice must be given not more than twelve nor less than six months before…”"
                fetched="today, 11:52"
              />
            </div>
          </NotYourMaterial>

          <div className="flex flex-wrap items-center gap-3">
            <Btn sm to="add-source">Add a document about this</Btn>
            <Micro>then the answer comes from your own material next time</Micro>
          </div>

          <Micro>the search closed with this question — your next one starts local again</Micro>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
