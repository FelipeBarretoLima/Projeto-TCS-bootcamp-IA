// Grava uma mensagem de voz com o microfone (MediaRecorder) e entrega o áudio pronto para enviar.
// O navegador só libera o microfone em HTTPS ou em localhost: fora disso, `disponivel` é false.

import { useCallback, useEffect, useRef, useState } from 'react'

export const DURACAO_MAXIMA = 15 // segundos (a API recusa áudios maiores que 1 MB)
const DURACAO_MINIMA_MS = 600 // menos que isso foi toque sem querer

// cada navegador grava num formato: Chrome/Edge/Firefox em webm ou ogg (Opus), Safari em mp4 (AAC)
const FORMATOS = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']

export type FaseGravacao = 'parado' | 'gravando'

function formatoSuportado(): string | undefined {
  return FORMATOS.find((f) => MediaRecorder.isTypeSupported(f))
}

export function microfoneDisponivel(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.isSecureContext &&
    typeof MediaRecorder !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia
  )
}

function mensagemDoErro(erro: unknown): string {
  const nome = erro instanceof DOMException ? erro.name : ''
  if (nome === 'NotAllowedError' || nome === 'SecurityError')
    return 'O acesso ao microfone foi negado. Libere o microfone nas permissões do navegador para este site.'
  if (nome === 'NotFoundError' || nome === 'OverconstrainedError') return 'Nenhum microfone foi encontrado neste aparelho.'
  if (nome === 'NotReadableError') return 'O microfone está sendo usado por outro aplicativo.'
  return 'Não foi possível usar o microfone. Tente de novo.'
}

type Opcoes = {
  /** Gravação concluída (não chamado se foi cancelada ou curta demais). */
  aoConcluir: (audio: Blob) => void
  aoErrar: (mensagem: string) => void
}

export function useGravadorDeVoz({ aoConcluir, aoErrar }: Opcoes) {
  const [fase, setFase] = useState<FaseGravacao>('parado')
  const [segundos, setSegundos] = useState(0)
  const gravador = useRef<MediaRecorder | null>(null)
  const cancelada = useRef(false)
  const inicio = useRef(0)
  const relogio = useRef<number | null>(null)
  // callbacks mais recentes, sem reiniciar a gravação quando o componente renderiza de novo
  const callbacks = useRef({ aoConcluir, aoErrar })
  useEffect(() => {
    callbacks.current = { aoConcluir, aoErrar }
  })

  const paraRelogio = () => {
    if (relogio.current !== null) window.clearInterval(relogio.current)
    relogio.current = null
  }

  const inicia = useCallback(async () => {
    if (gravador.current) return
    let fluxo: MediaStream
    try {
      fluxo = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (erro) {
      callbacks.current.aoErrar(mensagemDoErro(erro))
      return
    }
    const formato = formatoSuportado()
    const rec = new MediaRecorder(fluxo, formato ? { mimeType: formato } : undefined)
    const partes: Blob[] = []
    cancelada.current = false

    rec.ondataavailable = (e) => {
      if (e.data.size > 0) partes.push(e.data)
    }
    rec.onstop = () => {
      fluxo.getTracks().forEach((t) => t.stop()) // apaga o indicador de microfone do navegador
      paraRelogio()
      gravador.current = null
      setFase('parado')
      setSegundos(0)
      if (cancelada.current) return
      if (Date.now() - inicio.current < DURACAO_MINIMA_MS) {
        callbacks.current.aoErrar('Gravação muito curta. Toque no microfone, fale e toque em parar.')
        return
      }
      const audio = new Blob(partes, { type: rec.mimeType || formato || 'audio/webm' })
      if (audio.size === 0) callbacks.current.aoErrar('A gravação veio vazia. Tente de novo.')
      else callbacks.current.aoConcluir(audio)
    }

    gravador.current = rec
    inicio.current = Date.now()
    rec.start()
    setFase('gravando')
    setSegundos(0)
    relogio.current = window.setInterval(() => {
      const passados = Math.floor((Date.now() - inicio.current) / 1000)
      setSegundos(passados)
      if (passados >= DURACAO_MAXIMA) gravador.current?.stop() // limite: envia o que foi gravado
    }, 250)
  }, [])

  const para = useCallback(() => {
    gravador.current?.stop()
  }, [])

  const cancela = useCallback(() => {
    cancelada.current = true
    gravador.current?.stop()
  }, [])

  // saiu da tela no meio da gravação: descarta e solta o microfone
  useEffect(
    () => () => {
      cancelada.current = true
      gravador.current?.stop()
      paraRelogio()
    },
    [],
  )

  return { fase, segundos, inicia, para, cancela }
}
