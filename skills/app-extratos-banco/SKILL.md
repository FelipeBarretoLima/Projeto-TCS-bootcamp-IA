---
name: app-extratos-banco
description: Como construir a camada de banco de dados de uma aplicação de extratos bancários no Supabase (PostgreSQL + Auth). Cobre as tabelas (usuarios, extratos, transacoes, extrato_transacoes, conversas, mensagens, treinos_modelo), CHECKs iguais aos enums do código, RLS, exclusão em cascata (LGPD), migrações numeradas com um executor próprio, pool psycopg 3 compatível com o pooler do Supabase, um repositório que sempre filtra pelo usuário, e a deduplicação de transações entre extratos com períodos sobrepostos. Use sempre que for criar ou mudar tabelas, migrações, consultas SQL, o repositório, a conexão com o Supabase, ou tratar transações repetidas entre extratos.
---

# Camada de banco (`database/`)

PostgreSQL no Supabase. Login e senha ficam no **Supabase Auth** (`auth.users`); as tabelas da
aplicação guardam perfil, extratos, transações, conversas e o histórico de retreinos.

```
database/
  migrations/0001_....sql   uma migração por arquivo, numeradas, nunca editadas depois de aplicadas
  migrate.py                python -m database.migrate [--status]
  connection.py             pool de conexões (aberto na primeira vez)
  repository.py             classe Banco: toda leitura e gravação, sempre filtrando pelo usuário
  deduplication.py          regra de transação repetida entre extratos (sem banco, testável)
  tests/
```

## Decisões (e por quê)

- **A API conecta como dona do banco e sempre filtra por `usuario_id`.** É a proteção principal.
  O **RLS fica ligado** em todas as tabelas, com políticas só de leitura para `authenticated`,
  como segunda camada: se alguém um dia liberar uma tabela na Data API do Supabase, cada usuário
  só enxerga as próprias linhas. `treinos_modelo` não tem política: só a API acessa.
- **Perfil criado por gatilho** no cadastro (`auth.users` → `public.usuarios`, nome vindo de
  `raw_user_meta_data ->> 'nome'`). O repositório tem um `garante_usuario` para contas criadas
  antes das tabelas.
- **Exclusão em cascata**: apagar o usuário em `auth.users` apaga perfil, extratos, transações,
  vínculos e conversas (direito de exclusão da LGPD).
- **Dinheiro em `numeric(12, 2)`**, nunca `float`.
- **`CHECK` com os valores dos enums** (`tipo`, `meio`, `categoria`, `origem_categoria`). Um teste
  compara esses valores com os enums do Python, então banco e código não divergem.
- **Chave estrangeira composta** `(extrato_id, usuario_id) → extratos (id, usuario_id)`: uma
  transação nunca pertence a um extrato de outra pessoa.
- **`hash_arquivo` único por usuário** (sha256 do conteúdo): o mesmo arquivo não entra duas vezes
  (a API devolve 409). Excluir o extrato libera importar de novo.
- **O arquivo nunca é guardado**, só as transações extraídas e anonimizadas. O texto original
  fica em `original_cifrado`, cifrado pela API com uma chave que nunca vem para o banco.
- **`categoria` e `origem_categoria` andam juntas** (as duas preenchidas ou as duas nulas).
- **Mensagem do chat** tem texto ou gráfico (`jsonb`). Um gatilho atualiza
  `conversas.atualizada_em`, para a conversa mais recente aparecer primeiro.

Esquema completo, pronto para um projeto novo:
[references/0001_esquema_inicial.sql](references/0001_esquema_inicial.sql).

## Tabelas

| Tabela | Conteúdo |
|---|---|
| `usuarios` | `id` (= `auth.users.id`), `nome`, `email`, `criado_em` |
| `extratos` | um por arquivo importado: `nome_arquivo`, `banco`, `parser`, período, `linhas_gravadas`, `hash_arquivo`, `enviado_em` |
| `transacoes` | colunas do contrato do parser (menos `id_usuario`) + `categoria`, `origem_categoria`, `original_cifrado`, `corrigida_em` |
| `extrato_transacoes` | quais extratos trouxeram cada transação (uma transação pode vir de dois extratos sobrepostos) |
| `conversas` | conversas do assistente: `titulo`, `criada_em`, `atualizada_em` |
| `mensagens` | `papel` (`usuario` \| `agente`), `texto`, `grafico` (jsonb) |
| `treinos_modelo` | um registro por retreino: status, contagens e acertos antes/depois |
| `correcoes` | correções de categoria do usuário (campos anonimizados), que sobrevivem à exclusão do extrato |

Índices pensados para as consultas: `(usuario_id, data)`, `(usuario_id, categoria, data)`,
`(extrato_id)`, `(usuario_id, enviado_em desc)`, `(conversa_id, criada_em, id)` e um índice
parcial nas correções (`where origem_categoria = 'usuario'`).

## Conexão com o Supabase

- `DATABASE_URL` = **Session pooler** (Supabase > Connect > Session pooler > URI), com a senha no
  lugar de `[YOUR-PASSWORD]`.
