// Tema claro/escuro: começa pela preferência do sistema e lembra a escolha do usuário.

import { useEffect, useState } from 'react'

export type Tema = 'claro' | 'escuro'

const CHAVE = 'tas-tema'

function temaInicial(): Tema {
  const salvo = localStorage.getItem(CHAVE)
  if (salvo === 'claro' || salvo === 'escuro') return salvo
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'escuro' : 'claro'
}

export function useTema() {
  const [tema, setTema] = useState<Tema>(temaInicial)

  useEffect(() => {
    document.documentElement.dataset.tema = tema
    localStorage.setItem(CHAVE, tema)
  }, [tema])

  const alterna = () => setTema((t) => (t === 'claro' ? 'escuro' : 'claro'))
  return { tema, alterna }
}
