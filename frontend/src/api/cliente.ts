// Todas as chamadas à API ficam aqui. O proxy do Vite repassa /api para o FastAPI.
// As rotas com login recebem o token do Supabase no cabeçalho Authorization.

import { tokenAtual } from './supabase'
import type {
  Conversa,
  ExtratoEnviado,
  Mensagem,
  Painel,
  RespostaChat,
  ResultadoImportacao,
  Saude,
} from './tipos'

export class ErroApi extends Error {
  status: number

  constructor(mensagem: string, status = 0) {
    super(mensagem)
    this.status = status
  }
}

/** Avisado quando a API responde 401 (sessão expirada): o app volta para o login. */
let aoExpirar: (() => void) | null = null
export function quandoSessaoExpirar(acao: () => void) {
  aoExpirar = acao
}

async function trataResposta<T>(resposta: Response): Promise<T> {
  if (resposta.ok) return (resposta.status === 204 ? undefined : await resposta.json()) as T
  if (resposta.status === 502 || resposta.status === 504) {
    // 502 com corpo JSON é erro da própria API (ex.: o assistente falhou); sem corpo, a API está fora
    const corpo = await resposta.json().catch(() => null)
    if (typeof corpo?.detail === 'string') throw new ErroApi(corpo.detail, resposta.status)
    throw new ErroApi(
      'A API não está respondendo. Inicie a API na raiz do projeto (passo a passo no README, em "Rodar a página") e tente de novo.',
      resposta.status,
    )
  }
  if (resposta.status === 401) aoExpirar?.()
  // erros da API vêm como {"detail": "mensagem"}
  const corpo = await resposta.json().catch(() => null)
  const detalhe = typeof corpo?.detail === 'string' ? corpo.detail : null
  throw new ErroApi(detalhe ?? `Erro inesperado da API (HTTP ${resposta.status})`, resposta.status)
}

async function chama<T>(caminho: string, opcoes: RequestInit = {}): Promise<T> {
  const token = await tokenAtual()
  const cabecalhos = new Headers(opcoes.headers)
  if (token) cabecalhos.set('Authorization', `Bearer ${token}`)
  return trataResposta<T>(await fetch(caminho, { ...opcoes, headers: cabecalhos }))
}

export async function verificaSaude(): Promise<Saude> {
  return trataResposta<Saude>(await fetch('/api/saude'))
}

export async function enviaExtrato(arquivo: File): Promise<ResultadoImportacao> {
  const formulario = new FormData()
  formulario.append('arquivo', arquivo)
  return chama<ResultadoImportacao>('/api/extratos', { method: 'POST', body: formulario })
}

export const listaExtratos = () => chama<ExtratoEnviado[]>('/api/extratos')
export const apagaExtrato = (id: string) => chama<void>(`/api/extratos/${id}`, { method: 'DELETE' })

export const buscaPainel = () => chama<Painel>('/api/painel')

export const listaConversas = () => chama<Conversa[]>('/api/conversas')
export const buscaMensagens = (id: string) => chama<Mensagem[]>(`/api/conversas/${id}/mensagens`)
export const apagaConversa = (id: string) => chama<void>(`/api/conversas/${id}`, { method: 'DELETE' })

export function pergunta(mensagem: string, conversaId: string | null): Promise<RespostaChat> {
  return chama<RespostaChat>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mensagem, conversa_id: conversaId }),
  })
}
