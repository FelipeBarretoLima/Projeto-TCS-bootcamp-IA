// Todas as chamadas à API ficam aqui. O proxy do Vite repassa /api para o FastAPI.

import type { ResultadoUpload, Saude } from './tipos'

export class ErroApi extends Error {}

async function trataResposta<T>(resposta: Response): Promise<T> {
  if (resposta.ok) return (await resposta.json()) as T
  if (resposta.status === 502 || resposta.status === 504) {
    throw new ErroApi(
      'A API não está respondendo. Inicie a API na raiz do projeto (passo a passo no README, em "Rodar a página") e tente de novo.',
    )
  }
  // erros da API vêm como {"detail": "mensagem"}
  const corpo = await resposta.json().catch(() => null)
  const detalhe = typeof corpo?.detail === 'string' ? corpo.detail : null
  throw new ErroApi(detalhe ?? `Erro inesperado da API (HTTP ${resposta.status})`)
}

export async function verificaSaude(): Promise<Saude> {
  return trataResposta<Saude>(await fetch('/api/saude'))
}

export async function enviaExtrato(arquivo: File, usuario?: string): Promise<ResultadoUpload> {
  const formulario = new FormData()
  formulario.append('arquivo', arquivo)
  if (usuario) formulario.append('usuario', usuario)
  const resposta = await fetch('/api/extratos', { method: 'POST', body: formulario })
  return trataResposta<ResultadoUpload>(resposta)
}
