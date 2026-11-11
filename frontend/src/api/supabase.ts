// Cliente do Supabase Auth (login). A configuração pública vem da API (/api/config), que lê o .env
// da raiz: assim o frontend não precisa de um .env próprio.

import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import type { ConfigPublica } from './tipos'

export class LoginNaoConfigurado extends Error {}

/**
 * Retorno de um link enviado por e-mail (ex.: recuperar senha). O Supabase devolve os tokens no
 * `#` da URL; eles são lidos aqui, quando o módulo carrega, porque o roteador troca a URL (e apaga
 * o `#`) antes de o cliente ficar pronto.
 */
const hashInicial = new URLSearchParams(window.location.hash.slice(1))
export const retornoDoLink = {
  /** 'recovery' quando a pessoa chegou pelo link de recuperar senha. */
  tipo: hashInicial.get('type'),
  /** Link vencido ou já usado. */
  invalido: hashInicial.has('error'),
}
if (hashInicial.has('access_token') || hashInicial.has('error')) {
  // tira os tokens da barra de endereço (e do histórico)
  history.replaceState(null, '', window.location.pathname + window.location.search)
}

let promessa: Promise<SupabaseClient> | null = null

export function supabase(): Promise<SupabaseClient> {
  promessa ??= (async () => {
    const resposta = await fetch('/api/config')
    if (!resposta.ok) throw new LoginNaoConfigurado('A API não está respondendo.')
    const config = (await resposta.json()) as ConfigPublica
    if (!config.supabase_url || !config.supabase_publishable_key) {
      throw new LoginNaoConfigurado(
        'Login não configurado: preencha SUPABASE_PUBLISHABLE_KEY no .env da raiz e reinicie a API.',
      )
    }
    const cliente = createClient(config.supabase_url, config.supabase_publishable_key, {
      // a URL já foi lida e limpa acima: a sessão do link é aberta à mão logo abaixo
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
    })
    const access_token = hashInicial.get('access_token')
    const refresh_token = hashInicial.get('refresh_token')
    if (access_token && refresh_token) {
      const { error } = await cliente.auth.setSession({ access_token, refresh_token })
      if (error) retornoDoLink.invalido = true
    }
    return cliente
  })().catch((erro) => {
    promessa = null // deixa tentar de novo depois (ex.: a API ainda estava subindo)
    throw erro
  })
  return promessa
}

/** Token da sessão atual, para mandar à API. null = ninguém logado. */
export async function tokenAtual(): Promise<string | null> {
  const cliente = await supabase()
  const { data } = await cliente.auth.getSession()
  return data.session?.access_token ?? null
}
