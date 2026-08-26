import { Shell, Chrome, Split, Rail, Main, H, Prose, Micro, Btn, Badge, Panel, railWith } from '../ui'

export default function SourceMissing() {
  return (
    <Shell>
      <Chrome right={<Badge>local</Badge>} />
      <Split>
        <Rail groups={railWith('Ask')} />
        <Main>
          <Panel>
            <div className="flex items-baseline gap-2">
              <span className="h-1.5 w-1.5 shrink-0 border border-[var(--ask-inferred)]" />
              <span className="text-[13px] text-[var(--ask-inferred)]">This file has moved</span>
            </div>
            <H>supplier-agreement-2024.pdf</H>
            <Prose className="mt-2 text-[15px]">
              Askwell reads your files where they are rather than copying them, so it followed a path that no longer exists:
            </Prose>
            <div className="mt-2 rounded-[var(--ask-radius)] border border-[var(--ask-rule)] bg-[var(--ask-sunk)] px-3 py-2 text-[12.5px] text-[var(--ask-muted)]">
              ~/Documents/Clients/Meridian/supplier-agreement-2024.pdf
            </div>
            <Prose className="mt-3 text-[14px] text-[var(--ask-muted)]">
              Nothing is lost. The text Askwell already read is still indexed and still answers questions — only the link
              back to the original is broken.
            </Prose>
            <div className="mt-3 flex gap-3"><Btn primary sm>Find it</Btn><Btn sm>Leave it for now</Btn></div>
          </Panel>

          <Panel>
            <div className="flex items-baseline gap-2">
              <span className="h-1.5 w-1.5 shrink-0 bg-[var(--ask-rule)]" />
              <span className="text-[13px] text-[var(--ask-muted)]">Deleted on 6 June</span>
            </div>
            <H>old-handbook.pdf</H>
            <Prose className="mt-2 text-[15px] text-[var(--ask-muted)]">
              You deleted this from Askwell. Its contents are gone and it no longer influences answers. The record that it
              was once cited remains, so older answers still say where they came from instead of breaking.
            </Prose>
            <Micro>your original file on disk was never touched</Micro>
          </Panel>
        </Main>
      </Split>
    </Shell>
  )
}
