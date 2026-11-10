// Formatação para exibição (datas, valores e códigos da API em português)

const moeda = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })

export function formataValor(valor: string): string {
  return moeda.format(Number(valor))
}

/** "2024-01-02" -> "02/01/2024" (sem passar por Date, para não sofrer com fuso) */
export function formataData(iso: string): string {
  const [ano, mes, dia] = iso.split('-')
  return ano && mes && dia ? `${dia}/${mes}/${ano}` : iso
}

const MEIOS: Record<string, string> = {
  pix: 'Pix',
  ted_doc: 'TED/DOC',
  boleto: 'Boleto',
  cartao_debito: 'Cartão de débito',
  cartao_credito: 'Cartão de crédito',
  pagamento_fatura: 'Pagamento de fatura',
  tarifa: 'Tarifa',
  juros_iof: 'Juros/IOF',
  investimento: 'Investimento',
  rendimento: 'Rendimento',
  salario: 'Salário',
  saque: 'Saque',
  estorno: 'Estorno',
  transferencia_interna: 'Transferência interna',
  outros: 'Outros',
}

export function rotuloMeio(meio: string): string {
  return MEIOS[meio] ?? meio
}

/** A anonimização troca o nome de pessoas por este marcador (extrato.modelos.PESSOA_FISICA). */
const PESSOA_FISICA = 'PESSOA_FISICA'

export function rotuloContraparte(contraparte: string): string {
  return contraparte === PESSOA_FISICA ? 'Pessoa física' : contraparte
}

const CATEGORIAS: Record<string, string> = {
  mercado: 'Mercado',
  alimentacao_fora: 'Alimentação fora',
  transporte: 'Transporte',
  compras: 'Compras',
  contas_servicos: 'Contas e serviços',
  transferencia_pessoa: 'Transferência p/ pessoa',
  receitas: 'Receitas',
  financeiro: 'Financeiro',
}

export function rotuloCategoria(categoria: string): string {
  return CATEGORIAS[categoria] ?? categoria
}

/** As 8 categorias na ordem de exibição: [código, rótulo] (filtro da aba Extrato). */
export const LISTA_CATEGORIAS = Object.entries(CATEGORIAS)

/** "1 transação", "3 transações" */
export function plural(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`
}

// um parser por formato (extracao/src/extrato/parsers/registro.py)
const FORMATOS: Record<string, string> = {
  bradesco_cartao_pdf: 'Bradesco · cartão (PDF)',
  bradesco_conta_pdf: 'Bradesco · conta (PDF)',
  inter_conta_pdf: 'Inter · conta (PDF)',
  nubank_conta_csv: 'Nubank · conta (CSV)',
  nubank_conta_pdf: 'Nubank · conta (PDF)',
  nubank_fatura_pdf: 'Nubank · fatura (PDF)',
  santander_cartao_pdf: 'Santander · cartão (PDF)',
  sicoob_conta_pdf: 'Sicoob · conta (PDF)',
}

export function rotuloFormato(parser: string): string {
  return FORMATOS[parser] ?? parser
}

const SUPORTADOS =
  'Bradesco (conta e cartão), Inter (conta), Nubank (conta em PDF ou CSV e fatura), ' +
  'Santander (cartão) e Sicoob (conta)'

const RECONCILIACAO: Record<string, string> = {
  ok: 'Totais conferidos',
  ok_com_documentos_rejeitados: 'Totais conferidos (alguns documentos rejeitados)',
  sem_totais: 'Formato sem totais para conferir',
  falhou: 'Totais não conferem',
  nao_executada: 'Não executada',
}

export function rotuloReconciliacao(codigo: string): string {
  return RECONCILIACAO[codigo] ?? codigo
}

// cada motivo diz o problema e o que fazer em seguida
const ENVIE_ORIGINAL = 'Envie o arquivo original exportado pelo banco, sem editar nem converter.'

const MOTIVOS: Record<string, string> = {
  FormatoNaoReconhecido: `Este arquivo não é de um formato suportado. Hoje o TAS lê ${SUPORTADOS}. ${ENVIE_ORIGINAL}`,
  FormatoAmbiguo: `O arquivo parece com mais de um formato conhecido e não dá para escolher com segurança. ${ENVIE_ORIGINAL}`,
  HistoricoDesconhecido:
    'O extrato tem tipos de lançamento que o TAS ainda não conhece. Ele não foi processado para não errar a anonimização; avise a equipe para incluir esses tipos.',
  ReconciliacaoFalhou: `A soma dos lançamentos não bate com os totais do próprio extrato, então o resultado não seria confiável. ${ENVIE_ORIGINAL}`,
  erro_no_parser: `Houve um erro ao ler o arquivo. ${ENVIE_ORIGINAL} Se o erro continuar, avise a equipe.`,
  linhas_invalidas: 'Algumas linhas lidas não passaram na validação. Avise a equipe para conferir este formato.',
  segmentos_em_formato_sem_totais: 'O arquivo tem uma estrutura inesperada para este formato. Avise a equipe.',
}

/** Motivo da rejeição em português, com o próximo passo; códigos sem tradução aparecem como vêm. */
export function rotuloMotivo(motivo: string): string {
  const codigo = motivo.split(':')[0]
  if (codigo === 'LayoutInesperado') {
    return `O arquivo tem algo fora do layout que o TAS conhece (${motivo}). ${ENVIE_ORIGINAL}`
  }
  return MOTIVOS[codigo] ?? motivo
}

/** 1234.5 -> "R$ 1.234,50" */
export function formataMoeda(valor: number): string {
  return moeda.format(valor)
}

/** 1234.5 -> "R$ 1,2 mil" (eixos de gráfico, onde não cabe o valor inteiro) */
const compacto = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  notation: 'compact',
  maximumFractionDigits: 1,
})
export function formataMoedaCurta(valor: number): string {
  return compacto.format(valor)
}
