import {
  Shell, Chrome, Split, Rail, Main, Composer, Q, Prose, ClaimRow, SourceCard, Steps,
  Badge, Micro, NotYourMaterial, WebResult, railWith,
} from '../ui'

export default function WebMixed() {
  return (
    <Shell>
      <Chrome right={<><Badge tone="inf">web · this question only</Badge><Badge>local · Qwen3.5 9B</Badge></>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Q>Is our Meridian notice period unusual for the sector?</Q>
          <Steps items={['read 1 document', 'you asked me to search the web', 'read 2 pages']} />

          <Micro>from your files</Micro>
          <ClaimRow
            claim={<Prose>Your agreement with Meridian sets <strong>90 days' notice</strong> for termination without cause.</Prose>}
            card={<SourceCard file="supplier-agreement-2024.pdf" loc="page 22 · §14.1" quote="“Either party may terminate on ninety (90) days' written notice.”" />}
          />

          <NotYourMaterial>
            <Prose>
              Sector guidance generally describes <strong>30 to 60 days</strong> as typical for supplier agreements of
              this size, which would make ninety days longer than usual rather than unusual in kind.
            </Prose>
            <WebResult
              site="cips.org"
              title="Contract termination clauses: good practice"
              quote="“Notice periods of 30–60 days are common for suppliers below £1m annual spend.”"
              fetched="today, 12:04"
            />
          </NotYourMaterial>

          <Micro>
            each claim points at whichever kind of source it came from — your document above, the web below, never blurred together
          </Micro>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
