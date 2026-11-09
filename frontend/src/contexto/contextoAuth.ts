// Contexto da sessão (separado do provedor para o Fast Refresh do Vite funcionar).

import type { Session } from '@supabase/supabase-js'
import { createContext, useContext } from 'react'

export type Estado =
  | { fase: 'carregando' }
  | { fase: 'indisponivel'; motivo: string }
  | { fase: 'pronto'; sessao: Session | null }

export type Contexto = {
  estado: Estado
  nome: string
  entra: (email: string, senha: string) => Promise<void>
  cadastra: (nome: string, email: string, senha: string) => Promise<'logado' | 'confirmar_email'>
  recupera: (email: string) => Promise<void>
  sai: () => Promise<void>
}

export const ContextoAuth = createContext<Contexto | null>(null)

export function useAutenticacao(): Contexto {
  const contexto = useContext(ContextoAuth)
  if (!contexto) throw new Error('useAutenticacao fora do ProvedorAutenticacao')
  return contexto
}
