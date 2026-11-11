// Sessão do usuário (Supabase Auth) disponível para o app inteiro.

import type { SupabaseClient } from '@supabase/supabase-js'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { apagaContaNaApi, encerraSessaoNaApi, mudaNomeNaApi, quandoSessaoExpirar } from '../api/cliente'
import { retornoDoLink, supabase } from '../api/supabase'
import { ContextoAuth, type Contexto, type Estado } from './contextoAuth'

/** Mensagens do Supabase Auth em português (as que o usuário costuma ver). */
function traduz(mensagem: string): string {
  const m = mensagem.toLowerCase()
  if (m.includes('invalid login credentials')) return 'E-mail ou senha incorretos.'
  if (m.includes('email not confirmed')) return 'Confirme o seu e-mail antes de entrar (veja a caixa de entrada).'
  if (m.includes('already registered')) return 'Já existe uma conta com este e-mail.'
  // antes de "password should be": "New password should be different from the old password" também casa com ele
  if (m.includes('should be different')) return 'Essa senha já está sendo usada. Escolha uma senha diferente da atual.'
  if (m.includes('password should be')) return 'A senha precisa ter pelo menos 6 caracteres.'
  if (m.includes('rate limit')) return 'Muitas tentativas seguidas. Espere alguns minutos e tente de novo.'
  if (m.includes('expired') || (m.includes('invalid') && m.includes('token'))) return 'Código inválido ou expirado.'
  if (m.includes('invalid') && m.includes('email')) return 'E-mail inválido.'
  return mensagem
}

export function ProvedorAutenticacao({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState<Estado>({ fase: 'carregando' })
  const [cliente, setCliente] = useState<SupabaseClient | null>(null)
  const escuta = useRef<{ unsubscribe: () => void } | null>(null)

  useEffect(() => {
    const efeito = { ativo: true } // false depois que o componente sai da tela
    supabase()
      .then(async (c) => {
        setCliente(c)
        const { data: atual } = await c.auth.getSession()
        setEstado({ fase: 'pronto', sessao: atual.session })
        const { data } = c.auth.onAuthStateChange((_evento, sessao) => setEstado({ fase: 'pronto', sessao }))
        if (efeito.ativo) escuta.current = data.subscription
        else data.subscription.unsubscribe()
      })
      .catch((erro: Error) => setEstado({ fase: 'indisponivel', motivo: erro.message }))
    return () => {
      efeito.ativo = false
      escuta.current?.unsubscribe()
    }
  }, [])

  useEffect(() => {
    quandoSessaoExpirar(() => void cliente?.auth.signOut())
  }, [cliente])

  const exige = () => {
    if (!cliente) throw new Error('O login ainda não está disponível.')
    return cliente
  }

  const valor: Contexto = {
    estado,
    nome:
      estado.fase === 'pronto'
        ? (estado.sessao?.user.user_metadata?.nome as string | undefined) ?? ''
        : '',
    email: estado.fase === 'pronto' ? (estado.sessao?.user.email ?? '') : '',
    async entra(email, senha) {
      const { error } = await exige().auth.signInWithPassword({ email, password: senha })
      if (error) throw new Error(traduz(error.message))
    },
    async cadastra(nome, email, senha) {
      const { data, error } = await exige().auth.signUp({
        email,
        password: senha,
        options: { data: { nome } },
      })
      if (error) throw new Error(traduz(error.message))
      return data.session ? 'logado' : 'confirmar_email'
    },
    async recupera(email) {
      const { error } = await exige().auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/redefinir-senha`,
      })
      if (error) throw new Error(traduz(error.message))
    },
    async trocaSenha(senha) {
      const { error } = await exige().auth.updateUser({ password: senha })
      if (error) throw new Error(traduz(error.message))
    },
    async mudaNome(nome) {
      await mudaNomeNaApi(nome)
      const { error } = await exige().auth.updateUser({ data: { nome } })
      if (error) throw new Error(traduz(error.message))
    },
    async apagaConta() {
      await apagaContaNaApi()
      retornoDoLink.tipo = null
      // a conta já não existe: só limpa a sessão guardada neste navegador
      await cliente?.auth.signOut({ scope: 'local' })
    },
    async sai() {
      retornoDoLink.tipo = null // um login novo nesta aba não volta para "criar senha nova"
      await encerraSessaoNaApi()
      await cliente?.auth.signOut()
    },
  }

  return <ContextoAuth.Provider value={valor}>{children}</ContextoAuth.Provider>
}
