import type { Transacao } from '../api/tipos'
import { LISTA_CATEGORIAS, formataData, formataValor, rotuloContraparte, rotuloMeio } from '../utils/formatacao'
import { BadgeCategoria } from './BadgeCategoria'
import estilos from './TabelaTransacoes.module.css'

/** O comum à importação (Transacao, sem id) e à aba Extrato (TransacaoSalva, com id). */
type Linha = Omit<Transacao, 'origem_categoria'> & { id?: number }

type Props<T extends Linha> = {
  transacoes: T[]
  /** Com esta função, a categoria vira um seletor para o usuário corrigir (null = sem categoria). */
  onMudaCategoria?: (transacao: T, categoria: string | null) => void
  /** Ids das transações cuja categoria está sendo gravada (seletor desativado). */
  salvando?: ReadonlySet<number>
}

export function TabelaTransacoes<T extends Linha>({ transacoes, onMudaCategoria, salvando }: Props<T>) {
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
          {transacoes.map((t, i) => {
            // o texto original (sem anonimizar) quando a API o tiver; senão, o anonimizado
            const nome = t.contraparte_original || (t.contraparte ? rotuloContraparte(t.contraparte) : '')
            const historico = t.historico_original || t.historico
            const descricao = nome || historico
            return (
              <tr key={t.id ?? i}>
                <td className={estilos.data}>{formataData(t.data)}</td>
                <td className={estilos.descricao}>
                  <span className={estilos.principal}>{descricao}</span>
                  <span className={estilos.detalhe}>
                    {nome ? `${historico} · ` : ''}
                    {rotuloMeio(t.meio)}
                  </span>
                </td>
                <td className={estilos.categoria}>
                  {onMudaCategoria && t.id !== undefined ? (
                    <select
                      className={t.categoria ? estilos.seletor : `${estilos.seletor} ${estilos.seletorVazio}`}
                      value={t.categoria ?? ''}
                      onChange={(e) => onMudaCategoria(t, e.target.value || null)}
                      disabled={salvando?.has(t.id)}
                      aria-label={`Categoria de ${descricao} em ${formataData(t.data)}`}
                      title="Corrigir a categoria"
                    >
                      {LISTA_CATEGORIAS.map(([codigo, rotulo]) => (
                        <option key={codigo} value={codigo}>
                          {rotulo}
                        </option>
                      ))}
                      <option value="">Sem categoria</option>
                    </select>
                  ) : (
                    <BadgeCategoria categoria={t.categoria} />
                  )}
                </td>
                <td className={`${estilos.numero} ${estilos[t.tipo]}`}>{formataValor(t.valor)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
