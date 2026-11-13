-- 0001: esquema inicial da aplicação de extratos (PostgreSQL no Supabase).
--
-- Junta as 4 migrações do projeto de referência (tabelas, original cifrado, vínculo
-- extrato-transação e retreino) numa só, para um banco novo. Num banco que já tem dados, nunca
-- edite uma migração aplicada: crie a próxima (0002_..., 0003_...).
--
-- Login e senha ficam no Supabase Auth (auth.users): a senha nunca passa por estas tabelas.
-- A API conecta como dona do banco e SEMPRE filtra por usuario_id. O RLS fica ligado em todas
-- as tabelas como segunda camada: pela Data API do Supabase, cada usuário logado só enxergaria
-- as próprias linhas (e só se a tabela fosse liberada para ela, o que não fazemos).
-- Apagar o usuário no Supabase Auth apaga tudo dele em cascata (direito de exclusão da LGPD).

-- ---------------------------------------------------------------------------------------------
-- usuarios: perfil (sem senha), com o mesmo id do auth.users
-- ---------------------------------------------------------------------------------------------
create table public.usuarios (
    id         uuid primary key references auth.users (id) on delete cascade,
    nome       text not null default '',
    email      text not null default '',
    criado_em  timestamptz not null default now()
);

-- cria o perfil sozinho no cadastro (o nome vem de supabase.auth.signUp({..., options: {data: {nome}}}))
create function public.cria_perfil_do_usuario()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
    insert into public.usuarios (id, nome, email)
    values (new.id, coalesce(new.raw_user_meta_data ->> 'nome', ''), coalesce(new.email, ''));
    return new;
end;
$$;

create trigger ao_cadastrar_usuario
    after insert on auth.users
    for each row execute function public.cria_perfil_do_usuario();

-- ---------------------------------------------------------------------------------------------
-- extratos: cada arquivo enviado (o arquivo em si NÃO é guardado, só as transações extraídas)
-- ---------------------------------------------------------------------------------------------
create table public.extratos (
    id              uuid primary key default gen_random_uuid(),
    usuario_id      uuid not null references public.usuarios (id) on delete cascade,
    nome_arquivo    text not null default '',      -- só o dono vê
    banco           text not null,
    parser          text not null default '',
    periodo_inicio  date,
    periodo_fim     date,
    linhas_gravadas integer not null default 0 check (linhas_gravadas >= 0),
    hash_arquivo    text not null,                 -- sha256 do arquivo: recusa o mesmo arquivo duas vezes
    enviado_em      timestamptz not null default now(),
    unique (usuario_id, hash_arquivo),
    unique (id, usuario_id),                       -- alvo da chave composta de transacoes
    check (periodo_inicio is null or periodo_fim is null or periodo_inicio <= periodo_fim)
);

create index extratos_por_usuario on public.extratos (usuario_id, enviado_em desc);

-- ---------------------------------------------------------------------------------------------
-- transacoes: as colunas do CSV do parser + categoria (base do dashboard e do assistente)
-- ---------------------------------------------------------------------------------------------
create table public.transacoes (
    id               bigint generated always as identity primary key,
    usuario_id       uuid not null,
    extrato_id       uuid not null,
    data             date not null,
    historico        text not null,
    contraparte      text not null default '',
    valor            numeric(12, 2) not null,     -- numeric, nunca float: dinheiro exato
    tipo             text not null check (tipo in ('entrada', 'saida')),
    meio             text not null check (meio in (
                         'pix', 'ted_doc', 'boleto', 'cartao_debito', 'cartao_credito',
                         'pagamento_fatura', 'tarifa', 'juros_iof', 'investimento', 'rendimento',
                         'salario', 'saque', 'estorno', 'transferencia_interna', 'outros')),
    banco            text not null,
    categoria        text check (categoria in (
                         'mercado', 'alimentacao_fora', 'transporte', 'compras', 'contas_servicos',
                         'transferencia_pessoa', 'receitas', 'financeiro')),
    origem_categoria text check (origem_categoria in ('regra', 'mapa', 'modelo', 'usuario')),
    -- historico e contraparte originais (sem anonimizar), cifrados pela API (Fernet) com a chave
    -- do .env, que nunca vem para o banco. Null = gravada sem chave configurada.
    original_cifrado text,
    -- quando o usuário corrigiu a categoria (null = não corrigida)
    corrigida_em     timestamptz,
    -- a transação é do mesmo usuário dono do extrato
    foreign key (extrato_id, usuario_id) references public.extratos (id, usuario_id) on delete cascade,
    -- categoria e origem andam juntas: as duas preenchidas ou as duas vazias
    check ((categoria is null) = (origem_categoria is null))
);

comment on column public.transacoes.original_cifrado is
    'Historico e contraparte originais (sem anonimizar), cifrados pela API (Fernet). Só o dono vê, decifrado.';

-- "quanto gastei de X nos últimos N meses" e "gastos de tal mês"
create index transacoes_por_usuario_data on public.transacoes (usuario_id, data);
create index transacoes_por_usuario_categoria_data on public.transacoes (usuario_id, categoria, data);
create index transacoes_por_extrato on public.transacoes (extrato_id);
create index transacoes_corrigidas on public.transacoes (corrigida_em) where origem_categoria = 'usuario';

