---
name: TAS – Transactions Assistancy Service
description: Ferramenta de trabalho limpa para importar extratos e ler transações anonimizadas e categorizadas.
colors:
  marca-amarelo: "#ffc11a"
  marca-laranja: "#fe7b02"
  marca-vermelho: "#ed0b2a"
  marca-magenta: "#d22093"
  marca-roxo: "#7b12cf"
  azul: "#006eb8"
  azul-texto: "#006cb4"
  sobre-acao: "#ffffff"
  selo-fundo: "#e6f0f8"
  selo-texto: "#042f54"
  verde: "#08804a"
  vermelho: "#e4243c"
  vermelho-fundo: "#fdecee"
  tinta: "#0d1b2d"
  tinta-suave: "#586474"
  fundo: "#f8fafd"
  superficie: "#ffffff"
  superficie-cabecalho: "#ecf1f5"
  borda: "#dce2e8"
typography:
  logotipo:
    fontFamily: "Manrope Variable, system-ui, Segoe UI, sans-serif"
    fontSize: "2.5rem"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.04em"
  display:
    fontFamily: "Manrope Variable, system-ui, Segoe UI, sans-serif"
    fontSize: "2.375rem"
    fontWeight: 800
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Manrope Variable, system-ui, Segoe UI, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 700
  lead:
    fontFamily: "Manrope Variable, system-ui, Segoe UI, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: "Manrope Variable, system-ui, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  title:
    fontFamily: "Manrope Variable, system-ui, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
  label:
    fontFamily: "Manrope Variable, system-ui, Segoe UI, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
  numero:
    fontFamily: "Manrope Variable, system-ui, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    fontFeature: "tnum"
rounded:
  grande: "18px"
  pilula: "999px"
spacing:
  xs: "0.35rem"
  sm: "0.9rem"
  md: "1.5rem"
  lg: "1.75rem"
  xl: "3rem"
components:
  navegacao-ativa:
    backgroundColor: "{colors.azul}"
    textColor: "{colors.sobre-acao}"
    rounded: "{rounded.pilula}"
    padding: "0.55rem 1.25rem"
  navegacao-inativa:
    backgroundColor: "transparent"
    textColor: "{colors.tinta-suave}"
    rounded: "{rounded.pilula}"
    padding: "0.55rem 1.25rem"
  navegacao-inativa-hover:
    textColor: "{colors.tinta}"
  botao-icone:
    backgroundColor: "transparent"
    textColor: "{colors.tinta-suave}"
    rounded: "{rounded.pilula}"
    size: "2.5rem"
  botao-icone-hover:
    backgroundColor: "{colors.superficie-cabecalho}"
    textColor: "{colors.tinta}"
  selo-categoria:
    backgroundColor: "{colors.selo-fundo}"
    textColor: "{colors.selo-texto}"
    rounded: "{rounded.pilula}"
    padding: "0.25rem 0.8rem"
  selo-sem-categoria:
    backgroundColor: "transparent"
    textColor: "{colors.tinta-suave}"
    rounded: "{rounded.pilula}"
    padding: "0.25rem 0.8rem"
  painel:
    backgroundColor: "{colors.superficie}"
    rounded: "{rounded.grande}"
    padding: "1.6rem 1.75rem 1.5rem"
  zona-upload:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.grande}"
    padding: "4.5rem 2rem"
  zona-upload-compacta:
    padding: "1.25rem 1.5rem"
  aviso-rejeicao:
    backgroundColor: "{colors.vermelho-fundo}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.grande}"
    padding: "1.15rem 1.5rem"
  cabecalho-tabela:
    backgroundColor: "{colors.superficie-cabecalho}"
    textColor: "{colors.tinta-suave}"
    typography: "{typography.title}"
    padding: "0.85rem 1.75rem"
---

# Design System: TAS – Transactions Assistancy Service

## Overview

**Creative North Star: "O Fio da Marca"**

O TAS é uma ferramenta de trabalho limpa: fundo azulado quase branco, superfícies brancas com borda fina, tinta azul-marinho e um único azul de ação. Toda a identidade da marca mora num só fio, o degradê amarelo → laranja → vermelho → magenta → roxo, que aparece em poucos lugares e sempre como marca, nunca como decoração de conteúdo: a faixa de 3px no topo do cabeçalho, o logotipo "tas" e o círculo do envio na zona de upload (e o contorno dela enquanto um arquivo é arrastado).

