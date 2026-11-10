import { CircleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import estilos from './AvisoRejeicao.module.css'

type Props = {
  titulo: string
  mensagem: string
  /** Ação opcional abaixo da mensagem (ex.: botão para resolver o problema). */
  children?: ReactNode
}

/** Extrato rejeitado pelo pipeline ou erro ao falar com a API. */
export function AvisoRejeicao({ titulo, mensagem, children }: Props) {
  return (
    <div className={estilos.aviso} role="alert">
      <CircleAlert size={22} className={estilos.icone} aria-hidden="true" />
      <div>
        <strong>{titulo}</strong>
        <p>{mensagem}</p>
        {children && <div className={estilos.acao}>{children}</div>}
      </div>
    </div>
  )
}
