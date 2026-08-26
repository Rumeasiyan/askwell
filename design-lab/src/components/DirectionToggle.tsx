import { useEffect, useState } from 'react'
import type { Direction } from '../lib/directions'

export function DirectionToggle({
  directions,
  activeId,
  showAll,
  onSelect,
  onToggleAll,
}: {
  directions: Direction[]
  activeId: string
  showAll: boolean
  onSelect: (id: string) => void
  onToggleAll: () => void
}) {
  const [query, setQuery] = useState('')

  // number-key shortcuts (1-9) select a direction, G toggles grid/"all" view
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return
      if (e.key.toLowerCase() === 'g') {
        onToggleAll()
        return
      }
      const match = directions.find((d) => d.key === e.key)
      if (match) onSelect(match.id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [directions, onSelect, onToggleAll])

  const q = query.trim().toLowerCase()
  const filtered = q
    ? directions.filter((d) => `${d.label} ${d.sub ?? ''}`.toLowerCase().includes(q))
    : directions

  return (
    <div className="flex items-center gap-0.5 overflow-x-auto border-b border-white/10 bg-black/40 px-2 text-xs">
      <span className="shrink-0 px-2 py-2 font-semibold uppercase tracking-wide text-white/40">
        {directions.length} Directions
      </span>
      {directions.length > 6 && (
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter..."
          className="mx-1 w-28 shrink-0 rounded border border-white/10 bg-white/5 px-2 py-1 text-white placeholder:text-white/30 focus:outline-none"
        />
      )}
      {filtered.length === 0 ? (
        <span className="shrink-0 px-2 py-2 text-white/30">No matches</span>
      ) : (
        filtered.map((d) => (
          <button
            key={d.id}
            onClick={() => onSelect(d.id)}
            className={`flex shrink-0 flex-col items-start border-r border-white/10 px-3 py-2 text-left ${
              !showAll && activeId === d.id
                ? 'bg-white/15 text-white'
                : 'text-white/50 hover:text-white/80'
            }`}
          >
            <span className="font-semibold uppercase">{d.label}</span>
            {d.sub && <span className="text-[10px] uppercase text-white/40">{d.sub}</span>}
          </button>
        ))
      )}
      <button
        onClick={onToggleAll}
        className={`ml-auto shrink-0 px-3 py-2 font-semibold uppercase tracking-wide ${
          showAll ? 'bg-white/15 text-white' : 'text-white/50 hover:text-white/80'
        }`}
      >
        All {directions.length}
      </button>
      <span className="shrink-0 px-2 py-2 text-[10px] uppercase text-white/30">
        Keys 1-9 · G = Grid
      </span>
    </div>
  )
}
