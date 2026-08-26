import { Shell, Chrome, Main, H, Prose, Micro, Btn, Badge, Bar, Panel } from '../ui'

export default function FirstRunDownload() {
  return (
    <Shell>
      <Chrome right={<Badge>first run</Badge>} />
      <div className="mx-auto flex max-w-[720px] flex-col">
        <Main>
          <Micro>step 3 of 4</Micro>
          <H>Getting the model — about 6 minutes left</H>

          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between">
              <span className="text-[13px]">Qwen3.5 4B</span>
              <span className="text-[12px] tabular-nums text-[var(--ask-muted)]">1.4 GB of 2.4 GB · 4.1 MB/s</span>
            </div>
            <Bar pct={58} />
          </div>

          <Prose className="text-[15px] text-[var(--ask-muted)]">
            This is the only wait. Once it is here, Askwell never needs the internet again unless you ask it to.
          </Prose>

          <Panel title="you don't have to sit here">
            <Prose className="text-[15px]">
              Add your files now and Askwell will start reading them while the model downloads — indexing doesn't need it.
            </Prose>
            <div className="mt-3 flex gap-3"><Btn primary sm>Add files now</Btn></div>
          </Panel>

          <div className="flex flex-col gap-2 border-t border-[var(--ask-rule)] pt-4">
            <Micro>on a slow or metered connection</Micro>
            <Prose className="text-[14px] text-[var(--ask-muted)]">
              You can download the model file separately and put it in place by hand — useful if this machine has no
              internet at all.
            </Prose>
            <div className="flex gap-3"><Btn sm>Place a model file myself</Btn><Btn sm>Pause</Btn></div>
          </div>
        </Main>
      </div>
    </Shell>
  )
}
