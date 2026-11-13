# Design system de referência

O visual do projeto de referência: uma ferramenta de trabalho limpa, com fundo azulado quase
branco, superfícies brancas com borda fina, tinta azul-marinho e um único azul de ação. A marca
mora num só "fio": um degradê quente que aparece em poucos lugares fixos. Se o seu produto tiver
outra marca, troque os valores dos tokens e o logotipo, e mantenha as regras.

## Sumário

1. Tokens de cor (claro e escuro)
2. Tipografia
3. Layout e forma
4. Componentes
5. Regras

## 1. Tokens de cor (`src/index.css`)

```css
@import '@fontsource-variable/manrope';

:root {
  --marca-degrade: linear-gradient(90deg, #ffc11a 0%, #fe7b02 24%, #ed0b2a 50%, #d22093 74%, #7b12cf 100%);
  --marca-degrade-diagonal: linear-gradient(135deg, #ffc11a 0%, #fe7b02 25%, #ed0b2a 52%, #d22093 76%, #7b12cf 100%);

  --tinta: #0d1b2d;               /* títulos e texto principal */
  --tinta-suave: #586474;         /* subtítulos, datas, rótulos, cabeçalho da tabela */
  --fundo: #f8fafd;               /* fundo da página e hover de linha */
  --superficie: #ffffff;          /* cabeçalho, painéis, zona de upload */
  --superficie-cabecalho: #ecf1f5;/* faixa de títulos da tabela, hover de botão de ícone */
  --borda: #dce2e8;
  --azul: #006eb8;                /* ação: navegação ativa, foco, hover da zona */
  --azul-hover: #005a98;
  --azul-texto: #006cb4;          /* texto azul sobre superfície */
  --selo-fundo: #e6f0f8;          /* selo de categoria e seleção de texto */
  --selo-texto: #042f54;
  --grafico-1: #006eb8;           /* 1 = receitas e 2 = despesas nos gráficos de duas séries */
  --grafico-2: #e5196a;
  --grafico-3: #fe7b02;
  --grafico-4: #7b12cf;
  --grafico-5: #08804a;
  --grafico-6: #c99a00;
  --grafico-7: #0f9fb0;
  --grafico-8: #8a94a3;
  --grafico-grade: #e3e8ee;
  --verde: #08804a;               /* entrada, aceito, API conectada */
  --vermelho: #e4243c;            /* saída, rejeitado, API fora */
  --vermelho-fundo: #fdecee;      /* fundo do aviso de rejeição */
  --sombra: 0 1px 2px rgb(13 27 45 / 0.04), 0 4px 16px rgb(13 27 45 / 0.04);

  --raio: 12px;
  --raio-grande: 18px;
  --fonte: 'Manrope Variable', system-ui, 'Segoe UI', sans-serif;

  font: 400 1rem/1.5 var(--fonte);
  color: var(--tinta);
  background: var(--fundo);
  color-scheme: light;
  -webkit-font-smoothing: antialiased;
}

:root[data-tema='escuro'] {
  --tinta: #e8eef6;
  --tinta-suave: #97a4b5;
  --fundo: #0a1320;
  --superficie: #101c2c;
  --superficie-cabecalho: #15243a;
  --borda: #22344d;
  --azul: #1a6fb3;
  --azul-hover: #155f9b;
  --azul-texto: #6cb6f0;
  --selo-fundo: #16304d;
  --selo-texto: #cfe3f6;
  --grafico-1: #3d9be0;
  --grafico-2: #ff4f8f;
  --grafico-3: #ff9a3c;
  --grafico-4: #a95cf0;
  --grafico-5: #3cc882;
  --grafico-6: #f0c43c;
  --grafico-7: #38c6d6;
  --grafico-8: #8e9bb0;
  --grafico-grade: #22344d;
  --verde: #3cc882;
  --vermelho: #ff5c70;
  --vermelho-fundo: #3a1820;
  --sombra: 0 1px 2px rgb(0 0 0 / 0.3), 0 4px 16px rgb(0 0 0 / 0.25);
  color-scheme: dark;
}

*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; min-height: 100svh; }
h1, h2 { margin: 0; color: var(--tinta); text-wrap: balance; }
::selection { background: var(--selo-fundo); color: var(--selo-texto); }
:focus-visible { outline: 2px solid var(--azul); outline-offset: 2px; }
* { scrollbar-color: var(--borda) transparent; }
```

O tema padrão é o claro; o escuro só vale quando o usuário escolhe no botão, e a escolha fica no
`localStorage`. Um script no `index.html` aplica `data-tema` antes da primeira pintura, para a
página não piscar no tema errado.

## 2. Tipografia

Uma família só (Manrope Variable, de 400 a 800). A hierarquia vem só de peso e tamanho.

