import type { Screen } from '../lib/directions'

export function ScreenNav({
  screens,
  activeId,
  onSelect,
}: {
  screens: Screen[]
  activeId: string
  onSelect: (id: string) => void
}) {
  if (screens.length < 2) return null

  return (
    <div className="flex items-center gap-0.5 overflow-x-auto border-b border-white/10 bg-black/20 px-3 text-xs">
      <span className="shrink-0 py-1.5 pr-2 text-[10px] uppercase tracking-wide text-white/30">
        Screens
      </span>
      {screens.map((s) => (
        <button
          key={s.id}
          onClick={() => onSelect(s.id)}
          className={`shrink-0 rounded px-2 py-1 uppercase tracking-wide ${
            activeId === s.id ? 'bg-white/15 text-white' : 'text-white/50 hover:text-white/80'
          }`}
        >
          {s.label}
        </button>
      ))}
    </div>
  )
}
