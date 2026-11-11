import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router'
import { retornoDoLink } from '../api/supabase'
import { MolduraAcesso } from '../components/MolduraAcesso'
import { useAutenticacao } from '../contexto/contextoAuth'
import estilos from './PaginaLogin.module.css'

type Modo = 'entrar' | 'cadastrar' | 'recuperar'

const TITULOS: Record<Modo, [string, string]> = {
  entrar: ['Bem-vindo de volta', 'Entre com sua conta para continuar.'],
  cadastrar: ['Criar conta', 'Cadastre-se para importar extratos e conversar com o assistente.'],
  recuperar: ['Recuperar senha', 'Enviaremos um link para você criar uma senha nova.'],
}

const TEXTO_BOTAO: Record<Modo, string> = {
  entrar: 'Entrar',
  cadastrar: 'Criar conta',
  recuperar: 'Enviar link',
}

export function PaginaLogin() {
  const { estado, entra, cadastra, recupera } = useAutenticacao()
  const [modo, setModo] = useState<Modo>('entrar')
  const [nome, setNome] = useState('')
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [confirmacao, setConfirmacao] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  if (estado.fase === 'pronto' && estado.sessao) {
    // ao entrar, sempre começa por Importar extrato (ou pela senha nova, se veio do link)
    return <Navigate to={retornoDoLink.tipo === 'recovery' ? '/redefinir-senha' : '/importar'} replace />
  }

  function troca(novo: Modo) {
    setModo(novo)
    setErro(null)
    setAviso(null)
  }

  async function envia(evento: FormEvent) {
    evento.preventDefault()
    setEnviando(true)
    setErro(null)
    setAviso(null)
    try {
      if (modo === 'entrar') await entra(email, senha)
      else if (modo === 'cadastrar') {
        if (!nome.trim()) throw new Error('Preencha o seu nome.')
        if (senha !== confirmacao) throw new Error('As duas senhas não são iguais.')
        if ((await cadastra(nome.trim(), email, senha)) === 'confirmar_email') {
          setConfirmacao('')
          setAviso('Conta criada! Enviamos um e-mail de confirmação: clique no link e depois entre aqui.')
          setModo('entrar')
        }
      } else {
        await recupera(email)
        setAviso(
          `Se existir uma conta com ${email}, o link chega em instantes (confira também o spam). ` +
            'Clique em "Reset password" no e-mail para criar a senha nova.',
        )
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não foi possível continuar. Tente de novo.')
    } finally {
      setEnviando(false)
    }
  }

  const [titulo, subtitulo] = TITULOS[modo]

  return (
    <MolduraAcesso titulo={titulo} subtitulo={subtitulo}>
      {estado.fase === 'indisponivel' && (
        <p className={estilos.erro} role="alert">
          {estado.motivo}
        </p>
      )}

      <form onSubmit={envia} className={estilos.formulario}>
        {modo === 'cadastrar' && (
          <label>
            Nome
            <input value={nome} onChange={(e) => setNome(e.target.value)} required autoComplete="name" />
          </label>
        )}
        <label>
          E-mail
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </label>
        {modo !== 'recuperar' && (
          <label>
            Senha
            <input
              type="password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              required
              minLength={6}
              autoComplete={modo === 'entrar' ? 'current-password' : 'new-password'}
            />
          </label>
        )}
        {modo === 'cadastrar' && (
          <label>
            Confirme a senha
            <input
              type="password"
              value={confirmacao}
              onChange={(e) => setConfirmacao(e.target.value)}
              required
              minLength={6}
              autoComplete="new-password"
            />
          </label>
        )}

        {erro && (
          <p className={estilos.erro} role="alert">
            {erro}
          </p>
        )}
        {aviso && (
          <p className={estilos.aviso} role="status">
            {aviso}
          </p>
        )}

        <button type="submit" className={estilos.botao} disabled={enviando || estado.fase !== 'pronto'}>
          {enviando ? 'Aguarde…' : TEXTO_BOTAO[modo]}
        </button>
      </form>

      <p className={estilos.links}>
        {modo === 'entrar' ? (
          <>
            Esqueceu a senha?{' '}
            <button type="button" onClick={() => troca('recuperar')}>
              Recuperar
            </button>
            <br />
            Ainda não tem conta?{' '}
            <button type="button" onClick={() => troca('cadastrar')}>
              Criar conta
            </button>
          </>
        ) : (
          <>
            Já tem conta?{' '}
            <button type="button" onClick={() => troca('entrar')}>
              Entrar
            </button>
          </>
        )}
      </p>
    </MolduraAcesso>
  )
}
