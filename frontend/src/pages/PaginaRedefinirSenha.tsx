// Tela aberta pelo link "Reset password" do e-mail: o link já abriu a sessão, falta a senha nova.

import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { retornoDoLink } from '../api/supabase'
import { MolduraAcesso } from '../components/MolduraAcesso'
import { useAutenticacao } from '../contexto/contextoAuth'
import estilos from './PaginaLogin.module.css'

export function PaginaRedefinirSenha() {
  const { estado, trocaSenha, sai } = useAutenticacao()
  const navegar = useNavigate()
  const [senha, setSenha] = useState('')
  const [confirmacao, setConfirmacao] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  if (estado.fase === 'carregando') {
    return (
      <MolduraAcesso titulo="Criar senha nova" subtitulo="Conferindo o link do e-mail…">
        {null}
      </MolduraAcesso>
    )
  }

  if (estado.fase === 'indisponivel' || !estado.sessao || retornoDoLink.invalido) {
    return (
      <MolduraAcesso
        titulo="Link inválido ou expirado"
        subtitulo="O link de recuperação vence depois de um tempo e só pode ser usado uma vez. Peça um novo."
      >
        {estado.fase === 'indisponivel' && (
          <p className={estilos.erro} role="alert">
            {estado.motivo}
          </p>
        )}
        <p className={estilos.links}>
          <Link to="/login">Voltar ao login</Link>
        </p>
      </MolduraAcesso>
    )
  }

  async function envia(evento: FormEvent) {
    evento.preventDefault()
    setErro(null)
    if (senha !== confirmacao) {
      setErro('As duas senhas não são iguais.')
      return
    }
    setEnviando(true)
    try {
      await trocaSenha(senha)
      retornoDoLink.tipo = null // recuperação concluída
      navegar('/importar', { replace: true })
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não foi possível salvar a senha. Tente de novo.')
    } finally {
      setEnviando(false)
    }
  }

  async function cancela() {
    // o link abriu uma sessão: fecha antes de voltar ao login
    retornoDoLink.tipo = null
    await sai()
    navegar('/login', { replace: true })
  }

  return (
    <MolduraAcesso titulo="Criar senha nova" subtitulo={`Escolha a senha nova para ${estado.sessao.user.email}.`}>
      <form onSubmit={envia} className={estilos.formulario}>
        <label>
          Senha nova
          <input
            type="password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            required
            minLength={6}
            autoComplete="new-password"
            autoFocus
          />
        </label>
        <label>
          Confirme a senha nova
          <input
            type="password"
            value={confirmacao}
            onChange={(e) => setConfirmacao(e.target.value)}
            required
            minLength={6}
            autoComplete="new-password"
          />
        </label>

        {erro && (
          <p className={estilos.erro} role="alert">
            {erro}
          </p>
        )}

        <button type="submit" className={estilos.botao} disabled={enviando}>
          {enviando ? 'Aguarde…' : 'Salvar senha nova'}
        </button>
      </form>

      <p className={estilos.links}>
        Desistiu?{' '}
        <button type="button" onClick={() => void cancela()} disabled={enviando}>
          Voltar ao login
        </button>
      </p>
    </MolduraAcesso>
  )
}
