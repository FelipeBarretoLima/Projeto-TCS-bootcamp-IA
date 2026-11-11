// Exportação das transações para planilha (CSV no formato que o Excel em português abre direto).

import type { TransacaoSalva } from '../api/tipos'
import { formataData, rotuloCategoria, rotuloContraparte, rotuloMeio } from './formatacao'

const COLUNAS = ['Data', 'Estabelecimento', 'Descrição', 'Meio', 'Banco', 'Categoria', 'Tipo', 'Valor']

/** Texto vindo do extrato: aspas escapadas e, se começar com = + - @, um apóstrofo na frente para a
 *  planilha não executar como fórmula. */
function texto(valor: string): string {
  const seguro = /^[=+\-@\t\r]/.test(valor) ? `'${valor}` : valor
  return `"${seguro.replace(/"/g, '""')}"`
}

/** "-12.50" -> "-12,50" (vírgula decimal, como o Excel em português espera). */
function numero(valor: string): string {
  return Number(valor).toFixed(2).replace('.', ',')
}

export function geraCsv(transacoes: TransacaoSalva[]): string {
  // o mesmo texto que a tabela mostra: o original (só o dono vê), senão o anonimizado
  const linhas = transacoes.map((t) =>
    [
      formataData(t.data),
      texto(t.contraparte_original || (t.contraparte ? rotuloContraparte(t.contraparte) : '')),
      texto(t.historico_original || t.historico),
      texto(rotuloMeio(t.meio)),
      texto(t.banco),
      texto(t.categoria ? rotuloCategoria(t.categoria) : 'Sem categoria'),
      t.tipo === 'entrada' ? 'Entrada' : 'Saída',
      numero(t.valor),
    ].join(';'),
  )
  // BOM: sem ele o Excel lê os acentos errado
  return '﻿' + [COLUNAS.join(';'), ...linhas].join('\r\n')
}

/** Baixa as transações como arquivo .csv. */
export function baixaCsv(transacoes: TransacaoSalva[], nomeArquivo: string) {
  const url = URL.createObjectURL(new Blob([geraCsv(transacoes)], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = nomeArquivo
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
