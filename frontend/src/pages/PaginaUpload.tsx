import { ArrowRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { ErroApi, enviaExtrato } from '../api/cliente'
import type { Gravacao, ResultadoImportacao } from '../api/tipos'
import { ArquivoProcessado } from '../components/ArquivoProcessado'
import { AvisoRejeicao } from '../components/AvisoRejeicao'
import { ListaExtratos } from '../components/ListaExtratos'
import { ResumoExtracao } from '../components/ResumoExtracao'
import { TabelaTransacoes } from '../components/TabelaTransacoes'
import { ZonaUpload } from '../components/ZonaUpload'
import { plural, rotuloMotivo } from '../utils/formatacao'
import estilos from './PaginaUpload.module.css'

type Estado =
  | { fase: 'inicial' }
  | { fase: 'enviando'; nome: string }
  | { fase: 'concluido'; nome: string; resultado: ResultadoImportacao }
  | { fase: 'erro'; mensagem: string; repetido: boolean }

/** "12 transações novas salvas na sua conta. 3 já existiam de um extrato anterior e não foram contadas de novo." */
function textoGravacao({ gravadas, repetidas }: Gravacao): string {
  const novas =
    gravadas > 0
      ? `${plural(gravadas, 'transação nova salva', 'transações novas salvas')} na sua conta.`
      : 'Nenhuma transação nova: todas já estavam na sua conta.'
  if (repetidas === 0) return novas
  const verbo = repetidas === 1 ? 'já existia' : 'já existiam'
  const contada = repetidas === 1 ? 'foi contada' : 'foram contadas'
  return `${novas} ${repetidas} ${verbo} de um extrato anterior e não ${contada} de novo.`
}

export function PaginaUpload() {
  const [estado, setEstado] = useState<Estado>({ fase: 'inicial' })
  const resultadoRef = useRef<HTMLDivElement>(null)
  // muda a cada importação gravada: a lista de extratos importados recarrega
  const [versaoExtratos, setVersaoExtratos] = useState(0)

  function verExtratos() {
    const reduzido = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    document
      .getElementById('extratos-importados')
      ?.scrollIntoView({ behavior: reduzido ? 'auto' : 'smooth', block: 'start' })
  }

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
      if (resultado.gravacao) setVersaoExtratos((v) => v + 1)
    } catch (erro) {
      const mensagem =
        erro instanceof ErroApi
          ? erro.message
          : 'Não foi possível falar com a API. Confira se ela está rodando e tente de novo.'
      // 409 = o mesmo arquivo já foi importado (POST /extratos)
      setEstado({ fase: 'erro', mensagem, repetido: erro instanceof ErroApi && erro.status === 409 })
    }
  }

  return (
    <div className={estilos.pagina}>
      <header className={estilos.topo}>
        <h1>Importar extrato</h1>
        <p>
          Arraste o PDF ou CSV do seu banco ou clique para selecionar. O arquivo é processado e
          descartado na hora: só as transações ficam salvas na sua conta. Você vê os nomes como
          vieram do banco, guardados de forma criptografada; o classificador e o assistente só
          usam a versão anonimizada.
        </p>
      </header>

      <ZonaUpload
        enviando={estado.fase === 'enviando'}
        nomeEnviando={estado.fase === 'enviando' ? estado.nome : undefined}
        compacta={estado.fase === 'concluido'}
        onArquivo={enviar}
      />

      {estado.fase === 'erro' && (
        <AvisoRejeicao
          titulo="Não foi possível enviar"
          mensagem={
            estado.repetido
              ? `${estado.mensagem}. Para importar de novo, exclua o extrato anterior na lista abaixo.`
              : estado.mensagem
          }
        >
          {estado.repetido && (
            <button type="button" className={estilos.verExtratos} onClick={verExtratos}>
              Ver extratos importados
            </button>
          )}
        </AvisoRejeicao>
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
              {estado.resultado.gravacao && (
                <p className={estilos.gravacao} role="status">
                  {textoGravacao(estado.resultado.gravacao)}
                </p>
              )}
              <div className={estilos.painelTopo}>
                <div className={estilos.tituloComAcao}>
                  <h2 id="titulo-transacoes">Transações extraídas</h2>
                  <Link to="/dashboard" className={estilos.verDashboard}>
                    Ver dashboard <ArrowRight size={18} />
                  </Link>
                </div>
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

      <ListaExtratos
        versao={versaoExtratos}
        onExcluido={() => {
          // o extrato que travava a importação saiu: o aviso de "já importado" não vale mais
          if (estado.fase === 'erro' && estado.repetido) setEstado({ fase: 'inicial' })
        }}
      />
    </div>
  )
}
