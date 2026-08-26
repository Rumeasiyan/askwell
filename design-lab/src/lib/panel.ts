/*
  Whether the app's own side panel is open. Below the breakpoint the rail is hidden, so
  something has to open it — otherwise sources, clarifications, memory and settings are
  unreachable on a narrow window.

  A tiny store rather than prop-drilling through 37 screens: Chrome renders the control,
  Rail reads the state, and neither has to know about the other.
*/
import { useSyncExternalStore } from 'react'

let open = false
const listeners = new Set<() => void>()

function emit() {
  for (const l of listeners) l()
}

export function setPanelOpen(v: boolean) {
  open = v
  emit()
}

export function togglePanel() {
  setPanelOpen(!open)
}

export function usePanelOpen() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => {
        listeners.delete(l)
      }
    },
    () => open,
    () => false,
  )
}
