import { Suspense, useState } from 'react'
import { directions } from './lib/directions'
import { DirectionToggle } from './components/DirectionToggle'
import { ScreenNav } from './components/ScreenNav'
import { DeviceFrame, DeviceModeSwitch, type DeviceMode } from './components/DeviceFrame'
import { TweakBar } from './components/TweakBar'

export default function App() {
  const [activeId, setActiveId] = useState(directions[0]?.id ?? '')
  const [activeScreenId, setActiveScreenId] = useState(directions[0]?.screens[0]?.id ?? '')
  const [showAll, setShowAll] = useState(false)
  const [device, setDevice] = useState<DeviceMode>('desktop')

  const active = directions.find((d) => d.id === activeId)
  const activeScreen = active?.screens.find((s) => s.id === activeScreenId) ?? active?.screens[0]

  function selectDirection(id: string) {
    setActiveId(id)
    setShowAll(false)
    setActiveScreenId(directions.find((d) => d.id === id)?.screens[0]?.id ?? '')
  }

  return (
    <div className="flex h-screen flex-col bg-[var(--color-bg)]">
      <DirectionToggle
        directions={directions}
        activeId={activeId}
        showAll={showAll}
        onSelect={selectDirection}
        onToggleAll={() => setShowAll((v) => !v)}
      />

      <div className="flex items-center justify-between border-b border-white/10 bg-black/30 px-3 py-2">
        <span className="text-xs uppercase tracking-wide text-white/40">
          {showAll ? 'All directions' : active?.label ?? 'No direction'}
        </span>
        <DeviceModeSwitch mode={device} onChange={setDevice} />
      </div>

      {!showAll && active && (
        <ScreenNav screens={active.screens} activeId={activeScreenId} onSelect={setActiveScreenId} />
      )}

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <Suspense fallback={<div className="p-12 text-white/40">Loading...</div>}>
            {showAll ? (
              <div className="grid h-full grid-cols-2 gap-4 overflow-auto p-4 lg:grid-cols-3">
                {directions.map((d) => {
                  const Comp = d.screens[0]?.component
                  return (
                    <div
                      key={d.id}
                      onClick={() => selectDirection(d.id)}
                      className="cursor-pointer overflow-hidden rounded border border-white/10 bg-[var(--color-bg)]"
                    >
                      <div className="border-b border-white/10 px-2 py-1 text-[10px] uppercase text-white/40">
                        {d.label}
                      </div>
                      <div className="h-64 overflow-hidden">{Comp && <Comp />}</div>
                    </div>
                  )
                })}
              </div>
            ) : (
              activeScreen && (
                <DeviceFrame mode={device}>
                  <activeScreen.component />
                </DeviceFrame>
              )
            )}
          </Suspense>
        </div>
        <TweakBar />
      </div>
    </div>
  )
}
