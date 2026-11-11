-- 0004: retreino do classificador com as correções de categoria feitas pelos usuários.
--
-- Cada correção (origem_categoria = 'usuario') vira exemplo de treino, só com os campos
-- anonimizados (nunca original_cifrado). A cada 15 correções novas desde o último treino, a API
-- retreina o modelo (api/servicos/retreino.py) e registra o resultado em treinos_modelo.

-- quando o usuário corrigiu (null = não corrigida, ou corrigida para "sem categoria")
alter table public.transacoes add column corrigida_em timestamptz;

create index transacoes_corrigidas on public.transacoes (corrigida_em) where origem_categoria = 'usuario';

-- histórico de retreinos (só a API lê e grava; sem dado de usuário, só contagens e acertos)
create table public.treinos_modelo (
    id                       bigint generated always as identity primary key,
    iniciado_em              timestamptz not null default now(),
    concluido_em             timestamptz,
    status                   text not null default 'rodando'
                             check (status in ('rodando', 'ok', 'erro')),
    correcoes                integer not null default 0 check (correcoes >= 0),
    linhas_treino            integer not null default 0 check (linhas_treino >= 0),
    -- das correções, quantas o modelo acertava antes e quantas acerta depois do retreino
    acerto_correcoes_antes   numeric(5, 2),
    acerto_correcoes_depois  numeric(5, 2),
    -- acerto do modelo novo no CSV base (sanidade: não pode desabar)
    acerto_base_depois       numeric(5, 2),
    mensagem                 text not null default ''   -- motivo do erro (sem conteúdo de transação)
);

alter table public.treinos_modelo enable row level security;  -- sem policy: só a API (dona do banco)
