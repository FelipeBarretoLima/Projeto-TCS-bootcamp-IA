# Código-base do frontend

Do projeto de referência (`frontend/`). Os tipos (`api/tipos.ts`) são a tradução direta dos
schemas da API (skill `app-extratos-api`, `references/rotas-e-esquemas.md`): `date`/`datetime` →
`string`, `Decimal` → `string`, `float`/`int` → `number`, `None` → `null`.

## Sumário

1. `vite.config.ts` e `index.html`
2. `api/cliente.ts`
3. `api/supabase.ts`
4. Sessão: `contexto/contextoAuth.ts` e `contexto/Autenticacao.tsx`
5. `App.tsx`
6. `hooks/useTema.ts`
7. `components/Grafico.tsx`
8. `utils/formatacao.ts` (trechos)
9. `utils/exportacao.ts`

## 1. `vite.config.ts` e `index.html`

```ts
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
```

```html
<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Nome do produto</title>
    <script>
      // aplica o tema antes da primeira pintura (mesma chave de src/hooks/useTema.ts)
      document.documentElement.dataset.tema = 'claro'
      try {
        if (localStorage.getItem('tas-tema-escolhido') === 'escuro') document.documentElement.dataset.tema = 'escuro'
      } catch {}
    </script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

## 2. `api/cliente.ts`

```ts
import { tokenAtual } from './supabase'
import type {
  ExtratoEnviado, FiltrosTransacoes, Painel, RespostaChat, ResultadoImportacao, TransacaoSalva,
} from './tipos'

export class ErroApi extends Error {
  status: number
  constructor(mensagem: string, status = 0) {
    super(mensagem)
    this.status = status
  }
}

/** Avisado quando a API responde 401 (sessão expirada): o app volta para o login. */
let aoExpirar: (() => void) | null = null
export function quandoSessaoExpirar(acao: () => void) {
  aoExpirar = acao
}

async function trataResposta<T>(resposta: Response): Promise<T> {
  if (resposta.ok) return (resposta.status === 204 ? undefined : await resposta.json()) as T
  if (resposta.status === 502 || resposta.status === 504) {
    // 502 com corpo JSON é erro da própria API (ex.: o assistente falhou); sem corpo, a API está fora
    const corpo = await resposta.json().catch(() => null)
    if (typeof corpo?.detail === 'string') throw new ErroApi(corpo.detail, resposta.status)
    throw new ErroApi('A API não está respondendo. Inicie a API e tente de novo.', resposta.status)
  }
  if (resposta.status === 401) aoExpirar?.()
  const corpo = await resposta.json().catch(() => null)  // erros vêm como {"detail": "mensagem"}
  const detalhe = typeof corpo?.detail === 'string' ? corpo.detail : null
  throw new ErroApi(detalhe ?? `Erro inesperado da API (HTTP ${resposta.status})`, resposta.status)
}

async function chama<T>(caminho: string, opcoes: RequestInit = {}): Promise<T> {
  const token = await tokenAtual()
  const cabecalhos = new Headers(opcoes.headers)
  if (token) cabecalhos.set('Authorization', `Bearer ${token}`)
  return trataResposta<T>(await fetch(caminho, { ...opcoes, headers: cabecalhos }))
}

/** Logout: a API esquece o token na hora. Falhar aqui não impede sair. */
export async function encerraSessaoNaApi(): Promise<void> {
  try {
    const token = await tokenAtual()
    if (token) await fetch('/api/sessao', { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
  } catch {
    // API fora do ar: segue com o logout
  }
}

export async function enviaExtrato(arquivo: File): Promise<ResultadoImportacao> {
  const formulario = new FormData()
  formulario.append('arquivo', arquivo)
  return chama<ResultadoImportacao>('/api/extratos', { method: 'POST', body: formulario })
}

export const listaExtratos = () => chama<ExtratoEnviado[]>('/api/extratos')
export const apagaExtrato = (id: string) => chama<void>(`/api/extratos/${id}`, { method: 'DELETE' })

/** Transações salvas; filtros vazios são ignorados. */
export function listaTransacoes(filtros: FiltrosTransacoes, signal?: AbortSignal): Promise<TransacaoSalva[]> {
  const params = new URLSearchParams()
  for (const [chave, valor] of Object.entries(filtros)) if (valor) params.set(chave, valor)
  const consulta = params.toString()
  return chama<TransacaoSalva[]>(`/api/transacoes${consulta ? `?${consulta}` : ''}`, { signal })
}

export const buscaPainel = (mes?: string) => chama<Painel>(`/api/painel${mes ? `?mes=${encodeURIComponent(mes)}` : ''}`)

const json = (corpo: unknown): RequestInit => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(corpo),
})

