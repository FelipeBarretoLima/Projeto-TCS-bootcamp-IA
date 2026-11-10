// Tema claro/escuro: o padrão é o claro; o escuro só vale quando o usuário escolhe no botão.
// (Não segue o tema do sistema.) A escolha fica salva no navegador.

import { useEffect, useState } from 'react'

export type Tema = 'claro' | 'escuro'

// chave nova: a antiga ('tas-tema') guardava o tema do sistema mesmo sem o usuário escolher
const CHAVE = 'tas-tema-escolhido'

function temaInicial(): Tema {
  try {
    return localStorage.getItem(CHAVE) === 'escuro' ? 'escuro' : 'claro'
  } catch {
    return 'claro'
  }
}

export function useTema() {
  const [tema, setTema] = useState<Tema>(temaInicial)

  useEffect(() => {
    document.documentElement.dataset.tema = tema
  }, [tema])

  const alterna = () => {
    const novo: Tema = tema === 'claro' ? 'escuro' : 'claro'
    setTema(novo)
    try {
      localStorage.setItem(CHAVE, novo) // só grava quando o usuário escolhe
    } catch {
      // sem localStorage: o tema vale só até recarregar a página
    }
  }
  return { tema, alterna }
}
