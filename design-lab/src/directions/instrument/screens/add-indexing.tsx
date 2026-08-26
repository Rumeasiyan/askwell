import { Shell, Chrome, Split, Rail, Main, H, Prose, Micro, Bar, Badge, Panel, Btn, railWith } from '../ui'

const files = [
  { n: 'supplier-agreement-2024.pdf', s: 'indexed', p: 100, d: '31 pages' },
  { n: 'procurement-policy-v3.docx', s: 'indexed', p: 100, d: '18 pages' },
  { n: 'scanned-invoice-2019.pdf', s: 'reading text from images', p: 64, d: 'page 7 of 12' },
  { n: 'board-pack-Q2.pptx', s: 'queued', p: 0, d: 'position 2' },
  { n: 'archive.zip', s: 'not supported', p: 0, d: 'rejected', bad: true },
]

export default function AddIndexing() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('+ Add a source')} />
        <Main>
          <div className="flex items-baseline gap-3">
            <H>Reading 4 files</H>
            <Micro>about 6 minutes left</Micro>
          </div>
          <Prose className="text-[15px] text-[var(--ask-muted)]">
            You can ask about what is already indexed. Leaving this screen does not stop it.
          </Prose>

          <div className="flex flex-col gap-3">
            {files.map((f) => (
              <Panel key={f.n}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className={`text-[12.5px] ${f.bad ? 'text-[var(--ask-alarm)]' : ''}`}>{f.n}</span>
                  <span className={`text-[11px] uppercase tracking-[0.06em] ${f.bad ? 'text-[var(--ask-alarm)]' : 'text-[var(--ask-muted)]'}`}>{f.s}</span>
                </div>
                {!f.bad && <div className="mt-2"><Bar pct={f.p} /></div>}
                <div className="mt-1.5 text-[11px] text-[var(--ask-muted)]">
                  {f.bad ? 'Askwell reads PDF, Word, Excel, PowerPoint, text, HTML and images. Unzip it and add the contents.' : f.d}
                </div>
              </Panel>
            ))}
          </div>

          <div className="flex gap-3"><Btn primary sm to="ask-answered">Ask about what&rsquo;s ready</Btn><Btn sm to="add-source">Add more</Btn></div>
        </Main>
      </Split>
    </Shell>
  )
}
