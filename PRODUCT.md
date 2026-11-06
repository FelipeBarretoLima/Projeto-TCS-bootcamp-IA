# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- A equipe do projeto, que envia os próprios extratos bancários para ver as transações
  extraídas, anonimizadas e categorizadas (uso real).
- Avaliadores do bootcamp, na demonstração final do projeto.

Uso em notebook/desktop.

## Product Purpose

O TAS (Transactions Assistancy Service) lê extratos bancários reais em PDF ou CSV (conta corrente
e cartão de crédito), gera transações padronizadas e anônimas e classifica cada uma numa categoria
de gasto. A página deixa enviar um extrato e ver o resultado: o resumo do arquivo e a tabela de
transações com a categoria. Funciona bem quando o extrato é aceito, as transações aparecem
anonimizadas e a categoria explica de onde veio.

## Positioning

A extração é determinística, com um parser por formato de banco que confere os totais do
documento. A privacidade é tratada como requisito: anonimização, validação contra vazamento antes
de qualquer saída e nada gravado no servidor.

## Operating Context

- Fluxo: escolher o arquivo → enviar → ler o resumo (formato, período, contagens, conferência) →
  ler a tabela (data, histórico, contraparte, meio, categoria, valor).
- Bancos/formatos suportados: Bradesco (conta e cartão), Inter (conta), Nubank (conta em PDF e
  CSV, fatura), Santander (cartão), Sicoob (conta).
- Categorias: mercado, alimentação fora, transporte, compras, contas e serviços, transferência
  para pessoa, receitas, financeiro.

## Capabilities and Constraints

- Hoje a categoria vem de regras fixas e do mapa de estabelecimentos. O classificador treinado
  ainda vai entrar, para as transações sem categoria.
- Em espera até os classificadores ficarem prontos: resumo por categoria, filtros, exportar CSV
  e vários extratos de uma vez.
- Um arquivo por envio, até 10 MB, `.pdf` ou `.csv`. Nada é guardado entre visitas.
- A interface é em português do Brasil.

## Brand Commitments

- Nome do produto: **TAS — Transactions Assistancy Service** (grafia do logotipo nos mockups do usuário). Só o TAS aparece na interface;
  a TCS não é citada por nome.
- Cores: paleta da TCS (decisão do usuário em 2026-11-06).

## Evidence on Hand

Não há dados de demonstração nem capturas reais. Extratos reais nunca entram no repositório, e as
fixtures de teste são inventadas. Não inventar números, clientes ou depoimentos.

## Product Principles

- Privacidade primeiro: nunca mostrar dado pessoal além do que o pipeline já anonimizou.
- Transparência: dizer por que um arquivo foi rejeitado e de onde veio cada categoria.
- Sem surpresa: o que aparece na tela é exatamente o que o pipeline produziu.
