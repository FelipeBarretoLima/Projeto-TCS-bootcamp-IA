---
name: app-extratos-frontend
description: Como construir o frontend (React + TypeScript + Vite) de uma aplicação de extratos bancários. Cobre login, cadastro e recuperação de senha com Supabase Auth, importação de extrato com zona de arrastar e explicação da rejeição, aba Extrato com filtros na URL, busca, correção de categoria otimista e exportação para Excel, dashboard com cartões do mês, gráficos Recharts e chat com o assistente, página da conta (LGPD), cliente único da API, tipos espelhando a API, tema claro/escuro com tokens CSS e o design system de referência. Use sempre que for criar ou mudar páginas, componentes, gráficos, o chat, a chamada à API, o login no navegador, o tema ou o visual da aplicação de extratos.
---

# Camada do frontend (`frontend/`)

React 19 + TypeScript + Vite, sem biblioteca de componentes. Dependências: `react-router`,
`@supabase/supabase-js`, `recharts`, `lucide-react`, `react-day-picker` (campo de data) e
`@fontsource-variable/manrope` (fonte auto-hospedada). Lint com `oxlint`. Node.js 22 (ou 20.19+).

```
frontend/
  index.html          lang="pt-BR"; script que aplica o tema antes da primeira pintura
  vite.config.ts      proxy: '/api' -> http://localhost:8000
  src/
    main.tsx, App.tsx       rotas e o invólucro das páginas protegidas
    index.css               tokens de cor (claro e escuro), fonte, foco, seleção
    api/cliente.ts          TODAS as chamadas à API (token, erros, 401)
    api/supabase.ts         cliente do Supabase Auth com a configuração vinda de /api/config
    api/tipos.ts            espelho de api/schemas.py
    contexto/               sessão (Autenticacao.tsx = provedor; contextoAuth.ts = contexto + hook)
    hooks/useTema.ts        tema claro/escuro lembrado no localStorage
    pages/                  uma tela por arquivo, com o seu .module.css
    components/             peças da tela, cada uma com o seu .module.css
    utils/formatacao.ts     R$, datas, rótulos dos códigos da API, motivos de rejeição
    utils/exportacao.ts     CSV para o Excel em português
```

## Decisões (e por quê)

- **Sempre `/api/...`, sem endereço.** Em desenvolvimento o Vite repassa para a API; publicado,
  a própria API serve a página. Não há CORS nem `.env` no frontend.
- **Configuração do login vem da API** (`GET /api/config`): a URL do Supabase e a chave
  publishable. O cliente do Supabase é criado uma vez, sob demanda, e tenta de novo se a API ainda
  estava subindo.
- **Um cliente só** (`api/cliente.ts`) põe `Authorization: Bearer <token>`, transforma
  `{"detail"}` em `ErroApi(mensagem, status)` e, no 401, avisa o provedor de sessão para sair. Um
  502/504 sem corpo JSON quer dizer "a API está fora": mostre como iniciá-la.
- **`api/tipos.ts` espelha `api/schemas.py`.** Ao mudar uma resposta, mude os dois. `valor` das
  transações chega como texto (`"-12.50"`); totais do painel e gráficos, como número.
- **Estados como uniões discriminadas** (`{fase: 'inicial'} | {fase: 'enviando'} | ...`), em vez
  de vários booleanos.
- **Datas sem `Date`**: `"2024-01-02"` vira `"02/01/2024"` por texto, para não sofrer com o fuso.
  Dinheiro com `Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'})` e a versão
  compacta ("R$ 1,2 mil") nos eixos dos gráficos.
- **Códigos da API traduzidos num lugar só** (`formatacao.ts`): meio, categoria, parser,
  reconciliação, `PESSOA_FISICA` → "Pessoa física", e cada motivo de rejeição com o problema e
  o próximo passo ("Envie o arquivo original exportado pelo banco, sem editar nem converter.").
  Código desconhecido aparece como veio.
