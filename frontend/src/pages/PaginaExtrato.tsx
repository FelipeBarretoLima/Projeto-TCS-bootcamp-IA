import { Download } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { ErroApi, buscaPeriodo, listaTransacoes, mudaCategoria } from '../api/cliente'
import type { PeriodoTransacoes, TransacaoSalva } from '../api/tipos'
import { AvisoRejeicao } from '../components/AvisoRejeicao'
import { CampoData } from '../components/CampoData'
import { TabelaTransacoes } from '../components/TabelaTransacoes'
import { baixaCsv } from '../utils/exportacao'
import { LISTA_CATEGORIAS, formataMoeda, plural, rotuloContraparte } from '../utils/formatacao'
import estilos from './PaginaExtrato.module.css'

/** Linhas mostradas por vez (o resto entra com "Mostrar mais"). */
const POR_PAGINA = 100

/** Sem acentos e em minúsculas: "Padaria São João" acha "sao joao". */
function normaliza(texto: string): string {
  return texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
}

function casaBusca(t: TransacaoSalva, termo: string): boolean {
  // o texto que a tabela mostra (original, quando houver) e também o anonimizado
  const textos = [t.contraparte_original, t.historico_original, rotuloContraparte(t.contraparte), t.historico]
  return normaliza(textos.filter(Boolean).join(' ')).includes(termo)
}

/** Última resposta da API e para quais filtros ela veio (outros filtros = ainda carregando). */
type Resposta =
  | { chave: string; fase: 'pronto'; transacoes: TransacaoSalva[] }
  | { chave: string; fase: 'erro'; mensagem: string }

type Estado = { fase: 'carregando' } | Resposta

const SEM_CATEGORIA = 'sem_categoria'

// os filtros da última visita (a aba do cabeçalho abre /extrato sem eles)
const CHAVE_FILTROS = 'tas:filtros-extrato'

/** Filtros guardados junto com a última transação que existia quando foram usados. */
type FiltrosGuardados = { busca: string; ultima: string | null }

/** Os filtros da última visita, se ainda valem: com transações novas (outro extrato importado,
 *  outra conta na mesma aba), volta ao padrão para as novas não ficarem escondidas. */
function filtrosSalvos(ultima: string | null): string | null {
  try {
    const guardados = JSON.parse(sessionStorage.getItem(CHAVE_FILTROS) ?? 'null') as FiltrosGuardados | null
    return guardados && guardados.ultima === ultima ? guardados.busca : null
  } catch {
    return null
  }
}

function salvaFiltros(busca: string, ultima: string | null) {
  try {
    sessionStorage.setItem(CHAVE_FILTROS, JSON.stringify({ busca, ultima } satisfies FiltrosGuardados))
  } catch {
    // sem sessionStorage (aba privada etc.): só não lembra os filtros
  }
}

function mensagemDe(e: unknown, padrao: string): string {
  return e instanceof ErroApi ? e.message : padrao
}

/** Aba Extrato: as transações salvas na conta, com filtro de período e categoria.
 *  Padrão: os últimos 6 meses (até o mês da transação mais recente, como no dashboard).
 *  Os filtros ficam na URL (?inicio=&fim=&categoria=) e são lembrados ao trocar de aba. */