A densidade é de leitura confortável, não de painel apertado: blocos espaçados por 1.75rem, tabela com células generosas, números em algarismos tabulares. O sistema recusa o painel genérico cinza com um acento solto; a cor de conteúdo é semântica (verde para entrada, vermelho para saída e rejeição, azul-claro para os selos de categoria) e o degradê fica reservado à marca. A direção visual veio dos mockups do próprio usuário em `references/`, de onde a paleta foi amostrada.

Há dois temas, claro (padrão) e escuro (`[data-tema='escuro']` na raiz), escolhidos pela preferência do sistema e lembrados em `localStorage`. O escuro é derivado: os mesmos papéis, com valores próprios.

**Key Characteristics:**
- Um só fio de marca: o degradê de cinco paradas, em três lugares fixos.
- Superfícies brancas planas com borda de 1px e sombra quase imperceptível.
- Cantos amplos (18px) em blocos; pílula (999px) em tudo que é ação, selo ou navegação.
- Cor de conteúdo só semântica: verde entra, vermelho sai.
- Manrope Variable em toda a interface, pesos de 400 a 800.

## Colors

Uma paleta fria e contida de azul-marinho e branco, com o azul de ação como única cor sólida forte e o degradê quente da marca guardado para a identidade.

### Primary
- **Degradê da Marca** (`marca-amarelo` → `marca-laranja` → `marca-vermelho` → `marca-magenta` → `marca-roxo`, em 0/24/50/74/100%; versão diagonal a 135deg em 0/25/52/76/100%): a identidade do TAS. Horizontal na faixa do cabeçalho, no logotipo e no contorno da zona ao arrastar; diagonal no círculo do ícone de envio. Nunca em texto corrido, botões ou dados.
- **Azul de Ação** (`azul`): fundo da pílula de navegação ativa (texto `sobre-acao` branco) e cor do contorno de foco e da zona de upload em hover. No escuro passa a #1a6fb3, mantendo texto branco.
- **Azul de Texto** (`azul-texto`): texto azul sobre superfície: o "clique para abrir" da zona e o nome do produto em três linhas ao lado do logotipo. No escuro clareia para #6cb6f0 para manter a leitura.

### Secondary
- **Selo Azul-Névoa** (`selo-fundo` com `selo-texto`): selos de categoria e a seleção de texto. No escuro, #16304d com #cfe3f6.

### Tertiary
- **Verde Entrada** (`verde`): valores positivos, "N transações extraídas", ponto de API conectada. No escuro, #3cc882.
- **Vermelho Saída** (`vermelho`): valores negativos, "Extrato rejeitado", ícone do aviso, ponto de API fora. No escuro, #ff5c70.
- **Rosa Alerta** (`vermelho-fundo`): fundo do aviso de rejeição. No escuro, #3a1820.

### Neutral
- **Tinta Marinho** (`tinta`): títulos, texto principal, valores do resumo. No escuro, #e8eef6.
- **Tinta Suave** (`tinta-suave`): subtítulo, datas, rótulos, detalhes da transação, cabeçalho da tabela. No escuro, #97a4b5.
- **Fundo Gelo** (`fundo`): fundo da página e hover das linhas da tabela. No escuro, #0a1320.
- **Superfície** (`superficie`): cabeçalho, painéis, zona de upload, linha do arquivo. No escuro, #101c2c.
- **Superfície de Cabeçalho** (`superficie-cabecalho`): faixa de títulos da tabela e hover do botão de ícone. No escuro, #15243a.
- **Borda** (`borda`): bordas de 1px, tracejado da zona, divisórias da tabela, contorno do selo vazio, cor da barra de rolagem. No escuro, #22344d.

### Named Rules
**The Fio Único Rule.** O degradê da marca aparece só na faixa do cabeçalho, no logotipo, no círculo de envio e no contorno da zona ao arrastar. Uma nova tela não ganha um quinto lugar para ele.

**The Cor Que Significa Rule.** Verde e vermelho só dizem entrada/saída ou aceito/rejeitado. Categoria é sempre o selo azul-névoa, sem cor por categoria.

## Typography

