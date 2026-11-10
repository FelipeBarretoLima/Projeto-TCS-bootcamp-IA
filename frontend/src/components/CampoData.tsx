import { CalendarDays } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { DayPicker } from 'react-day-picker'
import { ptBR } from 'react-day-picker/locale/pt-BR'
import 'react-day-picker/style.css'
import estilos from './CampoData.module.css'

type Props = {
  rotulo: string
  valor: string // AAAA-MM-DD ou '' (sem data)
  onChange: (iso: string) => void
  min?: string // não deixa escolher antes desta data (AAAA-MM-DD)
  max?: string // nem depois desta
  primeiraDisponivel?: string | null // limites da navegação do calendário (datas das transações)
  ultimaDisponivel?: string | null
}

// sem transações para limitar o calendário, os anos vão até o atual
const ANO_ATUAL = new Date().getFullYear()

// --- conversões (sempre no fuso local, sem passar por UTC) ---

function isoParaData(iso: string): Date | undefined {
  const [a, m, d] = iso.split('-').map(Number)
  return a && m && d ? new Date(a, m - 1, d) : undefined
}

function dataParaIso(data: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${data.getFullYear()}-${p(data.getMonth() + 1)}-${p(data.getDate())}`
}

function isoParaTexto(iso: string): string {
  const [a, m, d] = iso.split('-')
  return a && m && d ? `${d}/${m}/${a}` : ''
}

/** Só dígitos, com as barras entrando sozinhas: "1203" -> "12/03", "12032024" -> "12/03/2024". */
function mascara(texto: string): string {
  const d = texto.replace(/\D/g, '').slice(0, 8)
  return [d.slice(0, 2), d.slice(2, 4), d.slice(4, 8)].filter(Boolean).join('/')
}

/** "12/03/2024" -> "2024-03-12"; null se incompleta ou inexistente (ex.: 31/02). */
function textoParaIso(texto: string): string | null {
  const [d, m, a] = texto.split('/').map(Number)
  if (texto.length !== 10 || !d || !m || !a || a < 1900) return null
  const data = new Date(a, m - 1, d)
  const existe = data.getFullYear() === a && data.getMonth() === m - 1 && data.getDate() === d
  return existe ? dataParaIso(data) : null
}

/** Campo de data: digita dd/mm/aaaa (as barras entram sozinhas) ou escolhe no calendário. */
export function CampoData({ rotulo, valor, onChange, min, max, primeiraDisponivel, ultimaDisponivel }: Props) {
  const id = useId()
  const [texto, setTexto] = useState(isoParaTexto(valor))
  const [invalida, setInvalida] = useState(false)
  const [aberto, setAberto] = useState(false)
  const caixaRef = useRef<HTMLDivElement>(null)
  const botaoRef = useRef<HTMLButtonElement>(null)

  // o valor mudou por fora (atalho de período, calendário, URL): mostra a data nova
  const [valorVisto, setValorVisto] = useState(valor)
  if (valor !== valorVisto) {
    setValorVisto(valor)
    setTexto(isoParaTexto(valor))
    setInvalida(false)
  }

  // calendário aberto: fecha ao clicar fora ou apertar Esc
  useEffect(() => {
    if (!aberto) return
    function cliqueFora(e: MouseEvent) {
      if (!caixaRef.current?.contains(e.target as Node)) setAberto(false)
    }
    function tecla(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      setAberto(false)
      botaoRef.current?.focus()
    }
    document.addEventListener('mousedown', cliqueFora)
    document.addEventListener('keydown', tecla)
    return () => {
      document.removeEventListener('mousedown', cliqueFora)
      document.removeEventListener('keydown', tecla)
    }
  }, [aberto])

  function digita(bruto: string) {
    const novo = mascara(bruto)
    setTexto(novo)
    if (novo.length < 10) {
      setInvalida(false)
      return
    }
    const iso = textoParaIso(novo)
    setInvalida(iso === null)
    if (iso) onChange(iso) // só filtra com a data completa e válida
  }

  function saiDoCampo() {
    if (texto === '') {
      if (valor) onChange('') // apagou tudo: sem limite de data
      return
    }
    if (texto.length < 10) {
      // data pela metade: volta para a última data válida
      setTexto(isoParaTexto(valor))
      setInvalida(false)
    }
  }

  const selecionada = isoParaData(valor)
  const minData = min ? isoParaData(min) : undefined
  const maxData = max ? isoParaData(max) : undefined
  const desabilitadas = [
    ...(minData ? [{ before: minData }] : []),
    ...(maxData ? [{ after: maxData }] : []),
  ]
  const primeira = primeiraDisponivel ? isoParaData(primeiraDisponivel) : undefined
  const ultima = ultimaDisponivel ? isoParaData(ultimaDisponivel) : undefined
  // os anos do menu do calendário cobrem as transações (e a data escolhida, se estiver fora)
  const anoMin = Math.min(primeira?.getFullYear() ?? 2015, selecionada?.getFullYear() ?? 9999)
  const anoMax = Math.max(ultima?.getFullYear() ?? ANO_ATUAL, selecionada?.getFullYear() ?? 0)

  return (
    <div className={estilos.campo} ref={caixaRef}>
      <label htmlFor={id}>{rotulo}</label>
      <div className={`${estilos.caixa} ${invalida ? estilos.invalida : ''}`}>
        <input
          id={id}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          placeholder="dd/mm/aaaa"
          value={texto}
          maxLength={10}
          aria-invalid={invalida}
          aria-describedby={invalida ? `${id}-erro` : undefined}
          onChange={(e) => digita(e.target.value)}
          onBlur={saiDoCampo}
        />
        <button
          ref={botaoRef}
          type="button"
          className={estilos.abrir}
          onClick={() => setAberto((a) => !a)}
          aria-label={`Abrir calendário: ${rotulo}`}
          aria-expanded={aberto}
          title="Escolher no calendário"
        >
          <CalendarDays size={18} />
        </button>
      </div>
      {invalida && (
        <span id={`${id}-erro`} className={estilos.erro}>
          Data inexistente
        </span>
      )}

      {aberto && (
        <div className={estilos.calendario} role="dialog" aria-label={`Calendário: ${rotulo}`}>
          <DayPicker
            mode="single"
            locale={ptBR}
            captionLayout="dropdown"
            startMonth={new Date(anoMin, 0)}
            endMonth={new Date(anoMax, 11)}
            defaultMonth={selecionada ?? ultima}
            selected={selecionada}
            disabled={desabilitadas}
            autoFocus
            onSelect={(data) => {
              if (!data) return
              onChange(dataParaIso(data))
              setAberto(false)
              botaoRef.current?.focus()
            }}
          />
        </div>
      )}
    </div>
  )
}