export function PaginaExtrato() {
  const [params, setParams] = useSearchParams()
  const inicio = params.get('inicio') ?? ''
  const fim = params.get('fim') ?? ''
  const categoria = params.get('categoria') ?? ''
  const textoBusca = params.get('busca') ?? ''
  const periodoInvertido = Boolean(inicio && fim && inicio > fim)

  const [periodo, setPeriodo] = useState<PeriodoTransacoes | null>(null)
  const [erroPeriodo, setErroPeriodo] = useState<string | null>(null)
  const abriuSemFiltros = useRef(params.toString() === '')

  // 1º passo: descobre o período das transações e, se a URL veio sem filtros, aplica o padrão
  useEffect(() => {
    buscaPeriodo()
      .then((p) => {
        setPeriodo(p)
        if (!abriuSemFiltros.current) return
        const salvos = filtrosSalvos(p.ultima)
        if (salvos !== null) setParams(new URLSearchParams(salvos), { replace: true })
        else if (p.padrao_inicio && p.padrao_fim)
          setParams({ inicio: p.padrao_inicio, fim: p.padrao_fim }, { replace: true })
      })
      .catch((e) => setErroPeriodo(mensagemDe(e, 'Não foi possível carregar o extrato.')))
  }, [setParams])

  // lembra os filtros para a próxima vez que a aba abrir
  const busca = params.toString()
  useEffect(() => {
    if (periodo) salvaFiltros(busca, periodo.ultima)
  }, [busca, periodo])

  // 2º passo: busca as transações (só depois do padrão aplicado, para não buscar tudo à toa)
  const chave = `${inicio}|${fim}|${categoria}`
  const [resposta, setResposta] = useState<Resposta | null>(null)
  const estado: Estado = resposta && resposta.chave === chave ? resposta : { fase: 'carregando' }

  useEffect(() => {
    if (!periodo || periodoInvertido) return
    // trocou o filtro antes de a resposta chegar: cancela a busca antiga
    const controle = new AbortController()
    listaTransacoes({ inicio, fim, categoria }, controle.signal)
      .then((transacoes) => setResposta({ chave, fase: 'pronto', transacoes }))
      .catch((e) => {
        if (controle.signal.aborted) return
        setResposta({ chave, fase: 'erro', mensagem: mensagemDe(e, 'Não foi possível carregar o extrato.') })
      })
    return () => controle.abort()
  }, [periodo, chave, inicio, fim, categoria, periodoInvertido])

  // paginação: volta para as primeiras linhas quando o filtro muda
  const [limite, setLimite] = useState({ chave: '', linhas: POR_PAGINA })
  const chaveLista = `${chave}|${textoBusca}`
  const linhasVisiveis = limite.chave === chaveLista ? limite.linhas : POR_PAGINA

  // correção de categoria: muda na tela na hora e volta atrás se a API recusar
  const [salvando, setSalvando] = useState<ReadonlySet<number>>(new Set())
  const [erroCategoria, setErroCategoria] = useState<string | null>(null)

  function trocaNaResposta(id: number, categoria: string | null) {
    setResposta((r) =>
      r?.fase === 'pronto'
        ? { ...r, transacoes: r.transacoes.map((t) => (t.id === id ? { ...t, categoria } : t)) }
        : r,
    )
  }

  async function corrigeCategoria(t: TransacaoSalva, nova: string | null) {
    setErroCategoria(null)
    setSalvando((s) => new Set(s).add(t.id))
    trocaNaResposta(t.id, nova)
    try {
      await mudaCategoria(t.id, nova)
    } catch (e) {
      trocaNaResposta(t.id, t.categoria)
      setErroCategoria(mensagemDe(e, 'Não foi possível salvar a categoria. Tente de novo.'))
    } finally {
      setSalvando((s) => {
        const resto = new Set(s)
        resto.delete(t.id)
        return resto
      })
    }
  }

  function muda(novos: { inicio?: string; fim?: string; categoria?: string; busca?: string }) {
    setParams(
      (anteriores) => {
        const p = new URLSearchParams(anteriores)
        for (const [k, v] of Object.entries(novos)) {
          if (v) p.set(k, v)
          else p.delete(k)
        }
        return p
      },
      { replace: true },
    )
  }

  const temDados = Boolean(periodo?.ultima)
  const eSeisMeses = temDados && inicio === periodo?.padrao_inicio && fim === periodo?.padrao_fim
  const eTudo = temDados && ((inicio === periodo?.primeira && fim === periodo?.ultima) || (!inicio && !fim))

  const termo = normaliza(textoBusca.trim())
  const doPeriodo = estado.fase === 'pronto' ? estado.transacoes : []
  const transacoes = termo ? doPeriodo.filter((t) => casaBusca(t, termo)) : doPeriodo
  const visiveis = transacoes.slice(0, linhasVisiveis)
  // como no dashboard: pagar a fatura, investir ou mover dinheiro entre contas (categoria Financeiro)
  // não entra nos totais, senão a compra no cartão e o pagamento da fatura contam duas vezes.
  // Filtrando só Financeiro, os totais mostram essas próprias transações.
  const somaFinanceiro = categoria === 'financeiro'
  const nosTotais = transacoes.filter((t) => somaFinanceiro || t.categoria !== 'financeiro')
  const foraDosTotais = transacoes.length - nosTotais.length
  const entradas = nosTotais.filter((t) => t.tipo === 'entrada').reduce((s, t) => s + Number(t.valor), 0)
  const saidas = nosTotais.filter((t) => t.tipo === 'saida').reduce((s, t) => s + Number(t.valor), 0)

  if (erroPeriodo) {
    return (
      <div className={estilos.pagina}>
        <Topo />
        <AvisoRejeicao titulo="Não foi possível carregar o extrato" mensagem={erroPeriodo} />
      </div>
    )
  }

  if (periodo && !temDados) {
    return (
      <div className={estilos.pagina}>
        <Topo />
        <div className={estilos.vazio}>
          <p>Você ainda não importou nenhum extrato. Importe o primeiro para ver suas transações aqui.</p>
          <Link to="/importar" className={estilos.botao}>
            Importar extrato
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className={estilos.pagina}>
      <Topo />

      <form className={estilos.filtros} onSubmit={(e) => e.preventDefault()} aria-label="Filtros do extrato">
        <div className={estilos.atalhos} role="group" aria-label="Período">
          <button
            type="button"
            className={estilos.atalho}
            aria-pressed={eSeisMeses}
            disabled={!periodo}
            onClick={() => periodo && muda({ inicio: periodo.padrao_inicio ?? '', fim: periodo.padrao_fim ?? '' })}
          >
            Últimos 6 meses
          </button>
          <button
            type="button"
            className={estilos.atalho}
            aria-pressed={eTudo}
            disabled={!periodo}
            onClick={() => periodo && muda({ inicio: periodo.primeira ?? '', fim: periodo.ultima ?? '' })}
          >
            Todo o período
          </button>
        </div>

        <div className={estilos.campos}>
          <CampoData
            rotulo="De"
            valor={inicio}
            max={fim || undefined}
            onChange={(v) => muda({ inicio: v })}
            primeiraDisponivel={periodo?.primeira}
            ultimaDisponivel={periodo?.ultima}
          />
          <CampoData
            rotulo="Até"
            valor={fim}
            min={inicio || undefined}
            onChange={(v) => muda({ fim: v })}
            primeiraDisponivel={periodo?.primeira}
            ultimaDisponivel={periodo?.ultima}
          />
          <label className={estilos.campo}>
            <span>Categoria</span>
            <select value={categoria} onChange={(e) => muda({ categoria: e.target.value })}>
              <option value="">Todas</option>
              {LISTA_CATEGORIAS.map(([codigo, rotulo]) => (
                <option key={codigo} value={codigo}>
                  {rotulo}
                </option>
              ))}
              <option value={SEM_CATEGORIA}>Sem categoria</option>
            </select>
          </label>
          <label className={`${estilos.campo} ${estilos.campoBusca}`}>
            <span>Buscar</span>
            <input
              type="search"
              value={textoBusca}
              onChange={(e) => muda({ busca: e.target.value })}
              placeholder="Estabelecimento ou descrição"
              maxLength={80}
            />
          </label>
        </div>
      </form>

      {periodoInvertido && (
        <AvisoRejeicao titulo="Período inválido" mensagem="A data inicial deve ser anterior ou igual à data final." />
      )}

      {!periodoInvertido && estado.fase === 'erro' && (
        <AvisoRejeicao titulo="Não foi possível carregar o extrato" mensagem={estado.mensagem} />
      )}

      {!periodoInvertido && estado.fase === 'carregando' && (
        <p className={estilos.carregando} role="status">
          Carregando transações…
        </p>
      )}

      {!periodoInvertido && estado.fase === 'pronto' && (
        <section className={estilos.painel} aria-label="Transações">
          <div className={estilos.resumo} role="status">
            <strong>{plural(transacoes.length, 'transação', 'transações')}</strong>
            {transacoes.length > 0 && (
              <>
                <span>
                  Entradas <b className={estilos.entrada}>{formataMoeda(entradas)}</b>
                </span>
                <span>
                  Saídas <b className={estilos.saida}>{formataMoeda(saidas)}</b>
                </span>
                <button
                  type="button"
                  className={estilos.exportar}
                  onClick={() => baixaCsv(transacoes, nomeDoArquivo(inicio, fim))}
                  title="Baixar estas transações numa planilha (CSV)"
                >
                  <Download size={16} aria-hidden="true" /> Exportar CSV
                </button>
                {foraDosTotais > 0 && (
                  <small className={estilos.notaTotais}>
                    Sem {plural(foraDosTotais, 'transação', 'transações')} da categoria Financeiro (fatura,
                    investimentos), como no dashboard.
                  </small>
                )}
              </>
            )}
          </div>
          {erroCategoria && (
            <p className={estilos.erroCategoria} role="alert">
              {erroCategoria}
            </p>
          )}
          {transacoes.length === 0 ? (
            <p className={estilos.semResultado}>
              {termo ? `Nenhuma transação com “${textoBusca.trim()}” nesses filtros.` : 'Nenhuma transação com esses filtros.'}
            </p>
          ) : (
            <>
              <TabelaTransacoes
                transacoes={visiveis}
                onMudaCategoria={(t, c) => void corrigeCategoria(t, c)}
                salvando={salvando}
              />
              {transacoes.length > visiveis.length && (
                <div className={estilos.mais}>
                  <span>
                    Mostrando {visiveis.length} de {transacoes.length}
                  </span>
                  <button
                    type="button"
                    className={estilos.atalho}
                    onClick={() => setLimite({ chave: chaveLista, linhas: linhasVisiveis + POR_PAGINA })}
                  >
                    Mostrar mais {Math.min(POR_PAGINA, transacoes.length - visiveis.length)}
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      )}
    </div>
  )
}

/** "transacoes_2024-01-01_a_2024-06-30.csv" */
function nomeDoArquivo(inicio: string, fim: string): string {
  const periodo = inicio && fim ? `_${inicio}_a_${fim}` : inicio ? `_desde_${inicio}` : fim ? `_ate_${fim}` : ''
  return `transacoes${periodo}.csv`
}

function Topo() {
  return (
    <header className={estilos.topo}>
      <h1>Extrato</h1>
      <p>Todas as transações dos extratos que você importou. Por padrão, os últimos 6 meses.</p>
    </header>
  )
}