- psycopg 3 com `psycopg_pool.ConnectionPool(min_size=1, max_size=5, timeout=15,
  kwargs={"prepare_threshold": None, "connect_timeout": 10})`. `prepare_threshold=None` desliga
  os prepared statements, que o pooler pode não aceitar.
- `with conexao(url) as con:` faz commit se o bloco termina sem erro e rollback se der erro.
  Na API, cada requisição é uma transação: deu erro, nada fica pela metade.
- O pool é aberto na primeira vez que a API precisa dele e fechado no desligamento.

## Migrações

- Arquivos `NNNN_nome.sql` em `database/migrations/`, aplicados em ordem de nome.
- `public.migracoes_aplicadas (nome, aplicada_em)` registra o que já rodou: rodar de novo não
  repete nada. O nome do arquivo é a chave, então **renomear uma migração faz ela rodar de novo**.
- Cada arquivo roda inteiro numa transação: se der erro no meio, nada dele fica.
- **Nunca edite uma migração aplicada**: crie a próxima. Migração que muda dados já existentes
  inclui o `insert ... select` de preenchimento.
- `python -m database.migrate --status` lista aplicadas e pendentes sem mudar nada.

## Repositório (`Banco`)

Uma classe que envolve uma conexão aberta. Quem abre a conexão decide o commit. Regras:

- **Toda função recebe `usuario_id` e filtra por ele.** A exceção são as funções do retreino, que
  leem as correções de todos (só campos anonimizados, nunca `original_cifrado`).
- Mudanças que devem valer para outra conexão antes do fim da requisição usam `confirma()`
  (commit). Exemplo: a correção de categoria precisa estar gravada antes de o retreino, em outra
  thread e outra conexão, ler as correções.
- "Não é do usuário" e "não existe" respondem igual (`False`/`None` → a API devolve 404), para não
  revelar se o id existe.
- Exceções de domínio: `ExtratoRepetido` (mesmo hash, inclusive na corrida de dois envios
  simultâneos, via `UniqueViolation`) e `ConversaApagada` (a conversa sumiu enquanto o assistente
  respondia, via `ForeignKeyViolation`).
- Linhas como `dict` (`row_factory=dict_row`); gráfico gravado como JSON (`Decimal` → `float`,
  datas → ISO).

Métodos e SQL principais em [references/acesso-ao-banco.md](references/acesso-ao-banco.md).

## Deduplicação entre extratos sobrepostos

Regra combinada com o grupo. Dentro do mesmo usuário e do mesmo banco, uma transação é
identificada por `(banco, data, valor, tipo, meio, historico, contraparte)`, e a comparação é por
**contagem**:

- a mesma compra em dois extratos que se sobrepõem entra uma vez;
- duas compras iguais de verdade no mesmo extrato (duas corridas de R$ 8,94 no mesmo dia) entram
  as duas: se o banco já tem 2 iguais e o extrato novo traz 3, entra só 1;
- a mesma compra em bancos diferentes entra nas duas contas;
- nada já gravado é apagado ou alterado.

Na gravação: busca as existentes do usuário nos bancos e no intervalo de datas do extrato novo,
separa as novas das repetidas (`separa_novas_com_ids`), grava só as novas e vincula ao extrato
novo tanto as novas quanto as repetidas (`extrato_transacoes`).

Na exclusão de um extrato, as transações que outro extrato também trouxe **passam para esse
outro** (o mais antigo), que tem `linhas_gravadas` recalculado. As outras saem em cascata.

**Correções de categoria** ficam em `correcoes` (campos anonimizados + categoria +
`corrigida_em`), uma por transação (`unique (transacao_id)`, corrigir de novo atualiza a linha):
- excluir o extrato não apaga a correção: `transacao_id` vira `null` (`on delete set null`);
- reimportar a mesma transação e corrigir de novo troca a correção órfã pela nova (comparação
  pelos campos do contrato), para não contar duas vezes no treino;
- voltar para "sem categoria" apaga a correção; excluir a conta apaga todas (cascata);
- o retreino conta e lê as correções desta tabela.

**Travas no Postgres** (`pg_advisory_xact_lock`, liberadas no commit): uma por usuário em
`grava_extrato`, para importações simultâneas não duplicarem transações, e uma fixa em
`inicia_treino_se_livre`, para dois processos não retreinarem ao mesmo tempo.

## Testes

- **Deduplicação** (sem banco): sobreposição entra uma vez; iguais de verdade pela contagem;
  bancos diferentes não se misturam; valor comparado em centavos; ids das repetidas.
- **Migrações** (sem banco): nomes `\d{4}_[a-z0-9_]+\.sql` numerados em sequência; `CHECK` de
  `categoria`, `meio`, `tipo` e `origem_categoria` iguais aos enums do Python e da API; nenhuma
  coluna de senha.
- **Banco real** só com `TESTE_BANCO=1`: conexão própria, um usuário criado em `auth.users` com
  e-mail `@teste.invalid` e **rollback no fim**, para nada ficar gravado. Cobre o fluxo completo:
  gravar, repetir o hash, deduplicar, excluir com herança, corrigir categoria e conversas.
- **API**: um `BancoFalso` em memória com a mesma interface do `Banco` (e a mesma
  deduplicação), trocado por `dependency_overrides`. Ao mudar um método do repositório, mude o
  falso junto.