- **O dono vê o texto original.** A tabela mostra `contraparte_original`/`historico_original`
  quando existem; senão, o anonimizado. A página diz que o arquivo é descartado e que o
  classificador e o assistente só usam a versão anonimizada.
- **Mesmas regras da API antes de enviar** (extensão, vazio, 10 MB), com as mesmas mensagens, para
  não mandar um arquivo grande pela rede à toa.
- **Interface em português do Brasil**, frases curtas, sem jargão.

## Rotas

| Rota | Página | Login |
|---|---|---|
| `/login` | entrar, criar conta, recuperar senha (três modos na mesma tela) | não |
| `/redefinir-senha` | senha nova, aberta pelo link do e-mail | sessão do link |
| `/importar` | importar extrato (abre depois do login) | sim |
| `/extrato` | transações salvas | sim |
| `/dashboard` | cartões, gráfico e assistente | sim |
| `/conta` | nome e exclusão da conta | sim |
| `*` | `/importar`, ou `/redefinir-senha` se veio do link de recuperação | |

`Protegida` envolve as páginas com login: enquanto a sessão carrega mostra "Carregando…"; sem
sessão vai para `/login`; com sessão mostra o cabeçalho e a página.

## Login (Supabase Auth no navegador)

- `createClient(url, chave, {auth: {persistSession: true, autoRefreshToken: true,
  detectSessionInUrl: false}})`.
- **Links do e-mail** (recuperar senha): o Supabase devolve os tokens no `#` da URL. Leia o `#`
  quando o módulo carrega, antes de o roteador trocar a URL, guarde o tipo (`recovery`), limpe a
  barra de endereço (`history.replaceState`) e abra a sessão com `auth.setSession(...)`.
- **Provedor de sessão** com estado `carregando | indisponivel(motivo) | pronto(sessao)`, ouvindo
  `onAuthStateChange`. Expõe `entra`, `cadastra` (`signUp` com `options.data.nome`; devolve
  `'logado'` ou `'confirmar_email'`), `recupera` (`resetPasswordForEmail` com `redirectTo:
  <origem>/redefinir-senha`), `trocaSenha`, `mudaNome` (API + metadados do login), `apagaConta`
  (API, depois `signOut({scope: 'local'})`) e `sai` (`DELETE /api/sessao`, depois `signOut`).
