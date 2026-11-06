import { FileText } from 'lucide-react'
import type { Relatorio } from '../api/tipos'
import { plural } from '../utils/formatacao'
import estilos from './ArquivoProcessado.module.css'

type Props = {
  nome: string
  relatorio: Relatorio
}

export function ArquivoProcessado({ nome, relatorio }: Props) {
  const aceito = relatorio.status === 'aceito'
  const n = relatorio.linhas_gravadas

  return (
    <div className={estilos.arquivo}>
      <FileText size={22} className={estilos.icone} aria-hidden="true" />
      <span className={estilos.nome}>{nome}</span>
      <span className={aceito ? estilos.aceito : estilos.rejeitado}>
        {aceito ? plural(n, 'transação extraída', 'transações extraídas') : 'Extrato rejeitado'}
      </span>
    </div>
  )
}