-- ---------------------------------------------------------------------------------------------
-- extrato_transacoes: quais extratos trouxeram cada transação
-- Uma transação de dois extratos sobrepostos é gravada uma vez só, mas pertence aos dois: ao
-- excluir um, as transações que o outro também trouxe passam para ele em vez de sumir.
-- ---------------------------------------------------------------------------------------------
create table public.extrato_transacoes (
    extrato_id   uuid   not null references public.extratos (id) on delete cascade,
    transacao_id bigint not null references public.transacoes (id) on delete cascade,
    primary key (extrato_id, transacao_id)
);

create index extrato_transacoes_por_transacao on public.extrato_transacoes (transacao_id);

-- ---------------------------------------------------------------------------------------------
-- conversas e mensagens do assistente
-- ---------------------------------------------------------------------------------------------
create table public.conversas (
    id            uuid primary key default gen_random_uuid(),
    usuario_id    uuid not null references public.usuarios (id) on delete cascade,
    titulo        text not null default 'Nova conversa',
    criada_em     timestamptz not null default now(),
    atualizada_em timestamptz not null default now()
);

create index conversas_por_usuario on public.conversas (usuario_id, atualizada_em desc);

create table public.mensagens (
    id          bigint generated always as identity primary key,
    conversa_id uuid not null references public.conversas (id) on delete cascade,
    papel       text not null check (papel in ('usuario', 'agente')),
    texto       text not null default '',
    grafico     jsonb,                            -- dados do gráfico (o frontend desenha); null = só texto
    criada_em   timestamptz not null default now(),
    check (texto <> '' or grafico is not null)
);

create index mensagens_por_conversa on public.mensagens (conversa_id, criada_em, id);

-- nova mensagem sobe a conversa para o topo da lista
create function public.atualiza_conversa()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    update public.conversas set atualizada_em = new.criada_em where id = new.conversa_id;
    return new;
end;
$$;

create trigger ao_inserir_mensagem
    after insert on public.mensagens
    for each row execute function public.atualiza_conversa();

-- ---------------------------------------------------------------------------------------------
-- treinos_modelo: histórico de retreinos do classificador (só contagens e acertos)
-- ---------------------------------------------------------------------------------------------
create table public.treinos_modelo (
    id                       bigint generated always as identity primary key,
    iniciado_em              timestamptz not null default now(),
    concluido_em             timestamptz,
    status                   text not null default 'rodando'
                             check (status in ('rodando', 'ok', 'erro')),
    correcoes                integer not null default 0 check (correcoes >= 0),
    linhas_treino            integer not null default 0 check (linhas_treino >= 0),
    acerto_correcoes_antes   numeric(5, 2),   -- % das correções que o modelo acertava antes
    acerto_correcoes_depois  numeric(5, 2),   -- % das correções que acerta depois
    acerto_base_depois       numeric(5, 2),   -- % do CSV base (sanidade: não pode desabar)
    mensagem                 text not null default ''   -- motivo do erro (sem conteúdo de transação)
);

-- ---------------------------------------------------------------------------------------------
-- correcoes: correções de categoria do usuário, só com os campos anonimizados.
-- Sobrevivem à exclusão do extrato (transacao_id vira null) e só somem com a conta (LGPD) ou
-- quando o usuário volta a transação para "sem categoria". O retreino lê daqui.
-- ---------------------------------------------------------------------------------------------
create table public.correcoes (
    id           bigint generated always as identity primary key,
    usuario_id   uuid not null references public.usuarios (id) on delete cascade,
    transacao_id bigint references public.transacoes (id) on delete set null,
    data         date not null,
    historico    text not null,
    contraparte  text not null default '',
    valor        numeric(12, 2) not null,
    tipo         text not null check (tipo in ('entrada', 'saida')),
    meio         text not null,
    banco        text not null,
    categoria    text not null check (categoria in (
                     'mercado', 'alimentacao_fora', 'transporte', 'compras', 'contas_servicos',
                     'transferencia_pessoa', 'receitas', 'financeiro')),
    corrigida_em timestamptz not null default now(),
    unique (transacao_id)  -- uma correção por transação
);

create index correcoes_por_data on public.correcoes (corrigida_em);
create index correcoes_por_usuario on public.correcoes (usuario_id);

-- ---------------------------------------------------------------------------------------------
-- RLS: cada usuário logado só lê as próprias linhas (treinos_modelo sem policy: só a API)
-- ---------------------------------------------------------------------------------------------
alter table public.usuarios           enable row level security;
alter table public.extratos           enable row level security;
alter table public.transacoes         enable row level security;
alter table public.extrato_transacoes enable row level security;
alter table public.conversas          enable row level security;
alter table public.mensagens          enable row level security;
alter table public.treinos_modelo     enable row level security;
alter table public.correcoes          enable row level security;

create policy "le as proprias correcoes" on public.correcoes
    for select to authenticated using ((select auth.uid()) = usuario_id);

create policy "le o proprio perfil" on public.usuarios
    for select to authenticated using ((select auth.uid()) = id);
create policy "le os proprios extratos" on public.extratos
    for select to authenticated using ((select auth.uid()) = usuario_id);
create policy "le as proprias transacoes" on public.transacoes
    for select to authenticated using ((select auth.uid()) = usuario_id);
create policy "le os vinculos dos proprios extratos" on public.extrato_transacoes
    for select to authenticated using (exists (
        select 1 from public.extratos e where e.id = extrato_id and e.usuario_id = (select auth.uid())));
create policy "le as proprias conversas" on public.conversas
    for select to authenticated using ((select auth.uid()) = usuario_id);
create policy "le as mensagens das proprias conversas" on public.mensagens
    for select to authenticated using (exists (
        select 1 from public.conversas c where c.id = conversa_id and c.usuario_id = (select auth.uid())));
