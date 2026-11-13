# Skills para recriar a aplicação

Skills para o Claude (Claude Code) que descrevem, camada por camada, como construir uma aplicação
como esta: importar extratos bancários em PDF/CSV, extrair as transações com um parser por
formato, anonimizar, categorizar com ML, guardar no Supabase e responder perguntas sobre os gastos
com um assistente LLM.

Cada skill é uma pasta com um `SKILL.md`, que é o prompt carregado quando a skill é usada, e uma
pasta `references/` com código e detalhes que o Claude lê quando precisa.

| Skill | Camada | Quando é usada |
|---|---|---|
| [app-extratos](app-extratos/SKILL.md) | visão geral | começar o projeto: arquitetura, contratos entre camadas, ordem de construção, perguntas ao usuário |
| [app-extratos-extracao](app-extratos-extracao/SKILL.md) | `extraction/` | parsers de extrato, conferência dos totais, anonimização, validação |
| [app-extratos-ml](app-extratos-ml/SKILL.md) | `ml/` | rotulagem, escolha e treino do modelo, retreino com as correções |
| [app-extratos-banco](app-extratos-banco/SKILL.md) | `database/` | tabelas no Supabase, migrações, repositório, deduplicação |
| [app-extratos-api](app-extratos-api/SKILL.md) | `api/` | rotas FastAPI, login, importação, limites, cifra, testes |
| [app-extratos-agente](app-extratos-agente/SKILL.md) | `agent/` | consultas fixas, ferramentas, prompt e modelos do assistente |
| [app-extratos-frontend](app-extratos-frontend/SKILL.md) | `frontend/` | páginas React, login no navegador, gráficos, design system |

## Como instalar

Copie as 7 pastas (não este README) para a pasta de skills do Claude Code:

- só no projeto novo: `<projeto-novo>/.claude/skills/`;
- em todos os projetos da pessoa: `~/.claude/skills/` (no Windows, `C:\Users\<nome>\.claude\skills\`).

```bash
mkdir -p <projeto-novo>/.claude/skills
cp -r skills/app-extratos* <projeto-novo>/.claude/skills/
```

Abra uma sessão nova do Claude Code no projeto: as skills aparecem na lista e são usadas sozinhas
quando o pedido combina com a descrição de cada uma. Também dá para chamar pelo nome
(`/app-extratos`).

## Como usar

Comece pela visão geral. Ela define a ordem e indica a skill de cada fase:

> Quero criar uma aplicação que lê meus extratos bancários (Nubank e Itaú), categoriza os gastos
> e tem um chat para perguntar sobre eles. Use a skill app-extratos para planejar.

Depois, uma camada por vez:

> Vamos fazer a camada de extração. Tenho um extrato do Itaú em PDF em data/raw/1/.

> Agora o banco no Supabase: já coloquei o DATABASE_URL no .env.

O Claude mostra o plano de cada camada antes de escrever e só passa para a próxima quando os
testes daquela passam.

## O que a pessoa precisa ter

- Python 3.12 e Node.js 22.
- Extratos reais dela (e de outras pessoas, para treinar o modelo), **só na máquina**, em `data/`,
  que fica fora do git.
- Um projeto no Supabase (Postgres + Auth) e uma chave de LLM (Gemini pelo AI Studio, na
  referência).

As skills não contêm dados reais nem segredos: os exemplos usam nomes e valores inventados.

## Manutenção

Estas skills descrevem o projeto como estava em 2026-11-12 (depois da tradução das pastas para
inglês). Se uma decisão ou um contrato mudar no código, atualize a skill da camada e, se for
contrato, também `app-extratos/references/contratos.md`.

A skill `.claude/skills/traducao-ingles/` é outra coisa: ela serve para trabalhar **neste**
repositório e não faz parte deste conjunto.