- **Mensagens do Supabase em português** ("Invalid login credentials" → "E-mail ou senha
  incorretos.", "already registered", "should be different", "password should be", "rate
  limit", token expirado, e-mail inválido).
- No Supabase (Authentication > URL Configuration), o endereço publicado vai em **Site URL** e em
  **Redirect URLs**.

## Páginas

**Importar extrato**
- Zona de arrastar ou clicar, que encolhe para uma linha depois do primeiro resultado. Um
  arquivo por vez ("Você soltou 3 arquivos. Envie um extrato por vez.").
- Resultado aceito: frase da gravação ("12 transações novas salvas na sua conta. 3 já existiam de
  um extrato anterior e não foram contadas de novo."), resumo (formato, período, conferência, sem
  categoria, em revisão, com aviso se alguma linha ficou fora por anonimização), tabela e link
  para o dashboard.
- Rejeitado: aviso com o motivo traduzido. Repetido (409): aviso + botão que rola até a lista
  para excluir o extrato anterior.
- Lista de extratos importados com exclusão confirmada na própria linha ("Excluir? 42
  transações serão removidas."), recarregada a cada importação gravada.
- A rolagem até o resultado respeita `prefers-reduced-motion`.

**Extrato**
- Filtros na URL (`?inicio=&fim=&categoria=&busca=`), lembrados em `sessionStorage` entre visitas
  enquanto não chegar transação nova.
- Primeiro busca o período (`/transacoes/periodo`) e, se a URL veio sem filtros, aplica o padrão
  (últimos 6 meses até o mês da última transação, igual ao dashboard). Só então busca as
  transações.
- Troca de filtro cancela a busca anterior (`AbortController`); período invertido não busca.
- Busca por texto no navegador, sem acento e sem maiúsculas, no original e no anonimizado.
- Paginação "Mostrar mais" (100 por vez), que volta ao começo quando o filtro muda.
- **Correção de categoria**: um `<select>` por linha. Muda na tela na hora, desativa o seletor
  enquanto grava e volta atrás se a API recusar.
- Totais de entradas e saídas do filtro. Como no dashboard, transações `financeiro` ficam fora
  dos totais (a compra no cartão e o pagamento da fatura contariam duas vezes), a não ser que o
  filtro seja a própria categoria Financeiro.
- **Exportar CSV** (separador `;`, vírgula decimal, BOM, proteção contra fórmula em células de
  texto).

**Dashboard**
- Saudação com o primeiro nome. Seletor de mês (se houver mais de um, com "(mais recente)") e
  cartões de receitas, despesas e saldo do mês (verde/vermelho), com o gráfico receitas x despesas
  dos 6 meses até ele. Ao trocar o mês, os cartões ficam esmaecidos até chegar a resposta.
- Sem dados: convite para importar o primeiro extrato.
- **Assistente** embaixo: lista de conversas (a mais recente abre ao entrar), nova conversa,
  renomear (Enter ou sair do campo, sem gravar duas vezes), apagar com confirmação, sugestões de
  pergunta, a pergunta aparece na hora (provisória) e é trocada pela versão gravada, um indicador
  de espera até a resposta chegar, e gráfico dentro da resposta. Não deixa trocar ou apagar conversa enquanto uma
  resposta está a caminho.

**Conta**: muda o nome (perfil + metadados do login); excluir a conta pede para digitar
`EXCLUIR` e avisa que é sem volta.

## Gráficos (`components/Grafico.tsx`)

Desenha o contrato do gráfico da API com Recharts:
- `barras`: `BarChart` vertical, eixo Y com moeda compacta, legenda clicável para esconder uma
  série quando há mais de uma;
- `barras_horizontais`: `layout="vertical"`, altura cresce com o número de barras;
- `linha`: `LineChart`;
- `pizza`: `PieChart` em rosca; o tooltip mostra valor e % ("R$ 300,00 · 27%").

Cores das séries por tokens (`var(--grafico-1)` a `var(--grafico-8)`, com valores próprios no
tema escuro), tooltip com as cores da superfície e números em `tabular-nums`. Código em
[references/codigo-base.md](references/codigo-base.md).

## Visual

Design system da referência (tokens, tipografia, componentes e regras) em
[references/design.md](references/design.md). O essencial:
- tokens CSS no `:root` e redefinidos em `:root[data-tema='escuro']`; componentes só usam
  `var(--...)`, nunca cores literais;
- o degradê da marca só em lugares fixos (faixa do cabeçalho, logotipo, círculo de envio);
- verde e vermelho só para entrada/saída e aceito/rejeitado; categoria sempre no mesmo selo
  neutro, sem cor por categoria;
- números com algarismos tabulares e alinhados à direita;
- ícones `lucide-react` com `aria-hidden` quando decorativos; foco visível; `aria-label` nos
  botões de ícone; `prefers-reduced-motion` em todo movimento;
- um ponto de quebra (720px): no celular, cada linha da tabela vira um bloco.

Se o produto tiver outra marca, troque os valores dos tokens e o logotipo, e mantenha as regras.

## Rodar e verificar

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 (a API precisa estar em :8000)
npm run build    # tsc -b (confere os tipos) + vite build -> dist/ (servido pela API)
npm run lint     # oxlint
```

A referência não tem testes automatizados no frontend. A verificação é `npm run build` e
`npm run lint` sem erros, mais os fluxos à mão: criar conta, entrar, importar (aceito, rejeitado,
repetido), excluir extrato, filtrar e corrigir no Extrato, exportar, trocar o mês no dashboard,
perguntar ao assistente, tema escuro, celular (720px) e excluir a conta. Se quiser testes, comece
pelos utilitários puros (`formatacao.ts`, `exportacao.ts`) com Vitest.