**Display Font:** Manrope Variable (auto-hospedada via `@fontsource-variable/manrope`, com system-ui, Segoe UI, sans-serif)
**Body Font:** Manrope Variable (a mesma família)

**Character:** Uma única sans geométrica e amigável, com a hierarquia feita só por peso e tamanho: 800 apertado para título e logotipo, 600–700 para estrutura, 400 para leitura.

### Hierarchy
- **Logotipo** (800, 2.5rem, entrelinha 1, -0.04em): o "tas" em minúsculas com texto em degradê. 2rem no celular. Ao lado, o nome do produto em três linhas (800, 0.75rem, caixa alta, azul de texto; a primeira linha com 0.22em), oculto no celular. Esse bloco é o logotipo dos mockups, não um padrão de rótulo.
- **Display** (800, 2.375rem, 1.15, -0.02em): o título da página. 1.875rem no celular.
- **Headline** (700, 1.375rem): título de painel ("Transações extraídas"). A chamada da zona de upload usa o mesmo tamanho em 600 (1.0625rem quando compacta, 1.125rem no celular).
- **Lead** (400, 1.125rem, 1.5, até 68ch): subtítulo da página, em tinta suave. 1rem no celular.
- **Body** (400, 1rem, 1.5): texto geral; o nome do arquivo usa 1.0625rem. Parágrafos de aviso limitados a 70ch.
- **Title** (600, 0.9375rem): rótulos de coluna da tabela.
- **Label** (500, 0.8125rem): status da API, rótulos do resumo, detalhes da transação e dicas. O selo usa 0.875rem/500; a origem da categoria, 0.75rem.
- **Número** (600, algarismos tabulares): valores, datas e dados do resumo sempre com `font-variant-numeric: tabular-nums`.

### Named Rules
**The Coluna Alinhada Rule.** Todo número (valor, data, contagem) usa algarismos tabulares; valores alinham à direita.

## Layout

Coluna única centrada com largura máxima de 80rem e respiro de 3rem nas laterais (3rem topo, 5rem base); o cabeçalho segue a mesma largura com 0.85rem × 3rem. Os blocos da página empilham com 1.75rem de intervalo, e o resultado tem `scroll-margin-top` de 6rem para não ficar sob o cabeçalho fixo.

O cabeçalho é fixo no topo (`position: sticky`), com o logotipo à esquerda e navegação, status e tema empurrados à direita. A zona de upload ocupa a largura toda e encolhe para uma linha depois do primeiro resultado, para a tabela subir.

Há um único ponto de quebra, 720px. Abaixo dele: conteúdo com 1.75rem × 1rem, painéis com 1.25rem × 1.1rem, o nome do produto e o status da API somem, e cada linha da tabela vira um bloco em grade (descrição e valor em cima, data, depois categoria), com os títulos de coluna ocultos visualmente.

Ritmo: 0.35rem para pares próximos, 0.9rem entre ícone e texto, 1.5rem e 1.75rem para respiro interno de blocos, 3rem para a margem da página.

## Elevation & Depth

Quase plano. A profundidade vem da troca de tom (fundo gelo atrás, superfície branca na frente, faixa de cabeçalho da tabela um tom acima) e das bordas de 1px. Os painéis levam uma sombra ambiente quase imperceptível; o único volume real é o círculo de envio em degradê, com uma sombra avermelhada que o destaca como ação principal.

### Shadow Vocabulary
- **Ambiente** (`box-shadow: 0 1px 2px rgb(13 27 45 / 0.04), 0 4px 16px rgb(13 27 45 / 0.04)`; no escuro `0 1px 2px rgb(0 0 0 / 0.3), 0 4px 16px rgb(0 0 0 / 0.25)`): painel de resultado.
- **Brilho da Marca** (`box-shadow: 0 8px 24px rgb(237 11 42 / 0.22)`): só o círculo de envio.

### Named Rules
**The Tom Antes de Sombra Rule.** Separe camadas por tom e borda; a sombra ambiente é o máximo para superfícies de conteúdo.

## Shapes

Cantos amplos e macios em todo bloco (18px: painel, zona de upload, linha do arquivo, aviso) e pílula completa (999px) em tudo que se clica ou rotula: navegação, botão de ícone, selo de categoria. Círculos puros para o ícone de envio e o ponto de status. Bordas sempre de 1px sólidas, exceto a zona de upload, com 2px tracejados, que vira contorno em degradê ao arrastar.

