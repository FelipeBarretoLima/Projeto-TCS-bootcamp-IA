import { useEffect, useState } from 'react'
import { verificaSaude } from '../api/cliente'
import estilos from './StatusApi.module.css'

type Estado = 'carregando' | 'ok' | 'erro'

const TEXTOS: Record<Estado, string> = {
  carregando: 'Verificando a API...',
  ok: 'API conectada',
  erro: 'API indisponível',
}

export function StatusApi() {
  const [estado, setEstado] = useState<Estado>('carregando')

  useEffect(() => {
    verificaSaude()
      .then((dados) => setEstado(dados.status === 'ok' ? 'ok' : 'erro'))
      .catch(() => setEstado('erro'))
  }, [])

  return (
    <span className={`${estilos.status} ${estilos[estado]}`} role="status" title={TEXTOS[estado]}>
      <span className={estilos.ponto} aria-hidden="true" />
      <span className={estilos.rotulo}>{TEXTOS[estado]}</span>
    </span>
  )
}
