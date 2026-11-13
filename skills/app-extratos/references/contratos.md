# Contratos entre as camadas

Fonte única dos nomes e valores que atravessam a aplicação. Mudar qualquer item aqui exige mudar
todas as camadas que o usam, no mesmo commit, e os testes que comparam as camadas.

## Sumário

1. Linha do CSV do parser
2. `meio` (forma de pagamento)
3. Categorias e origem da categoria
4. Relatório do arquivo e códigos de rejeição
5. Nome do parser
6. Gráfico
7. Rotas da API

## 1. Linha do CSV do parser

Cabeçalho, nesta ordem: `id_usuario,data,historico,contraparte,valor,tipo,meio,banco`.
Arquivo em UTF-8 sem BOM, separador vírgula, fim de linha `\n`, gravado num `.tmp` e renomeado no
fim (nunca fica um CSV pela metade).

| Coluna | Formato | Regra |
|---|---|---|
| `id_usuario` | `u` + 2 dígitos (`u07`) | pseudônimo, nunca o nome. Na API o dono real vem do login; a coluna não vai para o banco |
| `data` | `AAAA-MM-DD` | data do lançamento |
| `historico` | texto | tipo do lançamento como o banco escreve, normalizado: maiúsculas (Unicode NFC, acentos mantidos), espaços simples, sem tokens que tenham dígito e sem pontuação solta. Ex.: `PIX ENVIADO`, `COMPRA NO DÉBITO` |
| `contraparte` | texto | nome da empresa anonimizado e em maiúsculas, `PESSOA_FISICA` quando é uma pessoa, ou vazio |
| `valor` | decimal com 2 casas | nunca zero; negativo = dinheiro saiu |
| `tipo` | `entrada` \| `saida` | coerente com o sinal de `valor` |
| `meio` | enum (seção 2) | vem de um mapa explícito histórico → meio em cada parser |
| `banco` | slug `[a-z][a-z0-9_]*` | `nubank`, `bradesco`, `inter`... |

O ML acrescenta `categoria` no fim (CSV rotulado = as mesmas 8 colunas + `categoria`). Na
inferência, o modelo recebe as 8 colunas e ignora `id_usuario` e `data`.

O marcador `PESSOA_FISICA` substitui o nome de qualquer pessoa: PIX/TED para pessoa física,
vendedor autônomo na maquininha, etc. Ele é um valor fixo de propósito: nunca vaza nada.

## 2. `meio` (forma de pagamento)

| Valor | Significado |
|---|---|
| `pix` | PIX enviado ou recebido |
| `ted_doc` | TED/DOC |
| `boleto` | pagamento ou recebimento por boleto |
| `cartao_debito` | compra no débito |
| `cartao_credito` | compra no crédito (lançamento da fatura) |
| `pagamento_fatura` | pagamento da fatura do cartão pela conta |
| `tarifa` | tarifa bancária, anuidade |
| `juros_iof` | juros, multa, IOF |
| `investimento` | aplicação ou resgate |
| `rendimento` | rendimento creditado |
| `salario` | salário, crédito de folha |
| `saque` | saque |
| `estorno` | estorno, reembolso, devolução |
| `transferencia_interna` | entre contas da mesma pessoa no mesmo banco |
| `outros` | recarga de celular, crédito avulso etc. |

## 3. Categorias e origem da categoria

| Código | Rótulo na tela | O que entra |
|---|---|---|
| `mercado` | Mercado | supermercado, padaria, açougue, hortifruti, conveniência |
| `alimentacao_fora` | Alimentação fora | restaurante, lanchonete, delivery, bar, café |
| `transporte` | Transporte | aplicativo de corrida, combustível, pedágio, estacionamento, oficina |
| `compras` | Compras | lojas, e-commerce, roupas, eletrônicos (é também a "classe de dúvida" do modelo) |
| `contas_servicos` | Contas e serviços | boletos, assinaturas, telefone, energia, farmácia, saúde, academia, recarga |
| `transferencia_pessoa` | Transferência p/ pessoa | PIX/TED para pessoa física, pagamento a pessoa na maquininha |
| `receitas` | Receitas | dinheiro recebido |
| `financeiro` | Financeiro | pagamento da fatura, aplicação em investimento, tarifa, juros, saque, transferência entre contas próprias |

Na importação, **toda entrada vira `receitas`** (inclusive estorno, rendimento e resgate de
investimento: decisão da referência, que o usuário pode corrigir na aba Extrato). Nos rótulos de
treino, as regras mandam essas entradas para `financeiro`, mas isso só afeta o treino, porque o
modelo só classifica saídas. O agente abate o estorno da compra correspondente.

Sem categoria = `null` no banco e no JSON. Nos filtros da API e do frontend, o valor
`sem_categoria` pede só as transações sem categoria.

**Despesa** = saída que não é `financeiro` (pagar a fatura não é um gasto novo: o gasto já está
nas compras do cartão). **Receita** = entrada da categoria `receitas`.

`origem_categoria`:

| Valor | Quando |
|---|---|
| `regra` | entrada → `receitas` (regra fixa na importação) |
| `mapa` | reservado para rótulo vindo do mapa de estabelecimentos (a referência não usa na inferência) |
| `modelo` | saída classificada pelo `.pkl` |
| `usuario` | correção feita pelo dono na aba Extrato (vira exemplo de retreino) |

No banco, `categoria` e `origem_categoria` estão as duas preenchidas ou as duas vazias.

## 4. Relatório do arquivo e códigos de rejeição

Cada arquivo processado gera um relatório só com contagens e códigos, nada do conteúdo:

