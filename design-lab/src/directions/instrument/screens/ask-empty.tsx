import { Shell, Chrome, Split, Rail, Main, Composer, H, Prose, Btn, Micro, Badge } from '../ui'

export default function AskEmpty() {
  const rails = [
    { title: 'Sources', items: [{ label: 'none yet', count: '0' }] },
    { title: 'Library', items: [{ label: 'Ask', on: true }, { label: 'Clarifications' }, { label: 'Memory' }, { label: 'Settings' }] },
  ]
  return (
    <Shell>
      <Chrome right={<Badge>local · ready</Badge>} />
      <Split>
        <Rail groups={rails} />
        <Main className="justify-center">
          <div className="flex max-w-[var(--ask-measure)] flex-col gap-4 py-10">
            <H>Nothing to ask about yet.</H>
            <Prose>
              Add your files and Askwell reads them here on this machine — PDFs including scanned ones, Word,
              spreadsheets, a database dump, or a read-only connection to a database you already run.
            </Prose>
            <Prose className="text-[15px] text-[var(--ask-muted)]">
              It indexes them where they are. Nothing is copied, nothing is uploaded.
            </Prose>
            <div className="pt-1"><Btn primary to="add-source">Add your first source</Btn></div>
            <Micro>an empty box invites a question that cannot be answered — so there isn't one</Micro>
          </div>
        </Main>
      </Split>
      <Composer />
    </Shell>
  )
}
