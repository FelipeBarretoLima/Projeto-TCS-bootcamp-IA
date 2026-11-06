import type { Relatorio } from '../api/tipos'
import { formataData, plural, rotuloFormato, rotuloReconciliacao } from '../utils/formatacao'
import estilos from './ResumoExtracao.module.css'

type Props = {
  relatorio: Relatorio
  semCategoria: number
}

/** Dados do extrato aceito, numa linha sob o título da tabela. */
export function ResumoExtracao({ relatorio, semCategoria }: Props) {
  const periodo = relatorio.periodo_inicio
    ? `${formataData(relatorio.periodo_inicio)} a ${formataData(relatorio.periodo_fim)}`
    : '-'

  const itens = [
    ['Formato', rotuloFormato(relatorio.parser)],
    ['Período', periodo],
    ['Conferência', rotuloReconciliacao(relatorio.reconciliacao)],
    ['Sem categoria', String(semCategoria)],
    ['Em revisão', String(relatorio.linhas_revisar)],
  ]

  return (
    <div>
      <dl className={estilos.dados}>
        {itens.map(([rotulo, valor]) => (
          <div key={rotulo}>
            <dt>{rotulo}</dt>
            <dd>{valor}</dd>
          </div>
        ))}
      </dl>
      {relatorio.linhas_revisar > 0 && (
        <p className={estilos.aviso}>
          {relatorio.linhas_revisar === 1
            ? '1 lançamento ficou fora da tabela'
            : `${plural(relatorio.linhas_revisar, 'lançamento', 'lançamentos')} ficaram fora da tabela`}{' '}
          porque não foi possível garantir a anonimização da contraparte.
        </p>
      )}
    </div>
  )
}
