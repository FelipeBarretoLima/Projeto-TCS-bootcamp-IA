// Desenha um gráfico a partir dos dados que a API manda (agente/consultas.py). Interativo: valor ao
// passar o mouse e legenda clicável para esconder/mostrar uma série.

import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Grafico as DadosGrafico } from '../api/tipos'
import { useTelaEstreita } from '../hooks/useTelaEstreita'
import { formataMoeda, formataMoedaCurta } from '../utils/formatacao'
import estilos from './Grafico.module.css'

const CORES = Array.from({ length: 8 }, (_, i) => `var(--grafico-${i + 1})`)
const cor = (i: number) => CORES[i % CORES.length]

type Props = {
  dados: DadosGrafico
  altura?: number
  mostraTitulo?: boolean
}

const eixo = { fontSize: 12, fill: 'var(--tinta-suave)' }
const dica = {
  contentStyle: {
    background: 'var(--superficie)',
    border: '1px solid var(--borda)',
    borderRadius: 10,
    color: 'var(--tinta)',
  },
  labelStyle: { color: 'var(--tinta)', fontWeight: 700 },
  cursor: { fill: 'var(--superficie-cabecalho)' },
}

export function Grafico({ dados, altura = 300, mostraTitulo = true }: Props) {
  const [ocultas, setOcultas] = useState<Set<string>>(new Set())
  // celular: rótulos das barras horizontais mais estreitos (no computador ficam 150px, sem cortar)
  const estreita = useTelaEstreita()
  const larguraRotulo = estreita ? 96 : 150
  const encurta = (rotulo: string) => (estreita && rotulo.length > 13 ? `${rotulo.slice(0, 12)}…` : rotulo)
  const formata = (v: unknown) => (dados.formato === 'moeda' ? formataMoeda(Number(v)) : String(v))

  // Recharts quer uma linha por rótulo: {rotulo: 'jan/24', Receitas: 10, Despesas: 5}
  const linhas = dados.rotulos.map((rotulo, i) => ({
    rotulo,
    ...Object.fromEntries(dados.series.map((s) => [s.nome, s.valores[i] ?? 0])),
  }))
  const alterna = (nome: string) =>
    setOcultas((atual) => {
      const nova = new Set(atual)
      if (nova.has(nome)) nova.delete(nome)
      else nova.add(nome)
      return nova
    })
  const legenda = dados.series.length > 1 && (
    <Legend
      onClick={(e) => alterna(String(e.dataKey))}
      wrapperStyle={{ cursor: 'pointer', fontSize: 13 }}
      formatter={(valor: string) => (
        <span style={{ color: ocultas.has(valor) ? 'var(--tinta-suave)' : 'var(--tinta)', opacity: ocultas.has(valor) ? 0.5 : 1 }}>
          {valor}
        </span>
      )}
    />
  )

  let grafico
  if (dados.tipo === 'pizza') {
    const fatias = dados.rotulos.map((rotulo, i) => ({ rotulo, valor: dados.series[0]?.valores[i] ?? 0 }))
    const total = fatias.reduce((s, f) => s + f.valor, 0)
    // fatia: valor e quanto ela representa do total ("R$ 300,00 · 27%")
    const formataFatia = (v: unknown) =>
      total > 0 ? `${formata(v)} · ${Math.round((100 * Number(v)) / total)}%` : formata(v)
    grafico = (
      <PieChart>
        <Pie data={fatias} dataKey="valor" nameKey="rotulo" innerRadius="45%" outerRadius="80%" paddingAngle={1}>
          {fatias.map((f, i) => (
            <Cell key={f.rotulo} fill={cor(i)} stroke="var(--superficie)" />
          ))}
        </Pie>
        <Tooltip {...dica} formatter={formataFatia} />
        <Legend wrapperStyle={{ fontSize: 13 }} />
      </PieChart>
    )
  } else if (dados.tipo === 'linha') {
    grafico = (
      <LineChart data={linhas} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke="var(--grafico-grade)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="rotulo" tick={eixo} tickLine={false} axisLine={{ stroke: 'var(--borda)' }} />
        <YAxis tick={eixo} tickFormatter={formataMoedaCurta} tickLine={false} axisLine={false} width={72} />
        <Tooltip {...dica} cursor={{ stroke: 'var(--borda)' }} formatter={formata} />
        {legenda}
        {dados.series.map((s, i) => (
          <Line
            key={s.nome}
            dataKey={s.nome}
            stroke={cor(i)}
            strokeWidth={2.5}
            dot={{ r: 3 }}
            hide={ocultas.has(s.nome)}
          />
        ))}
      </LineChart>
    )
  } else if (dados.tipo === 'barras_horizontais') {
    grafico = (
      <BarChart data={linhas} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke="var(--grafico-grade)" strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" tick={eixo} tickFormatter={formataMoedaCurta} tickLine={false} axisLine={false} />
        <YAxis
          type="category"
          dataKey="rotulo"
          tick={eixo}
          tickFormatter={encurta}
          tickLine={false}
          axisLine={false}
          width={larguraRotulo}
        />
        <Tooltip {...dica} formatter={formata} />
        {dados.series.map((s, i) => (
          <Bar key={s.nome} dataKey={s.nome} fill={cor(i)} radius={[0, 6, 6, 0]} maxBarSize={28} />
        ))}
      </BarChart>
    )
  } else {
    grafico = (
      <BarChart data={linhas} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke="var(--grafico-grade)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="rotulo" tick={eixo} tickLine={false} axisLine={{ stroke: 'var(--borda)' }} />
        <YAxis tick={eixo} tickFormatter={formataMoedaCurta} tickLine={false} axisLine={false} width={72} />
        <Tooltip {...dica} formatter={formata} />
        {legenda}
        {dados.series.map((s, i) => (
          <Bar
            key={s.nome}
            dataKey={s.nome}
            fill={cor(i)}
            radius={[6, 6, 0, 0]}
            maxBarSize={56}
            hide={ocultas.has(s.nome)}
          />
        ))}
      </BarChart>
    )
  }

  // gráficos horizontais crescem com o número de barras
  const alturaFinal =
    dados.tipo === 'barras_horizontais' ? Math.max(160, 44 * dados.rotulos.length + 40) : altura

  return (
    <figure className={estilos.figura}>
      {mostraTitulo && <figcaption className={estilos.titulo}>{dados.titulo}</figcaption>}
      <div style={{ width: '100%', height: alturaFinal }}>
        <ResponsiveContainer>{grafico}</ResponsiveContainer>
      </div>
    </figure>
  )
}
