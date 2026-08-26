import { useEffect, useState } from 'react'

/*
  Live design-token tuning panel. Reads/writes CSS custom properties on :root so changes
  apply instantly to whichever direction is showing (see src/tokens.css). "Copy CSS" exports
  the current values as a :root block you can paste back into tokens.css to make a tuning
  session permanent. Add a field here for every token you want tunable by eye instead of by
  re-prompting.
*/

type FieldType = 'toggle' | 'slider'

interface Field {
  key: string // CSS custom property name, e.g. --radius
  label: string
  type: FieldType
  min?: number
  max?: number
  step?: number
  unit?: string
  group: string
}

const FIELDS: Field[] = [
  { key: '--radius', label: 'Radius', type: 'slider', min: 0, max: 32, step: 1, unit: 'px', group: 'Shape' },
  { key: '--gap', label: 'Gap', type: 'slider', min: 0, max: 64, step: 1, unit: 'px', group: 'Shape' },
  { key: '--font-scale', label: 'Font Scale', type: 'slider', min: 0.75, max: 1.5, step: 0.01, group: 'Type' },
  { key: '--motion-on', label: 'Motion', type: 'toggle', group: 'Motion' },
  { key: '--motion-duration', label: 'Weight (Duration x)', type: 'slider', min: 0.25, max: 3, step: 0.05, group: 'Motion' },
  { key: '--reveal-distance', label: 'Reveal Distance', type: 'slider', min: 0, max: 80, step: 1, unit: 'px', group: 'Motion' },
]

function readVar(key: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(key).trim()
}

function writeVar(key: string, value: string) {
  document.documentElement.style.setProperty(key, value)
}

export function TweakBar() {
  const [values, setValues] = useState<Record<string, string>>({})
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const initial: Record<string, string> = {}
    for (const f of FIELDS) initial[f.key] = readVar(f.key)
    setValues(initial)
  }, [])

  function set(key: string, value: string) {
    writeVar(key, value)
    setValues((v) => ({ ...v, [key]: value }))
  }

  function reset() {
    for (const f of FIELDS) document.documentElement.style.removeProperty(f.key)
    const initial: Record<string, string> = {}
    for (const f of FIELDS) initial[f.key] = readVar(f.key)
    setValues(initial)
  }

  async function copyCss() {
    const lines = FIELDS.map((f) => `  ${f.key}: ${values[f.key]};`).join('\n')
    const css = `:root {\n${lines}\n}`
    await navigator.clipboard.writeText(css)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const groups = [...new Set(FIELDS.map((f) => f.group))]

  return (
    <div className="flex h-full w-64 shrink-0 flex-col overflow-y-auto border-l border-white/10 bg-black/60 text-xs text-white">
      <div className="flex-1 p-4">
        {groups.map((group) => (
          <div key={group} className="mb-5">
            <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-white/40">
              + {group}
            </h3>
            <div className="flex flex-col gap-4">
              {FIELDS.filter((f) => f.group === group).map((f) => (
                <div key={f.key}>
                  <div className="mb-1 flex items-center justify-between">
                    <span>{f.label}</span>
                    <span className="text-white/40">
                      {f.type === 'toggle'
                        ? values[f.key] === '1'
                          ? 'ON'
                          : 'OFF'
                        : `${values[f.key] ?? ''}${f.unit ?? ''}`}
                    </span>
                  </div>
                  {f.type === 'toggle' ? (
                    <button
                      onClick={() => set(f.key, values[f.key] === '1' ? '0' : '1')}
                      className={`w-full rounded border px-2 py-1 text-center ${
                        values[f.key] === '1'
                          ? 'border-white/30 bg-white/15'
                          : 'border-white/10 bg-transparent text-white/50'
                      }`}
                    >
                      off / on
                    </button>
                  ) : (
                    <input
                      type="range"
                      min={f.min}
                      max={f.max}
                      step={f.step}
                      value={values[f.key] ?? f.min}
                      onChange={(e) => set(f.key, e.target.value)}
                      className="w-full accent-[var(--color-accent)]"
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-2 border-t border-white/10 p-4">
        <button
          onClick={copyCss}
          className="flex-1 rounded bg-white/10 py-2 uppercase tracking-wide hover:bg-white/20"
        >
          {copied ? 'Copied' : 'Copy CSS'}
        </button>
        <button
          onClick={reset}
          className="flex-1 rounded bg-white/10 py-2 uppercase tracking-wide hover:bg-white/20"
        >
          Reset
        </button>
      </div>
    </div>
  )
}
