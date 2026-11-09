// Chat do Assistente TAS: conversas anteriores (carregadas ao entrar), mensagens com gráfico e
// sugestões de pergunta.

import { Bot, Plus, SendHorizontal, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ErroApi, apagaConversa, buscaMensagens, listaConversas, pergunta } from '../api/cliente'
import type { Conversa, Mensagem } from '../api/tipos'
import { Grafico } from './Grafico'
import estilos from './Assistente.module.css'

const SUGESTOES = [
  'Onde gastei mais?',
  'Como evoluiu meu saldo?',
  'Receitas x despesas',
  'Quanto gastei de alimentação nos últimos 6 meses?',
]

const mensagemDeErro = (e: unknown) =>
  e instanceof ErroApi ? e.message : 'Não foi possível falar com a API. Tente de novo.'

export function Assistente() {
  const [conversas, setConversas] = useState<Conversa[]>([])
  const [atual, setAtual] = useState<string | null>(null)
  const [mensagens, setMensagens] = useState<Mensagem[]>([])
  const [texto, setTexto] = useState('')
  const [pensando, setPensando] = useState(false)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState<string | null>(null)
  const fimRef = useRef<HTMLDivElement>(null)

  // ao entrar: carrega as conversas e abre a mais recente
  useEffect(() => {
    listaConversas()
      .then(async (lista) => {
        setConversas(lista)
        if (lista[0]) {
          setAtual(lista[0].id)
          setMensagens(await buscaMensagens(lista[0].id))
        }
      })
      .catch((e) => setErro(mensagemDeErro(e)))
      .finally(() => setCarregando(false))
  }, [])

  useEffect(() => {
    fimRef.current?.scrollIntoView({ block: 'end' })
  }, [mensagens, pensando])

  async function abre(id: string) {
    if (id === atual || pensando) return
    setErro(null)
    setAtual(id)
    setMensagens([])
    try {
      setMensagens(await buscaMensagens(id))
    } catch (e) {
      setErro(mensagemDeErro(e))
    }
  }

  function nova() {
    if (pensando) return
    setAtual(null)
    setMensagens([])
    setErro(null)
  }

  async function apaga(id: string) {
    try {
      await apagaConversa(id)
      setConversas((cs) => cs.filter((c) => c.id !== id))
      if (id === atual) nova()
    } catch (e) {
      setErro(mensagemDeErro(e))
    }
  }

  async function envia(conteudo: string) {
    const limpo = conteudo.trim()
    if (!limpo || pensando) return
    setErro(null)
    setTexto('')
    setPensando(true)
    // mostra a pergunta na hora; a resposta da API traz a versão gravada
    const provisoria: Mensagem = { id: -1, papel: 'usuario', texto: limpo, grafico: null, criada_em: '' }
    setMensagens((ms) => [...ms, provisoria])
    try {
      const r = await pergunta(limpo, atual)
      setMensagens((ms) => [...ms.filter((m) => m !== provisoria), r.pergunta, r.resposta])
      if (r.conversa_id !== atual) {
        setAtual(r.conversa_id)
        setConversas(await listaConversas())
      } else {
        setConversas((cs) => [
          ...cs.filter((c) => c.id === r.conversa_id),
          ...cs.filter((c) => c.id !== r.conversa_id),
        ])
      }
    } catch (e) {
      setMensagens((ms) => ms.filter((m) => m !== provisoria))
      setTexto(limpo)
      setErro(mensagemDeErro(e))
    } finally {
      setPensando(false)
    }
  }

  function aoEnviar(evento: FormEvent) {
    evento.preventDefault()
    void envia(texto)
  }

  return (
    <section className={estilos.cartao} aria-labelledby="titulo-assistente">
      <header className={estilos.topo}>
        <span className={estilos.avatar} aria-hidden="true">
          <Bot size={18} />
        </span>
        <h2 id="titulo-assistente">Assistente TAS</h2>
      </header>

      <div className={estilos.corpo}>
        <nav className={estilos.conversas} aria-label="Conversas">
          <button type="button" className={estilos.nova} onClick={nova} disabled={pensando}>
            <Plus size={16} /> Nova conversa
          </button>
          <ul>
            {conversas.map((c) => (
              <li key={c.id} className={c.id === atual ? estilos.ativa : undefined}>
                <button type="button" onClick={() => void abre(c.id)} title={c.titulo}>
                  {c.titulo}
                </button>
                <button
                  type="button"
                  className={estilos.apagar}
                  onClick={() => void apaga(c.id)}
                  aria-label={`Apagar a conversa "${c.titulo}"`}
                  title="Apagar conversa"
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <div className={estilos.chat}>
          <div className={estilos.mensagens} aria-live="polite">
            {carregando ? (
              <p className={estilos.dica}>Carregando conversas…</p>
            ) : mensagens.length === 0 ? (
              <div className={estilos.boasVindas}>
                <p className={`${estilos.balao} ${estilos.agente}`}>
                  Olá! Pergunte algo como “onde gastei mais?” ou “como evoluiu meu saldo?”.
                </p>
                <div className={estilos.sugestoes}>
                  {SUGESTOES.map((s) => (
                    <button key={s} type="button" onClick={() => void envia(s)} disabled={pensando}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              mensagens.map((m) => (
                <div key={`${m.id}-${m.papel}`} className={m.papel === 'usuario' ? estilos.linhaUsuario : estilos.linhaAgente}>
                  <div className={`${estilos.balao} ${m.papel === 'usuario' ? estilos.usuario : estilos.agente}`}>
                    {m.texto && <p>{m.texto}</p>}
                    {m.grafico && (
                      <div className={estilos.grafico}>
                        <Grafico dados={m.grafico} altura={240} />
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
            {pensando && (
              <div className={estilos.linhaAgente}>
                <p className={`${estilos.balao} ${estilos.agente} ${estilos.pensando}`}>Analisando seus extratos…</p>
              </div>
            )}
            <div ref={fimRef} />
          </div>

          {erro && (
            <p className={estilos.erro} role="alert">
              {erro}
            </p>
          )}

          <form className={estilos.entrada} onSubmit={aoEnviar}>
            <input
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder="Pergunte sobre suas finanças…"
              aria-label="Sua pergunta"
              maxLength={1000}
              disabled={pensando}
            />
            <button type="submit" disabled={pensando || !texto.trim()} aria-label="Enviar pergunta">
              <SendHorizontal size={18} />
            </button>
          </form>
        </div>
      </div>
    </section>
  )
}
