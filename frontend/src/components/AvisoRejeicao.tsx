import { CircleAlert } from 'lucide-react'
import estilos from './AvisoRejeicao.module.css'

type Props = {
  titulo: string
  mensagem: string
}

/** Extrato rejeitado pelo pipeline ou erro ao falar com a API. */
export function AvisoRejeicao({ titulo, mensagem }: Props) {
  return (
    <div className={estilos.aviso} role="alert">
      <CircleAlert size={22} className={estilos.icone} aria-hidden="true" />
      <div>
        <strong>{titulo}</strong>
        <p>{mensagem}</p>
      </div>
    </div>
  )
}
