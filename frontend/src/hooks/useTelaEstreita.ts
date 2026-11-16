// true quando a tela é de celular (até 720px, o mesmo limite dos @media dos .module.css).
// Serve para o que não dá para ajustar só com CSS, como as medidas dos gráficos do Recharts.

import { useSyncExternalStore } from 'react'

const CONSULTA = '(max-width: 720px)'

function assina(avisa: () => void) {
  const lista = window.matchMedia(CONSULTA)
  lista.addEventListener('change', avisa)
  return () => lista.removeEventListener('change', avisa)
}

const estado = () => window.matchMedia(CONSULTA).matches

export function useTelaEstreita(): boolean {
  return useSyncExternalStore(assina, estado, () => false)
}