export const mudaCategoria = (id: number, categoria: string | null) =>
  chama<void>(`/api/transacoes/${id}`, { method: 'PATCH', ...json({ categoria }) })

export const pergunta = (mensagem: string, conversaId: string | null) =>
  chama<RespostaChat>('/api/chat', { method: 'POST', ...json({ mensagem, conversa_id: conversaId }) })

// e no mesmo estilo: verificaSaude, buscaPeriodo, listaConversas, buscaMensagens, renomeiaConversa,
// apagaConversa, mudaNomeNaApi, apagaContaNaApi
```

## 3. `api/supabase.ts`

```ts
import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import type { ConfigPublica } from './tipos'

export class LoginNaoConfigurado extends Error {}

/** Retorno de um link do e-mail (ex.: recuperar senha): o Supabase devolve os tokens no `#` da
 *  URL. São lidos quando o módulo carrega, porque o roteador troca a URL antes do cliente ficar pronto. */
const hashInicial = new URLSearchParams(window.location.hash.slice(1))
export const retornoDoLink = {
  tipo: hashInicial.get('type'),        // 'recovery' = veio do link de recuperar senha
  invalido: hashInicial.has('error'),   // link vencido ou já usado
}
if (hashInicial.has('access_token') || hashInicial.has('error')) {
  history.replaceState(null, '', window.location.pathname + window.location.search)  // tira os tokens da barra
}

let promessa: Promise<SupabaseClient> | null = null

export function supabase(): Promise<SupabaseClient> {
  promessa ??= (async () => {
    const resposta = await fetch('/api/config')
    if (!resposta.ok) throw new LoginNaoConfigurado('A API não está respondendo.')
    const config = (await resposta.json()) as ConfigPublica
    if (!config.supabase_url || !config.supabase_publishable_key) {
      throw new LoginNaoConfigurado('Login não configurado: preencha SUPABASE_PUBLISHABLE_KEY no .env e reinicie a API.')
    }
    const cliente = createClient(config.supabase_url, config.supabase_publishable_key, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
    })
    const access_token = hashInicial.get('access_token')
    const refresh_token = hashInicial.get('refresh_token')
    if (access_token && refresh_token) {
      const { error } = await cliente.auth.setSession({ access_token, refresh_token })
      if (error) retornoDoLink.invalido = true
    }
    return cliente
  })().catch((erro) => {
    promessa = null // deixa tentar de novo depois (ex.: a API ainda estava subindo)
    throw erro
  })
  return promessa
}

export async function tokenAtual(): Promise<string | null> {
  const { data } = await (await supabase()).auth.getSession()
  return data.session?.access_token ?? null
}
```

## 4. Sessão

`contexto/contextoAuth.ts` (separado do provedor para o Fast Refresh do Vite funcionar):

```ts
import type { Session } from '@supabase/supabase-js'
import { createContext, useContext } from 'react'

export type Estado =
  | { fase: 'carregando' }
  | { fase: 'indisponivel'; motivo: string }
  | { fase: 'pronto'; sessao: Session | null }

export type Contexto = {
  estado: Estado
  nome: string
  email: string
  entra: (email: string, senha: string) => Promise<void>
  cadastra: (nome: string, email: string, senha: string) => Promise<'logado' | 'confirmar_email'>
  recupera: (email: string) => Promise<void>
  trocaSenha: (senha: string) => Promise<void>
  mudaNome: (nome: string) => Promise<void>
  apagaConta: () => Promise<void>
  sai: () => Promise<void>
}

export const ContextoAuth = createContext<Contexto | null>(null)

