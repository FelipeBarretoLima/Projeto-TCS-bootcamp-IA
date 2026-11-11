// Formato das respostas da API (espelha api/esquemas.py)

export type Saude = {
  status: string
}

export type Relatorio = {
  status: 'aceito' | 'rejeitado'
  motivo: string
  parser: string
  periodo_inicio: string
  periodo_fim: string
  linhas_extraidas: number
  linhas_gravadas: number
  linhas_revisar: number
  linhas_duplicadas: number
  linhas_omitidas: number
  reconciliacao: string
}

export type Transacao = {
  data: string // AAAA-MM-DD
  historico: string
  contraparte: string
  valor: string // decimal como texto, ex.: "-12.50"
  tipo: 'entrada' | 'saida'
  meio: string
  banco: string
  categoria: string | null // uma das 8 classes de ml/classes.py; null = sem categoria
  origem_categoria: 'regra' | 'mapa' | 'modelo' | null
  // como veio no extrato, sem anonimizar (só o dono vê); null = mostra o anonimizado
  historico_original?: string | null
  contraparte_original?: string | null
}

/** Transação gravada na conta (aba Extrato): sem a origem da categoria. */
export type TransacaoSalva = Omit<Transacao, 'origem_categoria'> & { id: number } // id: para corrigir a categoria

/** Datas das transações do usuário e o filtro padrão (últimos 6 meses). null = nenhuma transação. */
export type PeriodoTransacoes = {
  primeira: string | null
  ultima: string | null
  padrao_inicio: string | null
  padrao_fim: string | null
}

export type FiltrosTransacoes = {
  inicio?: string // AAAA-MM-DD, inclusiva
  fim?: string // AAAA-MM-DD, inclusiva
  categoria?: string // uma das 8 categorias ou 'sem_categoria'
}

export type ResultadoUpload = {
  relatorio: Relatorio
  transacoes: Transacao[]
  sem_categoria: number
}

export type ConfigPublica = {
  supabase_url: string
  supabase_publishable_key: string
}

/** O que entrou no banco: as repetidas já estavam lá (extratos com períodos sobrepostos). */
export type Gravacao = {
  extrato_id: string
  gravadas: number
  repetidas: number
}

export type ResultadoImportacao = ResultadoUpload & {
  gravacao: Gravacao | null // null = extrato rejeitado, nada gravado
}

export type ExtratoEnviado = {
  id: string
  nome_arquivo: string
  banco: string
  parser: string
  periodo_inicio: string | null
  periodo_fim: string | null
  linhas_gravadas: number
  enviado_em: string
}

/** Dados de um gráfico (espelha agente/consultas.py); o componente Grafico desenha. */
export type Grafico = {
  tipo: 'barras' | 'barras_horizontais' | 'linha' | 'pizza'
  titulo: string
  rotulos: string[]
  series: { nome: string; valores: number[] }[]
  formato: string
}

export type MesDisponivel = {
  valor: string // "AAAA-MM"
  rotulo: string // "mar/24"
}

export type Painel = {
  tem_dados: boolean
  mes: string | null
  mes_valor: string | null // o mês mostrado, "AAAA-MM"
  meses: MesDisponivel[] // meses com transações, do mais recente ao mais antigo
  receitas: number
  despesas: number
  saldo: number
  grafico: Grafico | null
}

export type Conversa = {
  id: string
  titulo: string
  criada_em: string
  atualizada_em: string
}

export type Mensagem = {
  id: number
  papel: 'usuario' | 'agente'
  texto: string
  grafico: Grafico | null
  criada_em: string
}

export type RespostaChat = {
  conversa_id: string
  pergunta: Mensagem
  resposta: Mensagem
}
