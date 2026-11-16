// Chat do Assistente TAS: conversas anteriores (carregadas ao entrar), mensagens com gráfico e
// sugestões de pergunta.

import { Bot, MessagesSquare, Mic, Pencil, Plus, SendHorizontal, Square, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ErroApi,
  apagaConversa,
  buscaMensagens,
  listaConversas,
  pergunta,
  renomeiaConversa,
  transcreveAudio,
} from '../api/cliente'
import type { Conversa, Mensagem } from '../api/tipos'
import { DURACAO_MAXIMA, microfoneDisponivel, useGravadorDeVoz } from '../hooks/useGravadorDeVoz'
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

const minutos = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

// o microfone só existe em HTTPS ou localhost (ex.: no celular por http://IP:5173 ele fica bloqueado)
const MICROFONE = microfoneDisponivel()

export function Assistente() {
  const [conversas, setConversas] = useState<Conversa[]>([])
  const [atual, setAtual] = useState<string | null>(null)
  const [mensagens, setMensagens] = useState<Mensagem[]>([])
  const [texto, setTexto] = useState('')
  const [pensando, setPensando] = useState(false)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState<string | null>(null)
  const [confirmando, setConfirmando] = useState<string | null>(null) // conversa à espera do "Apagar"
  const [renomeando, setRenomeando] = useState<{ id: string; titulo: string } | null>(null)
  // lista de conversas aberta no celular (no computador ela aparece sempre; ver Assistente.module.css)
  const [listaAberta, setListaAberta] = useState(false)
  const [transcrevendo, setTranscrevendo] = useState(false)
  const fimRef = useRef<HTMLDivElement>(null)
  const campoRef = useRef<HTMLInputElement>(null)

  // mensagem de voz: grava, a API transcreve e o texto vai para o campo (o usuário confere e envia)
  const gravador = useGravadorDeVoz({
    aoErrar: setErro,
    aoConcluir: async (audio) => {
      setErro(null)
      setTranscrevendo(true)
      try {
        const falado = await transcreveAudio(audio)
        setTexto((atual) => (atual.trim() ? `${atual.trim()} ${falado}` : falado).slice(0, 1000))
        campoRef.current?.focus()
      } catch (e) {
        setErro(mensagemDeErro(e))
      } finally {
        setTranscrevendo(false)
      }
    },
  })
  const gravando = gravador.fase === 'gravando'
  const salvouTitulo = useRef<{ id: string; titulo: string } | null>(null)

  async function salvaTitulo() {
    // Enter e depois o blur do campo que some: só a primeira chamada vale
    if (!renomeando || salvouTitulo.current === renomeando) return
    salvouTitulo.current = renomeando
    const { id, titulo } = renomeando
    const limpo = titulo.trim()
    setRenomeando(null)
    const anterior = conversas.find((c) => c.id === id)?.titulo
    if (!limpo || limpo === anterior) return
    setConversas((cs) => cs.map((c) => (c.id === id ? { ...c, titulo: limpo } : c)))
    try {
      await renomeiaConversa(id, limpo)
    } catch (e) {
      setConversas((cs) => cs.map((c) => (c.id === id && anterior ? { ...c, titulo: anterior } : c)))
      setErro(mensagemDeErro(e))
    }
  }

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
    setListaAberta(false)
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
    setListaAberta(false)
    setAtual(null)
    setMensagens([])
    setErro(null)
  }

  async function apaga(id: string) {
    setConfirmando(null)
    if (pensando) return // a resposta em andamento seria gravada nesta conversa
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
        <button
          type="button"
          className={estilos.alternaLista}
          onClick={() => setListaAberta((aberta) => !aberta)}
          aria-expanded={listaAberta}
          aria-controls="lista-conversas"
        >
          <MessagesSquare size={16} /> Conversas{conversas.length > 0 && ` (${conversas.length})`}
        </button>
      </header>

      <div className={estilos.corpo}>
        <nav
          id="lista-conversas"
          className={`${estilos.conversas} ${listaAberta ? estilos.listaAberta : ''}`}
          aria-label="Conversas"
        >
          <button type="button" className={estilos.nova} onClick={nova} disabled={pensando}>
            <Plus size={16} /> Nova conversa
          </button>
          <ul>
            {conversas.map((c) =>
              confirmando === c.id ? (
                <li key={c.id} className={estilos.confirmacao} role="group" aria-label="Confirmar exclusão">
                  <span>Apagar esta conversa?</span>
                  <button type="button" className={estilos.cancelar} onClick={() => setConfirmando(null)}>
                    Não
                  </button>
                  <button
                    type="button"
                    className={estilos.confirmar}
                    onClick={() => void apaga(c.id)}
                    disabled={pensando}
                    autoFocus
                  >
                    Apagar
                  </button>
                </li>
              ) : renomeando?.id === c.id ? (
                <li key={c.id} className={estilos.ativa}>
                  <input
                    className={estilos.renomear}
                    value={renomeando.titulo}
                    onChange={(e) => setRenomeando({ id: c.id, titulo: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void salvaTitulo()
                      if (e.key === 'Escape') setRenomeando(null)
                    }}
                    onBlur={() => void salvaTitulo()}
                    maxLength={60}
                    aria-label="Novo nome da conversa (Enter salva, Esc cancela)"
                    autoFocus
                  />
                </li>
              ) : (
                <li key={c.id} className={c.id === atual ? estilos.ativa : undefined}>
                  <button type="button" onClick={() => void abre(c.id)} title={c.titulo}>
                    {c.titulo}
                  </button>
                  <button
                    type="button"
                    className={estilos.apagar}
                    onClick={() => setRenomeando({ id: c.id, titulo: c.titulo })}
                    aria-label={`Renomear a conversa "${c.titulo}"`}
                    title="Renomear conversa"
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    type="button"
                    className={estilos.apagar}
                    onClick={() => setConfirmando(c.id)}
                    disabled={pensando}
                    aria-label={`Apagar a conversa "${c.titulo}"`}
                    title={pensando ? 'Aguarde a resposta do assistente' : 'Apagar conversa'}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ),
            )}
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
            {gravando ? (
              <>
                <button
                  type="button"
                  className={estilos.cancelarVoz}
                  onClick={gravador.cancela}
                  aria-label="Descartar a gravação"
                  title="Descartar"
                >
                  <X size={18} />
                </button>
                <p className={estilos.gravando} role="status">
                  <span className={estilos.pontoGravando} aria-hidden="true" />
                  Gravando… {minutos(gravador.segundos)}
                  <span className={estilos.limiteVoz}> / {minutos(DURACAO_MAXIMA)}</span>
                </p>
                <button
                  type="button"
                  className={estilos.pararVoz}
                  onClick={gravador.para}
                  aria-label="Parar e transcrever a gravação"
                  title="Parar e transcrever"
                >
                  <Square size={16} fill="currentColor" />
                </button>
              </>
            ) : (
              <>
                <input
                  ref={campoRef}
                  value={texto}
                  onChange={(e) => setTexto(e.target.value)}
                  placeholder={transcrevendo ? 'Transcrevendo o áudio…' : 'Pergunte sobre suas finanças…'}
                  aria-label="Sua pergunta"
                  maxLength={1000}
                  disabled={pensando || transcrevendo}
                />
                <button
                  type="button"
                  className={estilos.microfone}
                  onClick={() => void gravador.inicia()}
                  disabled={!MICROFONE || pensando || transcrevendo}
                  aria-label="Gravar mensagem de voz"
                  title={
                    MICROFONE
                      ? 'Gravar mensagem de voz'
                      : 'Microfone indisponível: o navegador só libera o microfone em sites HTTPS'
                  }
                >
                  <Mic size={18} />
                </button>
                <button
                  type="submit"
                  disabled={pensando || transcrevendo || !texto.trim()}
                  aria-label="Enviar pergunta"
                >
                  <SendHorizontal size={18} />
                </button>
              </>
            )}
          </form>
        </div>
      </div>
    </section>
  )
}
