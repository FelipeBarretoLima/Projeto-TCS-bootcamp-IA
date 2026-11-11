// Minha conta: nome do perfil e exclusão da conta.

import { useState, type FormEvent } from 'react'
import { useAutenticacao } from '../contexto/contextoAuth'
import estilos from './PaginaConta.module.css'

const PALAVRA_DE_CONFIRMACAO = 'EXCLUIR'

function mensagemDe(e: unknown): string {
  return e instanceof Error ? e.message : 'Não foi possível salvar. Tente de novo.'
}

/** Estado de um formulário: enviando, erro ou aviso de sucesso. */
function useEnvio() {
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  async function executa(acao: () => Promise<string | void>) {
    setEnviando(true)
    setErro(null)
    setAviso(null)
    try {
      const sucesso = await acao()
      if (sucesso) setAviso(sucesso)
    } catch (e) {
      setErro(mensagemDe(e))
    } finally {
      setEnviando(false)
    }
  }

  return { enviando, erro, aviso, executa }
}

function Retorno({ erro, aviso }: { erro: string | null; aviso: string | null }) {
  return (
    <>
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
    </>
  )
}

function Perfil() {
  const { nome: nomeAtual, email, mudaNome } = useAutenticacao()
  const [nome, setNome] = useState(nomeAtual)
  const envio = useEnvio()

  function envia(evento: FormEvent) {
    evento.preventDefault()
    void envio.executa(async () => {
      const limpo = nome.trim()
      if (!limpo) throw new Error('Preencha o seu nome.')
      await mudaNome(limpo)
      setNome(limpo)
      return 'Nome atualizado.'
    })
  }

  return (
    <section className={estilos.cartao} aria-labelledby="titulo-perfil">
      <h2 id="titulo-perfil">Perfil</h2>
      <form onSubmit={envia} className={estilos.formulario}>
        <label className={estilos.campo}>
          <span>Nome</span>
          <input value={nome} onChange={(e) => setNome(e.target.value)} required maxLength={80} autoComplete="name" />
        </label>
        <label className={estilos.campo}>
          <span>E-mail</span>
          <input value={email} readOnly aria-readonly="true" />
        </label>
        <Retorno erro={envio.erro} aviso={envio.aviso} />
        <button type="submit" className={estilos.botao} disabled={envio.enviando || nome.trim() === nomeAtual}>
          {envio.enviando ? 'Salvando…' : 'Salvar nome'}
        </button>
      </form>
    </section>
  )
}

function ExcluirConta() {
  const { apagaConta } = useAutenticacao()
  const [aberto, setAberto] = useState(false)
  const [palavra, setPalavra] = useState('')
  const envio = useEnvio()

  function envia(evento: FormEvent) {
    evento.preventDefault()
    // ao terminar, a sessão some e o app volta sozinho para o login
    void envio.executa(() => apagaConta())
  }

  return (
    <section className={`${estilos.cartao} ${estilos.perigo}`} aria-labelledby="titulo-excluir">
      <h2 id="titulo-excluir">Excluir conta</h2>
      <p className={estilos.explicacao}>
        Apaga o seu login e tudo o que está na conta: extratos importados, transações e conversas com o
        assistente. Não dá para desfazer.
      </p>
      {!aberto ? (
        <button type="button" className={estilos.botaoPerigo} onClick={() => setAberto(true)}>
          Excluir minha conta
        </button>
      ) : (
        <form onSubmit={envia} className={estilos.formulario}>
          <label className={estilos.campo}>
            <span>
              Para confirmar, digite <strong>{PALAVRA_DE_CONFIRMACAO}</strong>
            </span>
            <input value={palavra} onChange={(e) => setPalavra(e.target.value)} autoComplete="off" autoFocus />
          </label>
          <Retorno erro={envio.erro} aviso={null} />
          <div className={estilos.acoes}>
            <button
              type="button"
              className={estilos.botaoSecundario}
              onClick={() => {
                setAberto(false)
                setPalavra('')
              }}
              disabled={envio.enviando}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className={estilos.botaoPerigo}
              disabled={envio.enviando || palavra.trim().toUpperCase() !== PALAVRA_DE_CONFIRMACAO}
            >
              {envio.enviando ? 'Excluindo…' : 'Excluir definitivamente'}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}

export function PaginaConta() {
  return (
    <div className={estilos.pagina}>
      <header className={estilos.topo}>
        <h1>Minha conta</h1>
        <p>Seu nome e a exclusão da conta.</p>
      </header>
      <Perfil />
      <ExcluirConta />
    </div>
  )
}
