-- 0001: tabelas do TAS (usuários, extratos, transações, conversas e mensagens do chatbot).
--
-- Login e senha ficam no Supabase Auth (auth.users): a senha é guardada criptografada por ele e
-- nunca passa por estas tabelas. `usuarios` guarda só o perfil e tem o mesmo id do auth.users.
--
-- Acesso: a API (FastAPI) conecta como dono do banco e SEMPRE filtra por usuario_id. O RLS fica
-- ligado em todas as tabelas como segunda camada: pela Data API do Supabase, cada usuário logado
-- só enxergaria as próprias linhas (e só se a tabela for liberada para ela, o que não fazemos).
--
-- Apagar o usuário no Supabase Auth apaga tudo dele em cascata (direito de exclusão da LGPD).

-- ---------------------------------------------------------------------------------------------
-- usuarios: perfil (sem senha)
-- ---------------------------------------------------------------------------------------------
create table public.usuarios (
    id         uuid primary key references auth.users (id) on delete cascade,
    nome       text not null default '',
    email      text not null default '',
    criado_em  timestamptz not null default now()
);

-- cria o perfil sozinho quando alguém se cadastra no Supabase Auth
-- (o nome vem dos metadados do cadastro: supabase.auth.signUp({..., options: {data: {nome}}}))
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
-- transacoes: mesmas colunas do CSV do parser + categoria (base das consultas do chatbot)
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
    -- a transação é do mesmo usuário dono do extrato
    foreign key (extrato_id, usuario_id) references public.extratos (id, usuario_id) on delete cascade,
    -- categoria e origem andam juntas: as duas preenchidas ou as duas vazias
    check ((categoria is null) = (origem_categoria is null))
);

-- "quanto gastei de X nos últimos N meses" e "gastos de tal mês"
create index transacoes_por_usuario_data on public.transacoes (usuario_id, data);
create index transacoes_por_usuario_categoria_data on public.transacoes (usuario_id, categoria, data);
create index transacoes_por_extrato on public.transacoes (extrato_id);

-- ---------------------------------------------------------------------------------------------
-- conversas e mensagens do chatbot (carregadas no login)
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
-- RLS: cada usuário logado só lê as próprias linhas
-- ---------------------------------------------------------------------------------------------
alter table public.usuarios   enable row level security;
alter table public.extratos   enable row level security;
alter table public.transacoes enable row level security;
alter table public.conversas  enable row level security;
alter table public.mensagens  enable row level security;

create policy "le o proprio perfil" on public.usuarios
    for select to authenticated using ((select auth.uid()) = id);
create policy "le os proprios extratos" on public.extratos
    for select to authenticated using ((select auth.uid()) = usuario_id);
create policy "le as proprias transacoes" on public.transacoes
    for select to authenticated using ((select auth.uid()) = usuario_id);
create policy "le as proprias conversas" on public.conversas
    for select to authenticated using ((select auth.uid()) = usuario_id);
create policy "le as mensagens das proprias conversas" on public.mensagens
    for select to authenticated using (exists (
        select 1 from public.conversas c where c.id = conversa_id and c.usuario_id = (select auth.uid())));
