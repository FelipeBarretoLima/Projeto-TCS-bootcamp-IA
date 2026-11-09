// Cliente do Supabase Auth (login). A configuração pública vem da API (/api/config), que lê o .env
// da raiz: assim o frontend não precisa de um .env próprio.

import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import type { ConfigPublica } from './tipos'

export class LoginNaoConfigurado extends Error {}

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
    return createClient(config.supabase_url, config.supabase_publishable_key, {
      auth: { persistSession: true, autoRefreshToken: true },
    })
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