## Components

### Buttons
Pílulas firmes e silenciosas.
- **Shape:** pílula (999px).
- **Primary (navegação ativa):** azul de ação com texto branco, 600, 0.55rem × 1.25rem (0.45rem × 0.9rem e 0.875rem no celular).
- **Hover / Focus:** inativa passa de tinta suave para tinta em 0.15s ease-out. Foco global: contorno de 2px azul com 2px de afastamento.
- **Ícone:** círculo de 2.5rem, transparente, ícone lucide de 20px em tinta suave; no hover ganha a superfície de cabeçalho e tinta.

### Chips
- **Selo de categoria:** pílula azul-névoa, 0.875rem/500, 0.25rem × 0.8rem, sem quebra de linha. A origem da categoria (regra ou modelo) não aparece para o usuário.
- **Sem categoria:** mesmo formato, fundo transparente, contorno interno de 1px na cor de borda, texto em tinta suave.

### Cards / Containers
- **Corner Style:** 18px.
- **Background:** superfície.
- **Shadow Strategy:** sombra ambiente só no painel de resultado; linha do arquivo e aviso são planos.
- **Border:** 1px de borda (o aviso de rejeição não tem borda; usa o fundo rosa).
- **Internal Padding:** painel 1.6rem × 1.75rem; linha do arquivo e aviso 1.15rem × 1.5rem.

### Navigation
Cabeçalho fixo em superfície com borda inferior de 1px e a faixa de 3px do degradê acima. Logotipo à esquerda, pílulas de navegação e ações (status da API com ponto de 0.5rem, botão de tema) à direita.

### Zona de Upload (assinatura)
A ação principal da página. Bloco de largura total com tracejado de 2px em borda, 4.5rem × 2rem, texto centrado. No centro, o círculo de 5rem com o degradê diagonal, ícone de envio branco (34px) e o brilho da marca. Hover: tracejado fica azul e o círculo sobe 4px (0.35s, `cubic-bezier(0.16, 1, 0.3, 1)`). Arrastando: o contorno vira o degradê e o fundo, azul-névoa. Enviando: o ícone vira um carregador girando (0.9s linear). Depois de um resultado, encolhe para uma linha (círculo de 3rem, ícone de 22px, sem a dica). Com `prefers-reduced-motion`, sem subida nem giro.

### Tabela de Transações
Dentro do painel, sem borda lateral. Cabeçalho na superfície de cabeçalho, células de 0.85rem × 1.75rem com divisória de 1px, hover de linha no fundo gelo (0.15s). Descrição em duas linhas (principal em tinta, detalhe em 0.8125rem tinta suave). Valor à direita, 600, verde ou vermelho. No celular, cada linha é um bloco em grade.

### Aviso de Rejeição
Fundo rosa alerta, ícone de alerta lucide em vermelho, título em 700 e explicação em tinta suave até 70ch. Diz sempre por que o arquivo foi rejeitado.

## Do's and Don'ts

### Do:
- **Do** usar os tokens de `index.css` por nome (`var(--tinta)`, `var(--borda)`) para que os dois temas funcionem sem código extra.
- **Do** manter o degradê da marca nos seus lugares fixos: faixa de 3px, logotipo, círculo de envio, contorno ao arrastar.
- **Do** usar 18px em blocos e pílula (999px) em ações, selos e navegação.
- **Do** usar algarismos tabulares em todo número e alinhar valores à direita.
- **Do** usar ícones lucide-react (20–22px na interface, 34px no círculo de envio) com `aria-hidden` quando decorativos.
- **Do** respeitar `prefers-reduced-motion` em qualquer movimento novo.

### Don't:
- **Don't** aplicar o degradê em texto que não seja o logotipo, nem em botões, selos ou dados.
- **Don't** usar verde ou vermelho fora de entrada/saída e aceito/rejeitado, nem dar cor própria a cada categoria.
- **Don't** escrever cores literais nos módulos (fora o branco sobre o azul de ação e sobre o círculo de envio); toda cor nova entra como token nos dois temas.
- **Don't** citar a TCS por nome na interface; só o TAS aparece.
