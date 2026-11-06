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
  origem_categoria: 'regra' | 'mapa' | null
}

export type ResultadoUpload = {
  relatorio: Relatorio
  transacoes: Transacao[]
  sem_categoria: number
}
