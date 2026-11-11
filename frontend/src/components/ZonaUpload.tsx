import { LoaderCircle, UploadCloud } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import estilos from './ZonaUpload.module.css'

type Props = {
  enviando: boolean
  nomeEnviando?: string
  /** já existe um resultado na tela: a zona encolhe para a tabela subir */
  compacta?: boolean
  onArquivo: (arquivo: File) => void
  /** Vários arquivos soltos de uma vez: nenhum é enviado. */
  onVarios?: (quantos: number) => void
}

export function ZonaUpload({ enviando, nomeEnviando, compacta = false, onArquivo, onVarios }: Props) {
  const entrada = useRef<HTMLInputElement>(null)
  const [arrastando, setArrastando] = useState(false)

  function abrir() {
    if (!enviando) entrada.current?.click()
  }

  function soltar(evento: DragEvent) {
    evento.preventDefault()
    setArrastando(false)
    if (enviando) return
    const { files } = evento.dataTransfer
    if (files.length > 1) onVarios?.(files.length)
    else if (files[0]) onArquivo(files[0])
  }

  const classes = [
    estilos.zona,
    compacta && estilos.compacta,
    arrastando && estilos.arrastando,
    enviando && estilos.enviando,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      className={classes}
      role="button"
      tabIndex={enviando ? -1 : 0}
      aria-disabled={enviando}
      aria-label="Escolher o arquivo do extrato"
      onClick={abrir}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          abrir()
        }
      }}
      onDragOver={(e) => {
        e.preventDefault()
        if (!enviando) setArrastando(true)
      }}
      onDragLeave={() => setArrastando(false)}
      onDrop={soltar}
    >
      <span className={estilos.icone} aria-hidden="true">
        {enviando ? (
          <LoaderCircle size={compacta ? 22 : 34} className={estilos.girando} />
        ) : (
          <UploadCloud size={compacta ? 22 : 34} />
        )}
      </span>

      {enviando ? (
        <>
          <strong className={estilos.titulo}>Processando o extrato...</strong>
          <span className={estilos.texto}>{nomeEnviando}</span>
        </>
      ) : compacta ? (
        <>
          <strong className={estilos.titulo}>Enviar outro extrato</strong>
          <span className={estilos.texto}>
            solte aqui ou <span className={estilos.link}>clique para abrir</span>
          </span>
        </>
      ) : (
        <>
          <strong className={estilos.titulo}>Solte seu extrato aqui</strong>
          <span className={estilos.texto}>
            ou <span className={estilos.link}>clique para abrir</span> o gerenciador de arquivos
          </span>
          <span className={estilos.dica}>PDF ou CSV, até 10 MB</span>
        </>
      )}

      <input
        ref={entrada}
        type="file"
        accept=".pdf,.csv"
        hidden
        onChange={(e) => {
          const arquivo = e.target.files?.[0]
          if (arquivo) onArquivo(arquivo)
          e.target.value = '' // permite reenviar o mesmo arquivo
        }}
      />
    </div>
  )
}
