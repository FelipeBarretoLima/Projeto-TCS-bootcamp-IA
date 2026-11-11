import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { ErroApi, buscaPainel } from '../api/cliente'
import type { Painel } from '../api/tipos'
import { Assistente } from '../components/Assistente'
import { AvisoRejeicao } from '../components/AvisoRejeicao'
import { Grafico } from '../components/Grafico'
import { useAutenticacao } from '../contexto/contextoAuth'
import { formataMoeda } from '../utils/formatacao'
import estilos from './PaginaDashboard.module.css'

export function PaginaDashboard() {
  const { nome } = useAutenticacao()
  const [painel, setPainel] = useState<Painel | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [mesEscolhido, setMesEscolhido] = useState<string | undefined>(undefined) // undefined = o mais recente
  const [trocandoMes, setTrocandoMes] = useState(false)

  useEffect(() => {
    let ativo = true
    buscaPainel(mesEscolhido)
      .then((p) => {
        if (!ativo) return
        setPainel(p)
        setErro(null)
      })
      .catch((e) => ativo && setErro(e instanceof ErroApi ? e.message : 'Não foi possível carregar o dashboard.'))
      .finally(() => ativo && setTrocandoMes(false))
    return () => {
      ativo = false
    }
  }, [mesEscolhido])

  const mes = painel?.mes ? ` (${painel.mes})` : ''

  return (
    <div className={estilos.pagina}>
      <header className={estilos.topo}>
        <h1>Dashboard</h1>
        {nome && <p>Olá, {nome.split(' ')[0]}!</p>}
      </header>

      {erro && <AvisoRejeicao titulo="Não foi possível carregar o dashboard" mensagem={erro} />}

      {!painel && !erro && (
        <p className={estilos.carregando} role="status">
          Carregando seus números…
        </p>
      )}

      {painel && !painel.tem_dados && (
        <div className={estilos.vazio}>
          <p>Você ainda não importou nenhum extrato. Importe o primeiro para ver seus números aqui.</p>
          <Link to="/importar" className={estilos.botao}>
            Importar extrato
          </Link>
        </div>
      )}

      {painel?.tem_dados && (
        <>
          {painel.meses.length > 1 && (
            <label className={estilos.escolheMes}>
              <span>Mês</span>
              <select
                value={painel.mes_valor ?? ''}
                onChange={(e) => {
                  setTrocandoMes(true)
                  setMesEscolhido(e.target.value)
                }}
                disabled={trocandoMes}
              >
                {painel.meses.map((m, i) => (
                  <option key={m.valor} value={m.valor}>
                    {m.rotulo}
                    {i === 0 ? ' (mais recente)' : ''}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className={trocandoMes ? `${estilos.cartoes} ${estilos.atualizando}` : estilos.cartoes}>
            <div className={estilos.cartao}>
              <span>Receitas{mes}</span>
              <strong className={estilos.positivo}>{formataMoeda(painel.receitas)}</strong>
            </div>
            <div className={estilos.cartao}>
              <span>Despesas{mes}</span>
              <strong className={estilos.negativo}>{formataMoeda(-painel.despesas)}</strong>
            </div>
            <div className={estilos.cartao}>
              <span>Saldo{mes}</span>
              <strong className={painel.saldo >= 0 ? estilos.saldo : estilos.negativo}>
                {formataMoeda(painel.saldo)}
              </strong>
            </div>
          </div>

          {painel.grafico && (
            <section className={estilos.cartaoGrafico}>
              <h2>Receitas x Despesas (6 meses até {painel.mes})</h2>
              <Grafico dados={painel.grafico} altura={300} mostraTitulo={false} />
            </section>
          )}
        </>
      )}

      <Assistente />
    </div>
  )
}
