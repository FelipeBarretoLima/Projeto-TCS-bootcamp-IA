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

export type Painel = {
  tem_dados: boolean
  mes: string | null
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
