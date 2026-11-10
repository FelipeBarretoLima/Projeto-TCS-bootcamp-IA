import type { TransacaoSalva } from '../api/tipos'
import { formataData, formataValor, rotuloContraparte, rotuloMeio } from '../utils/formatacao'
import { BadgeCategoria } from './BadgeCategoria'
import estilos from './TabelaTransacoes.module.css'

type Props = {
  // a importação passa Transacao (com origem), a aba Extrato passa TransacaoSalva: a tabela só usa o comum
  transacoes: TransacaoSalva[]
}

export function TabelaTransacoes({ transacoes }: Props) {
  if (transacoes.length === 0) {
    return <p className={estilos.vazio}>Nenhuma transação para mostrar.</p>
  }

  return (
    <div className={estilos.rolagem}>
      <table className={estilos.tabela}>
        <thead>
          <tr>
            <th scope="col">Data</th>
            <th scope="col">Descrição</th>
            <th scope="col">Categoria</th>
            <th scope="col" className={estilos.numero}>
              Valor
            </th>
          </tr>
        </thead>
        <tbody>
          {transacoes.map((t, i) => (
            <tr key={i}>
              <td className={estilos.data}>{formataData(t.data)}</td>
              <td className={estilos.descricao}>
                <span className={estilos.principal}>
                  {t.contraparte ? rotuloContraparte(t.contraparte) : t.historico}
                </span>
                <span className={estilos.detalhe}>
                  {t.contraparte ? `${t.historico} · ` : ''}
                  {rotuloMeio(t.meio)}
                </span>
              </td>
              <td className={estilos.categoria}>
                <BadgeCategoria categoria={t.categoria} />
              </td>
              <td className={`${estilos.numero} ${estilos[t.tipo]}`}>{formataValor(t.valor)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
