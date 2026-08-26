import { type ReactNode } from 'react'

export type DeviceMode = 'mobile' | 'tablet' | 'desktop'

const WIDTHS: Record<DeviceMode, string> = {
  mobile: '390px',
  tablet: '834px',
  desktop: '100%',
}

export function DeviceFrame({
  mode,
  children,
}: {
  mode: DeviceMode
  children: ReactNode
}) {
  return (
    <div className="flex h-full w-full items-start justify-center overflow-auto bg-black/20 p-6">
      <div
        className="h-[calc(100vh-160px)] overflow-auto bg-[var(--color-bg)] shadow-2xl transition-[width] duration-300"
        style={{ width: WIDTHS[mode], maxWidth: '100%' }}
      >
        {children}
      </div>
    </div>
  )
}

export function DeviceModeSwitch({
  mode,
  onChange,
}: {
  mode: DeviceMode
  onChange: (m: DeviceMode) => void
}) {
  const modes: DeviceMode[] = ['mobile', 'tablet', 'desktop']
  return (
    <div className="flex gap-1 rounded-md bg-white/5 p-1 text-xs">
      {modes.map((m) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className={`rounded px-2 py-1 uppercase tracking-wide ${
            mode === m ? 'bg-white/15 text-white' : 'text-white/50 hover:text-white/80'
          }`}
        >
          {m}
        </button>
      ))}
    </div>
  )
}