export function useAutenticacao(): Contexto {
  const contexto = useContext(ContextoAuth)
  if (!contexto) throw new Error('useAutenticacao fora do ProvedorAutenticacao')
  return contexto
}
```

`contexto/Autenticacao.tsx`:

```tsx
function traduz(mensagem: string): string {
  const m = mensagem.toLowerCase()
  if (m.includes('invalid login credentials')) return 'E-mail ou senha incorretos.'
  if (m.includes('email not confirmed')) return 'Confirme o seu e-mail antes de entrar (veja a caixa de entrada).'
  if (m.includes('already registered')) return 'Já existe uma conta com este e-mail.'
  // antes de "password should be": "New password should be different..." também casa com ele
  if (m.includes('should be different')) return 'Essa senha já está sendo usada. Escolha uma senha diferente da atual.'
  if (m.includes('password should be')) return 'A senha precisa ter pelo menos 6 caracteres.'
  if (m.includes('rate limit')) return 'Muitas tentativas seguidas. Espere alguns minutos e tente de novo.'
  if (m.includes('expired') || (m.includes('invalid') && m.includes('token'))) return 'Código inválido ou expirado.'
  if (m.includes('invalid') && m.includes('email')) return 'E-mail inválido.'
  return mensagem
}

export function ProvedorAutenticacao({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState<Estado>({ fase: 'carregando' })
  const [cliente, setCliente] = useState<SupabaseClient | null>(null)
  const escuta = useRef<{ unsubscribe: () => void } | null>(null)

  useEffect(() => {
    const efeito = { ativo: true }
    supabase()
      .then(async (c) => {
        setCliente(c)
        const { data: atual } = await c.auth.getSession()
        setEstado({ fase: 'pronto', sessao: atual.session })
        const { data } = c.auth.onAuthStateChange((_evento, sessao) => setEstado({ fase: 'pronto', sessao }))
        if (efeito.ativo) escuta.current = data.subscription
        else data.subscription.unsubscribe()
      })
      .catch((erro: Error) => setEstado({ fase: 'indisponivel', motivo: erro.message }))
    return () => {
      efeito.ativo = false
      escuta.current?.unsubscribe()
    }
  }, [])

  useEffect(() => {
    quandoSessaoExpirar(() => void cliente?.auth.signOut())  // 401 da API -> sai
  }, [cliente])

  const exige = () => {
    if (!cliente) throw new Error('O login ainda não está disponível.')
    return cliente
  }

  const valor: Contexto = {
    estado,
    nome: estado.fase === 'pronto' ? ((estado.sessao?.user.user_metadata?.nome as string | undefined) ?? '') : '',
    email: estado.fase === 'pronto' ? (estado.sessao?.user.email ?? '') : '',
    async entra(email, senha) {
      const { error } = await exige().auth.signInWithPassword({ email, password: senha })
      if (error) throw new Error(traduz(error.message))
    },
    async cadastra(nome, email, senha) {
      const { data, error } = await exige().auth.signUp({ email, password: senha, options: { data: { nome } } })
      if (error) throw new Error(traduz(error.message))
      return data.session ? 'logado' : 'confirmar_email'
    },
    async recupera(email) {
      const { error } = await exige().auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/redefinir-senha`,
      })
      if (error) throw new Error(traduz(error.message))
    },
    async trocaSenha(senha) {
      const { error } = await exige().auth.updateUser({ password: senha })
      if (error) throw new Error(traduz(error.message))
    },
    async mudaNome(nome) {
      await mudaNomeNaApi(nome)
      const { error } = await exige().auth.updateUser({ data: { nome } })
      if (error) throw new Error(traduz(error.message))
    },
    async apagaConta() {
      await apagaContaNaApi()
      retornoDoLink.tipo = null
      await cliente?.auth.signOut({ scope: 'local' })  // a conta já não existe: só limpa este navegador
    },
    async sai() {
      retornoDoLink.tipo = null  // um login novo nesta aba não volta para "criar senha nova"
      await encerraSessaoNaApi()
      await cliente?.auth.signOut()
    },
  }
  return <ContextoAuth.Provider value={valor}>{children}</ContextoAuth.Provider>
}
```

## 5. `App.tsx`

```tsx
function Protegida({ children }: { children: ReactNode }) {
  const { estado } = useAutenticacao()
  if (estado.fase === 'carregando') return <p className={estilos.carregando}>Carregando…</p>
  if (estado.fase === 'pronto' && estado.sessao) {
    return (
      <>
        <Cabecalho />
        <main className={estilos.conteudo}>{children}</main>
      </>
    )
  }
  return <Navigate to="/login" replace />
}

function Rotas() {
  return (
    <Routes>
      <Route path="/login" element={<PaginaLogin />} />
      <Route path="/redefinir-senha" element={<PaginaRedefinirSenha />} />
      <Route path="/importar" element={<Protegida><PaginaUpload /></Protegida>} />
      <Route path="/extrato" element={<Protegida><PaginaExtrato /></Protegida>} />
      <Route path="/dashboard" element={<Protegida><PaginaDashboard /></Protegida>} />
      <Route path="/conta" element={<Protegida><PaginaConta /></Protegida>} />
      <Route path="*" element={<Navigate to={retornoDoLink.tipo === 'recovery' ? '/redefinir-senha' : '/importar'} replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ProvedorAutenticacao>
        <Rotas />
      </ProvedorAutenticacao>
    </BrowserRouter>
  )
}
```

A página de login, com sessão aberta, redireciona para `/importar` (ou `/redefinir-senha` se veio
do link). No estado `indisponivel`, ela mostra o motivo (ex.: login não configurado).

## 6. `hooks/useTema.ts`

```ts
export type Tema = 'claro' | 'escuro'
const CHAVE = 'tas-tema-escolhido'

function temaInicial(): Tema {
  try {
    return localStorage.getItem(CHAVE) === 'escuro' ? 'escuro' : 'claro'
  } catch {
    return 'claro'
  }
}

export function useTema() {
  const [tema, setTema] = useState<Tema>(temaInicial)
  useEffect(() => {
    document.documentElement.dataset.tema = tema
  }, [tema])
  const alterna = () => {
    const novo: Tema = tema === 'claro' ? 'escuro' : 'claro'
    setTema(novo)
    try {
      localStorage.setItem(CHAVE, novo)  // só grava quando o usuário escolhe
    } catch {
      // sem localStorage: o tema vale só até recarregar a página
    }
  }
  return { tema, alterna }
}
```

## 7. `components/Grafico.tsx`

```tsx
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis } from 'recharts'

const CORES = Array.from({ length: 8 }, (_, i) => `var(--grafico-${i + 1})`)
const cor = (i: number) => CORES[i % CORES.length]
const eixo = { fontSize: 12, fill: 'var(--tinta-suave)' }
const dica = {
  contentStyle: { background: 'var(--superficie)', border: '1px solid var(--borda)', borderRadius: 10, color: 'var(--tinta)' },
  labelStyle: { color: 'var(--tinta)', fontWeight: 700 },
  cursor: { fill: 'var(--superficie-cabecalho)' },
}

export function Grafico({ dados, altura = 300, mostraTitulo = true }: Props) {
  const [ocultas, setOcultas] = useState<Set<string>>(new Set())
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
        // série escondida fica esmaecida na legenda
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
    const formataFatia = (v: unknown) => (total > 0 ? `${formata(v)} · ${Math.round((100 * Number(v)) / total)}%` : formata(v))
    grafico = (
      <PieChart>
        <Pie data={fatias} dataKey="valor" nameKey="rotulo" innerRadius="45%" outerRadius="80%" paddingAngle={1}>
          {fatias.map((f, i) => <Cell key={f.rotulo} fill={cor(i)} stroke="var(--superficie)" />)}
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
          <Line key={s.nome} dataKey={s.nome} stroke={cor(i)} strokeWidth={2.5} dot={{ r: 3 }} hide={ocultas.has(s.nome)} />
        ))}
      </LineChart>
    )
  } else if (dados.tipo === 'barras_horizontais') {
    grafico = (
      <BarChart data={linhas} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke="var(--grafico-grade)" strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" tick={eixo} tickFormatter={formataMoedaCurta} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="rotulo" tick={eixo} tickLine={false} axisLine={false} width={150} />
        <Tooltip {...dica} formatter={formata} />
        {dados.series.map((s, i) => <Bar key={s.nome} dataKey={s.nome} fill={cor(i)} radius={[0, 6, 6, 0]} maxBarSize={28} />)}
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
          <Bar key={s.nome} dataKey={s.nome} fill={cor(i)} radius={[6, 6, 0, 0]} maxBarSize={56} hide={ocultas.has(s.nome)} />
        ))}
      </BarChart>
    )
  }

  // gráficos horizontais crescem com o número de barras
  const alturaFinal = dados.tipo === 'barras_horizontais' ? Math.max(160, 44 * dados.rotulos.length + 40) : altura
  return (
    <figure className={estilos.figura}>
      {mostraTitulo && <figcaption className={estilos.titulo}>{dados.titulo}</figcaption>}
      <div style={{ width: '100%', height: alturaFinal }}>
        <ResponsiveContainer>{grafico}</ResponsiveContainer>
      </div>
    </figure>
  )
}
```

## 8. `utils/formatacao.ts` (trechos)

```ts
const moeda = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })
export const formataValor = (valor: string) => moeda.format(Number(valor))   // "-12.50" -> "-R$ 12,50"
export const formataMoeda = (valor: number) => moeda.format(valor)

const compacto = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', notation: 'compact', maximumFractionDigits: 1 })
export const formataMoedaCurta = (valor: number) => compacto.format(valor)   // "R$ 1,2 mil"

/** "2024-01-02" -> "02/01/2024" (sem passar por Date, para não sofrer com fuso) */
export function formataData(iso: string): string {
  const [ano, mes, dia] = iso.split('-')
  return ano && mes && dia ? `${dia}/${mes}/${ano}` : iso
}

export const rotuloContraparte = (c: string) => (c === 'PESSOA_FISICA' ? 'Pessoa física' : c)

export function plural(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`
}

// MEIOS, CATEGORIAS, FORMATOS (nome do parser -> "Nubank · conta (CSV)") e RECONCILIACAO são
// Record<string, string> com os rótulos da skill app-extratos (references/contratos.md).
export const LISTA_CATEGORIAS = Object.entries(CATEGORIAS)  // ordem de exibição no filtro e no seletor

const ENVIE_ORIGINAL = 'Envie o arquivo original exportado pelo banco, sem editar nem converter.'
const MOTIVOS: Record<string, string> = {
  FormatoNaoReconhecido: `Este arquivo não é de um formato suportado. Hoje o produto lê ${SUPORTADOS}. ${ENVIE_ORIGINAL}`,
  FormatoAmbiguo: `O arquivo parece com mais de um formato conhecido e não dá para escolher com segurança. ${ENVIE_ORIGINAL}`,
  HistoricoDesconhecido:
    'O extrato tem tipos de lançamento que ainda não conhecemos. Ele não foi processado para não errar a anonimização; avise a equipe para incluir esses tipos.',
  ReconciliacaoFalhou: `A soma dos lançamentos não bate com os totais do próprio extrato, então o resultado não seria confiável. ${ENVIE_ORIGINAL}`,
  erro_no_parser: `Houve um erro ao ler o arquivo. ${ENVIE_ORIGINAL} Se o erro continuar, avise a equipe.`,
  linhas_invalidas: 'Algumas linhas lidas não passaram na validação. Avise a equipe para conferir este formato.',
  segmentos_em_formato_sem_totais: 'O arquivo tem uma estrutura inesperada para este formato. Avise a equipe.',
}

/** Motivo da rejeição com o próximo passo; códigos sem tradução aparecem como vêm. */
export function rotuloMotivo(motivo: string): string {
  const codigo = motivo.split(':')[0]
  if (codigo === 'LayoutInesperado') {
    return `O arquivo tem algo fora do layout que conhecemos (${motivo}). ${ENVIE_ORIGINAL}`
  }
  return MOTIVOS[codigo] ?? motivo
}
```

## 9. `utils/exportacao.ts`

```ts
const COLUNAS = ['Data', 'Estabelecimento', 'Descrição', 'Meio', 'Banco', 'Categoria', 'Tipo', 'Valor']

/** Texto do extrato: aspas escapadas e, se começar com = + - @, um apóstrofo na frente para a
 *  planilha não executar como fórmula. */
function texto(valor: string): string {
  const seguro = /^[=+\-@\t\r]/.test(valor) ? `'${valor}` : valor
  return `"${seguro.replace(/"/g, '""')}"`
}

const numero = (valor: string) => Number(valor).toFixed(2).replace('.', ',')  // vírgula decimal

export function geraCsv(transacoes: TransacaoSalva[]): string {
  const linhas = transacoes.map((t) =>
    [
      formataData(t.data),
      texto(t.contraparte_original || (t.contraparte ? rotuloContraparte(t.contraparte) : '')),
      texto(t.historico_original || t.historico),
      texto(rotuloMeio(t.meio)),
      texto(t.banco),
      texto(t.categoria ? rotuloCategoria(t.categoria) : 'Sem categoria'),
      t.tipo === 'entrada' ? 'Entrada' : 'Saída',
      numero(t.valor),
    ].join(';'),
  )
  return '﻿' + [COLUNAS.join(';'), ...linhas].join('\r\n')  // BOM: sem ele o Excel lê os acentos errado
}

export function baixaCsv(transacoes: TransacaoSalva[], nomeArquivo: string) {
  const url = URL.createObjectURL(new Blob([geraCsv(transacoes)], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = nomeArquivo
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
```
