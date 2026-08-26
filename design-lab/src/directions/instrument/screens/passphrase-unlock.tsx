import { Shell, Chrome, Main, H, Prose, Micro, Btn, Field, Badge } from '../ui'

export default function PassphraseUnlock() {
  return (
    <Shell>
      <Chrome right={<Badge>locked</Badge>} />
      <div className="mx-auto flex h-full max-w-[480px] flex-col justify-center">
        <Main>
          <H>Askwell is locked.</H>
          <Prose className="text-[15px]">
            Your library and saved database credentials are encrypted on this disk. Enter your passphrase to unlock them.
          </Prose>
          <div className="pt-1"><Field>passphrase</Field></div>
          <div className="flex gap-3"><Btn primary>Unlock</Btn></div>
          <Prose className="text-[14px] text-[var(--muted)]">
            There is no recovery. Askwell cannot reset this for you — if it could, the encryption would be worth nothing.
            Without the passphrase the only way forward is to start again from your original files, which are untouched.
          </Prose>
          <Micro>this protects a stolen, powered-off laptop — not a machine someone is already sitting at</Micro>
        </Main>
      </div>
    </Shell>
  )
}
