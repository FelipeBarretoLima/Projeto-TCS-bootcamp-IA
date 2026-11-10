import { Moon, Sun } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router'
import { Marca } from '../components/Marca'
import { useAutenticacao } from '../contexto/contextoAuth'
import { useTema } from '../hooks/useTema'
import estilos from './PaginaLogin.module.css'

type Modo = 'entrar' | 'cadastrar' | 'recuperar'

const TITULOS: Record<Modo, [string, string]> = {
  entrar: ['Bem-vindo de volta', 'Entre com sua conta para continuar.'],
  cadastrar: ['Criar conta', 'Cadastre-se para importar extratos e conversar com o assistente.'],
  recuperar: ['Recuperar senha', 'Enviaremos um link para você criar uma senha nova.'],
}

export function PaginaLogin() {
  const { estado, entra, cadastra, recupera } = useAutenticacao()
  const { tema, alterna } = useTema()
  const [modo, setModo] = useState<Modo>('entrar')
  const [nome, setNome] = useState('')
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  if (estado.fase === 'pronto' && estado.sessao) {
    // ao entrar, sempre começa por Importar extrato
    return <Navigate to="/importar" replace />
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
        if ((await cadastra(nome.trim(), email, senha)) === 'confirmar_email') {
          setAviso('Conta criada! Enviamos um e-mail de confirmação: clique no link e depois entre aqui.')
          setModo('entrar')
        }
      } else {
        await recupera(email)
        setAviso('Se existir uma conta com este e-mail, você vai receber o link em instantes.')
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não foi possível continuar. Tente de novo.')
    } finally {
      setEnviando(false)
    }
  }

  const [titulo, subtitulo] = TITULOS[modo]
  const textoBotao = { entrar: 'Entrar', cadastrar: 'Criar conta', recuperar: 'Enviar link' }[modo]

  return (
    <div className={estilos.tela}>
      <aside className={estilos.lateral} aria-hidden="true">
        <div className={estilos.frase}>
          <p className={estilos.chamada}>
            Suas finanças,
            <br />
            em conversa.
          </p>
          <p className={estilos.apoio}>
            Importe extratos em PDF e pergunte ao assistente o que quiser sobre seus gastos.
          </p>
        </div>
      </aside>

      <main className={estilos.principal}>
        <button
          type="button"
          className={estilos.tema}
          onClick={alterna}
          aria-label={`Mudar para o tema ${tema === 'claro' ? 'escuro' : 'claro'}`}
        >
          {tema === 'claro' ? <Moon size={20} /> : <Sun size={20} />}
        </button>

        <div className={estilos.caixa}>
          <Marca />
          <h1>{titulo}</h1>
          <p className={estilos.subtitulo}>{subtitulo}</p>

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
              {enviando ? 'Aguarde…' : textoBotao}
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
        </div>
      </main>
    </div>
  )
}
