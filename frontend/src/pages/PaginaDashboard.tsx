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

  useEffect(() => {
    buscaPainel()
      .then(setPainel)
      .catch((e) => setErro(e instanceof ErroApi ? e.message : 'Não foi possível carregar o dashboard.'))
  }, [])

  const mes = painel?.mes ? ` (${painel.mes})` : ''

  return (
    <div className={estilos.pagina}>
      <header className={estilos.topo}>
        <h1>Dashboard</h1>
        {nome && <p>Olá, {nome.split(' ')[0]}!</p>}
      </header>

      {erro && <AvisoRejeicao titulo="Não foi possível carregar o dashboard" mensagem={erro} />}

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
          <div className={estilos.cartoes}>
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
              <h2>Receitas x Despesas (últimos 6 meses)</h2>
              <Grafico dados={painel.grafico} altura={300} mostraTitulo={false} />
            </section>
          )}
        </>
      )}

      <Assistente />
    </div>
  )
}