| Papel | Peso, tamanho | Uso |
|---|---|---|
| Logotipo | 800, 2.5rem, entrelinha 1, -0.04em | nome do produto em minúsculas, com o texto no degradê (2rem no celular) |
| Display | 800, 2.375rem, 1.15, -0.02em | título da página (1.875rem no celular) |
| Headline | 700, 1.375rem | título de painel ("Transações extraídas") |
| Lead | 400, 1.125rem, 1.5, até 68ch | subtítulo da página, em tinta suave |
| Body | 400, 1rem, 1.5 | texto geral; avisos até 70ch |
| Title | 600, 0.9375rem | rótulos de coluna da tabela |
| Label | 500, 0.8125rem | status da API, rótulos do resumo, detalhes, dicas |
| Número | 600, `font-variant-numeric: tabular-nums` | valores, datas, contagens |

## 3. Layout e forma

- Coluna única centrada, largura máxima de 80rem, 3rem de respiro nas laterais (3rem no topo,
  5rem embaixo). Blocos empilhados com 1.75rem de intervalo.
- Cabeçalho fixo (`position: sticky`) com uma faixa de 3px do degradê no topo, o logotipo à
  esquerda e navegação, status da API, conta, tema e sair à direita.
- Um ponto de quebra, **720px**: conteúdo com 1.75rem × 1rem, painéis com 1.25rem × 1.1rem, o
  nome do produto e o status da API somem, e cada linha da tabela vira um bloco em grade
  (descrição e valor em cima, data, depois categoria).
- Cantos de **18px** em blocos (painel, zona de upload, linha do arquivo, aviso) e **pílula
  (999px)** em tudo que se clica ou rotula (navegação, botão de ícone, selo).
- Quase plano: profundidade por troca de tom e bordas de 1px. A sombra ambiente (`--sombra`) é o
  máximo em superfícies de conteúdo. O único volume real é o círculo de envio
  (`box-shadow: 0 8px 24px rgb(237 11 42 / 0.22)`).

## 4. Componentes

- **Navegação**: pílulas; a ativa em azul de ação com texto branco (600, 0.55rem × 1.25rem); a
  inativa em tinta suave, que vira tinta no hover (0.15s).
- **Botão de ícone**: círculo de 2.5rem, transparente, ícone lucide de 20px em tinta suave; no
  hover, superfície de cabeçalho e tinta. Sempre com `aria-label` e `title`.
- **Selo de categoria**: pílula azul-névoa (`--selo-fundo`/`--selo-texto`), 0.875rem/500,
  0.25rem × 0.8rem. "Sem categoria": fundo transparente, contorno interno de 1px na cor da borda,
  texto em tinta suave. A origem da categoria não aparece para o usuário.
- **Painel**: superfície, 18px, borda de 1px, sombra ambiente, 1.6rem × 1.75rem.
- **Zona de upload** (assinatura da página): largura total, tracejado de 2px na cor da borda,
  4.5rem × 2rem, texto centrado. No centro, círculo de 5rem com o degradê diagonal e o ícone de
  envio branco (34px). Hover: tracejado azul e o círculo sobe 4px (0.35s,
  `cubic-bezier(0.16, 1, 0.3, 1)`). Arrastando: contorno no degradê e fundo azul-névoa.
  Enviando: o ícone vira um carregador girando (0.9s linear). Depois do primeiro resultado,
  encolhe para uma linha (círculo de 3rem, ícone de 22px). Com `prefers-reduced-motion`, sem
  subida nem giro.
- **Tabela de transações**: dentro do painel, cabeçalho em superfície de cabeçalho, células de
  0.85rem × 1.75rem com divisória de 1px, hover de linha no fundo gelo. Descrição em duas linhas
  (principal em tinta; detalhe "histórico · meio" em 0.8125rem, tinta suave). Valor à direita,
  600, verde (entrada) ou vermelho (saída).
- **Aviso de rejeição**: fundo rosa (`--vermelho-fundo`), sem borda, ícone de alerta em
  vermelho, título em 700 e explicação em tinta suave até 70ch. Sempre diz por que e o que fazer.
- **Cartões do dashboard**: rótulo em tinta suave e valor grande com algarismos tabulares
  (receitas em verde, despesas em vermelho, saldo conforme o sinal).

## 5. Regras

- **Fio único**: o degradê da marca aparece só na faixa do cabeçalho, no logotipo, no círculo de
  envio e no contorno da zona ao arrastar. Uma tela nova não ganha um quinto lugar para ele, e
  ele nunca vai em texto corrido, botões, selos ou dados.
- **Cor que significa**: verde e vermelho só dizem entrada/saída ou aceito/rejeitado. Categoria é
  sempre o selo azul-névoa, sem cor própria por categoria.
- **Coluna alinhada**: todo número usa algarismos tabulares; valores alinham à direita.
- **Tom antes de sombra**: separe camadas por tom e borda.
- **Tokens sempre**: nenhuma cor literal nos módulos CSS (fora o branco sobre o azul de ação e
  sobre o círculo de envio). Toda cor nova vira token nos dois temas.
- **Movimento opcional**: todo movimento novo respeita `prefers-reduced-motion`.
- **Ícones**: lucide-react, 20 a 22px na interface, `aria-hidden` quando decorativos.
