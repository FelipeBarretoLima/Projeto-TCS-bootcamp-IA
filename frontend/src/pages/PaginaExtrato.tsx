import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { ErroApi, buscaPeriodo, listaTransacoes } from '../api/cliente'
import type { PeriodoTransacoes, TransacaoSalva } from '../api/tipos'
import { AvisoRejeicao } from '../components/AvisoRejeicao'
import { CampoData } from '../components/CampoData'
import { TabelaTransacoes } from '../components/TabelaTransacoes'
import { LISTA_CATEGORIAS, formataMoeda, plural } from '../utils/formatacao'
import estilos from './PaginaExtrato.module.css'

/** Última resposta da API e para quais filtros ela veio (outros filtros = ainda carregando). */
type Resposta =
  | { chave: string; fase: 'pronto'; transacoes: TransacaoSalva[] }
  | { chave: string; fase: 'erro'; mensagem: string }

type Estado = { fase: 'carregando' } | Resposta

const SEM_CATEGORIA = 'sem_categoria'

// os filtros da última visita (a aba do cabeçalho abre /extrato sem eles)
const CHAVE_FILTROS = 'tas:filtros-extrato'

function filtrosSalvos(): string | null {
  try {
    return sessionStorage.getItem(CHAVE_FILTROS)
  } catch {
    return null
  }
}

function salvaFiltros(busca: string) {
  try {
    sessionStorage.setItem(CHAVE_FILTROS, busca)
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
        const salvos = filtrosSalvos()
        if (salvos !== null) setParams(new URLSearchParams(salvos), { replace: true })
        else if (p.padrao_inicio && p.padrao_fim)
          setParams({ inicio: p.padrao_inicio, fim: p.padrao_fim }, { replace: true })
      })
      .catch((e) => setErroPeriodo(mensagemDe(e, 'Não foi possível carregar o extrato.')))
  }, [setParams])

  // lembra os filtros para a próxima vez que a aba abrir
  const busca = params.toString()
  useEffect(() => {
    if (periodo) salvaFiltros(busca)
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

  function muda(novos: { inicio?: string; fim?: string; categoria?: string }) {
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

  const transacoes = estado.fase === 'pronto' ? estado.transacoes : []
  const entradas = transacoes.filter((t) => t.tipo === 'entrada').reduce((s, t) => s + Number(t.valor), 0)
  const saidas = transacoes.filter((t) => t.tipo === 'saida').reduce((s, t) => s + Number(t.valor), 0)

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
              </>
            )}
          </div>
          {transacoes.length === 0 ? (
            <p className={estilos.semResultado}>Nenhuma transação com esses filtros.</p>
          ) : (
            <TabelaTransacoes transacoes={transacoes} />
          )}
        </section>
      )}
    </div>
  )
}

function Topo() {
  return (
    <header className={estilos.topo}>
      <h1>Extrato</h1>
      <p>Todas as transações dos extratos que você importou. Por padrão, os últimos 6 meses.</p>
    </header>
  )
}
