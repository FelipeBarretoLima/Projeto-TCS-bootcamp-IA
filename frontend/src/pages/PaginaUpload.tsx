import { useEffect, useRef, useState } from 'react'
import { ErroApi, enviaExtrato } from '../api/cliente'
import type { ResultadoUpload } from '../api/tipos'
import { ArquivoProcessado } from '../components/ArquivoProcessado'
import { AvisoRejeicao } from '../components/AvisoRejeicao'
import { ResumoExtracao } from '../components/ResumoExtracao'
import { TabelaTransacoes } from '../components/TabelaTransacoes'
import { ZonaUpload } from '../components/ZonaUpload'
import { rotuloMotivo } from '../utils/formatacao'
import estilos from './PaginaUpload.module.css'

type Estado =
  | { fase: 'inicial' }
  | { fase: 'enviando'; nome: string }
  | { fase: 'concluido'; nome: string; resultado: ResultadoUpload }
  | { fase: 'erro'; mensagem: string }

export function PaginaUpload() {
  const [estado, setEstado] = useState<Estado>({ fase: 'inicial' })
  const resultadoRef = useRef<HTMLDivElement>(null)

  // quando o resultado chega, leva o arquivo processado para a vista
  useEffect(() => {
    if (estado.fase !== 'concluido') return
    const reduzido = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    resultadoRef.current?.scrollIntoView({ behavior: reduzido ? 'auto' : 'smooth', block: 'start' })
  }, [estado])

  async function enviar(arquivo: File) {
    setEstado({ fase: 'enviando', nome: arquivo.name })
    try {
      const resultado = await enviaExtrato(arquivo)
      setEstado({ fase: 'concluido', nome: arquivo.name, resultado })
    } catch (erro) {
      const mensagem =
        erro instanceof ErroApi
          ? erro.message
          : 'Não foi possível falar com a API. Confira se ela está rodando e tente de novo.'
      setEstado({ fase: 'erro', mensagem })
    }
  }

  return (
    <div className={estilos.pagina}>
      <header className={estilos.topo}>
        <h1>Importar extrato</h1>
        <p>
          Arraste o PDF ou CSV do seu banco ou clique para selecionar. O arquivo é processado e
          descartado na hora; a tabela mostra as transações já anonimizadas.
        </p>
      </header>

      <ZonaUpload
        enviando={estado.fase === 'enviando'}
        nomeEnviando={estado.fase === 'enviando' ? estado.nome : undefined}
        compacta={estado.fase === 'concluido'}
        onArquivo={enviar}
      />

      {estado.fase === 'erro' && (
        <AvisoRejeicao titulo="Não foi possível enviar" mensagem={estado.mensagem} />
      )}

      {estado.fase === 'concluido' && (
        <div className={estilos.resultado} ref={resultadoRef}>
          <ArquivoProcessado nome={estado.nome} relatorio={estado.resultado.relatorio} />

          {estado.resultado.relatorio.status === 'rejeitado' ? (
            <AvisoRejeicao
              titulo="O extrato não pôde ser processado"
              mensagem={rotuloMotivo(estado.resultado.relatorio.motivo)}
            />
          ) : (
            <section className={estilos.painel} aria-labelledby="titulo-transacoes">
              <div className={estilos.painelTopo}>
                <h2 id="titulo-transacoes">Transações extraídas</h2>
                <ResumoExtracao
                  relatorio={estado.resultado.relatorio}
                  semCategoria={estado.resultado.sem_categoria}
                />
              </div>
              <TabelaTransacoes transacoes={estado.resultado.transacoes} />
            </section>
          )}
        </div>
      )}
    </div>
  )
}