| Campo | Conteúdo |
|---|---|
| `status` | `aceito` \| `rejeitado` |
| `motivo` | código da rejeição (tabela abaixo) ou vazio |
| `parser` | nome do parser que reconheceu o arquivo |
| `periodo_inicio`, `periodo_fim` | primeira e última data extraída (`AAAA-MM-DD`) |
| `linhas_extraidas` | lançamentos lidos do documento |
| `linhas_gravadas` | linhas que foram para a saída |
| `linhas_revisar` | linhas tiradas da saída por anonimização ambígua (vão para a revisão privada) |
| `linhas_duplicadas` | lançamentos que o próprio documento repete |
| `linhas_omitidas` | lançamentos que não são movimento novo (ex.: pagamento da fatura dentro da fatura) |
| `reconciliacao` | `ok`, `ok_com_documentos_rejeitados`, `sem_totais`, `falhou`, `nao_executada` |

A CLI grava também `arquivo`, `documentos_rejeitados`, `historicos_desconhecidos`, `segmentos` e
`segmentos_divergentes`.

| `motivo` | Quando | O que dizer ao usuário |
|---|---|---|
| `FormatoNaoReconhecido` | nenhum parser reconhece o arquivo | listar os formatos suportados e pedir o arquivo original exportado pelo banco |
| `FormatoAmbiguo` | mais de um parser reconhece | pedir o arquivo original |
| `LayoutInesperado:<motivo>[@p<página>]` | algo fora do layout conhecido (`linha_desconhecida`, `cabecalho`, `valor`...) | pedir o arquivo original, sem editar nem converter |
| `HistoricoDesconhecido` | tipo de lançamento fora do mapa do parser | avisar a equipe para incluir o tipo; nada foi processado para não errar a anonimização |
| `ReconciliacaoFalhou` | a soma não bate com os totais do documento | o resultado não seria confiável; pedir o arquivo original |
| `erro_no_parser:<Tipo>` | exceção inesperada no parser (só o tipo, nunca a mensagem) | avisar a equipe |
| `linhas_invalidas:<n>` | linhas que não passaram na validação do modelo da linha | avisar a equipe |
| `segmentos_em_formato_sem_totais` | estrutura inesperada num formato sem totais | avisar a equipe |
| `documentos_rejeitados:<doc;doc>` | arquivo aceito, mas alguns documentos internos não bateram (`fatura 2026-08-10`) | informar que esses documentos ficaram de fora |

Possível vazamento de dado pessoal detectado na saída (`VazamentoDetectado`) não é um motivo de
arquivo: a gravação inteira é bloqueada (CLI sai com código 2, API responde 422).

## 5. Nome do parser

`<banco>_<produto>_<extensão>`, por exemplo `nubank_conta_csv`, `bradesco_cartao_pdf`,
`nubank_fatura_pdf`. Ele fica gravado em `extratos.parser` e o frontend o traduz para um rótulo
("Nubank · conta (CSV)"). Por isso o nome de um parser nunca muda depois de publicado.

## 6. Gráfico

Gerado pelas consultas do agente, gravado em `mensagens.grafico` (jsonb) e desenhado pelo frontend:

```json
{
  "tipo": "barras",
  "titulo": "Gastos por mês (jun/24 a nov/24)",
  "rotulos": ["jun/24", "jul/24", "ago/24"],
  "series": [{"nome": "Gastos", "valores": [1234.5, 980.0, 1500.25]}],
  "formato": "moeda"
}
```

| `tipo` | Uso | Séries |
|---|---|---|
| `barras` | valores por mês | 1 ou 2 (receitas x despesas) |
| `barras_horizontais` | rankings (maiores gastos, estabelecimentos) | 1 |
| `linha` | evolução do saldo | 2 (saldo do mês e acumulado) |
| `pizza` | divisão por categoria | 1 (a fatia mostra valor e %) |

Rótulos de mês: `jan/24`, `fev/24`... Uma resposta do chat tem no máximo um gráfico.

## 7. Rotas da API

Todas sob `/api`. Detalhes (corpos, respostas, erros) na skill `app-extratos-api`.

| Método e rota | Login | Para quê |
|---|---|---|
| `GET /saude` | não | a API está no ar |
| `GET /config` | não | URL e chave publishable do Supabase para o login no navegador |
| `DELETE /sessao` | token | logout: a API esquece o token na hora |
| `POST /extratos` | sim | importa um arquivo (multipart, campo `arquivo`) |
| `GET /extratos` | sim | extratos importados |
| `DELETE /extratos/{id}` | sim | exclui o extrato e as transações que só ele trouxe |
| `GET /transacoes/periodo` | sim | primeira e última data e o filtro padrão (6 meses) |
| `GET /transacoes?inicio&fim&categoria` | sim | transações salvas, filtradas |
| `PATCH /transacoes/{id}` | sim | corrige a categoria (`{"categoria": "mercado"}` ou `null`) |
| `GET /painel?mes=AAAA-MM` | sim | cartões do mês e gráfico de 6 meses |
| `GET /conversas` | sim | conversas do assistente |
| `GET /conversas/{id}/mensagens` | sim | mensagens de uma conversa |
| `PATCH /conversas/{id}` | sim | renomeia |
| `DELETE /conversas/{id}` | sim | apaga |
| `POST /chat` | sim | pergunta ao assistente (`{"mensagem", "conversa_id"}`) |
| `PATCH /perfil` | sim | muda o nome |
| `DELETE /conta` | sim | apaga a conta e tudo dela |

Erros sempre como `{"detail": "mensagem em português"}`.
