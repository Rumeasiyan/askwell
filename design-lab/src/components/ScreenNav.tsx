import type { Screen } from '../lib/directions'

/*
  Left sidebar rather than a top bar: a direction with thirty-odd screens is unusable as a
  horizontal scroller. Screens are grouped by the "Group · Name" convention in their label —
  anything before the first "·" becomes a heading.
*/
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

  const groups: { name: string; items: Screen[] }[] = []
  for (const s of screens) {
    const [head, ...rest] = s.label.split('·').map((p) => p.trim())
    const name = rest.length ? head : ''
    const last = groups[groups.length - 1]
    if (last && last.name === name) last.items.push(s)
    else groups.push({ name, items: [s] })
  }

  return (
    <nav className="flex w-[210px] shrink-0 flex-col overflow-y-auto border-r border-white/10 bg-black/25">
      <div className="sticky top-0 border-b border-white/10 bg-black/40 px-3 py-2 text-[10px] uppercase tracking-wide text-white/30">
        {screens.length} screens
      </div>
      <div className="flex flex-col gap-3 p-2">
        {groups.map((g, i) => (
          <div key={`${g.name}-${i}`} className="flex flex-col gap-px">
            {g.name && (
              <div className="px-2 pb-1 pt-1 text-[10px] uppercase tracking-wide text-white/25">{g.name}</div>
            )}
            {g.items.map((s) => {
              const short = s.label.includes('·') ? s.label.split('·').slice(1).join('·').trim() : s.label
              return (
                <button
                  key={s.id}
                  onClick={() => onSelect(s.id)}
                  className={`rounded px-2 py-1 text-left text-xs ${
                    activeId === s.id ? 'bg-white/15 text-white' : 'text-white/50 hover:bg-white/5 hover:text-white/80'
                  }`}
                >
                  {short}
                </button>
              )
            })}
          </div>
        ))}
      </div>
    </nav>
  )
}
