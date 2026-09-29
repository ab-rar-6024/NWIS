import { createContext, ReactNode, useContext, useState } from 'react'

interface UiModeCtx {
  simple: boolean
  setSimple: (v: boolean) => void
}

const Ctx = createContext<UiModeCtx>({ simple: true, setSimple: () => undefined })
export const useUiMode = () => useContext(Ctx)

const KEY = 'nwis_simple_mode'

function readInitial(): boolean {
  try {
    const v = localStorage.getItem(KEY)
    return v === null ? true : v === '1'
  } catch {
    return true
  }
}

/** Simple mode is the default for everyone: a first-time viewer should understand the page without a glossary.
 *  Technical mode reveals the same underlying data in full depth for judges who want to verify the rigor. */
export function UiModeProvider({ children }: { children: ReactNode }) {
  const [simple, setSimpleState] = useState(readInitial)
  const setSimple = (v: boolean) => {
    setSimpleState(v)
    try {
      localStorage.setItem(KEY, v ? '1' : '0')
    } catch {
      /* private browsing or storage disabled: mode just won't persist across reloads */
    }
  }
  return <Ctx.Provider value={{ simple, setSimple }}>{children}</Ctx.Provider>
}
