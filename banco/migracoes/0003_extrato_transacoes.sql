-- 0003: quais extratos trouxeram cada transação.
--
-- Uma transação que aparece em dois extratos sobrepostos é gravada uma vez só
-- (banco/deduplicacao.py), mas pertence aos dois. Sem este vínculo, excluir o primeiro extrato
-- apagava em cascata também as transações que o segundo trazia. Com ele, ao excluir um extrato, as
-- transações que outro extrato também trouxe passam para esse outro (banco/repositorio.py).

create table public.extrato_transacoes (
    extrato_id   uuid   not null references public.extratos (id) on delete cascade,
    transacao_id bigint not null references public.transacoes (id) on delete cascade,
    primary key (extrato_id, transacao_id)
);

create index extrato_transacoes_por_transacao on public.extrato_transacoes (transacao_id);

-- transações já gravadas: vinculadas ao extrato que as gravou
-- (as repetidas de importações anteriores a esta migração não têm como ser recuperadas)
insert into public.extrato_transacoes (extrato_id, transacao_id)
select extrato_id, id from public.transacoes;

alter table public.extrato_transacoes enable row level security;

create policy "le os vinculos dos proprios extratos" on public.extrato_transacoes
    for select to authenticated using (exists (
        select 1 from public.extratos e where e.id = extrato_id and e.usuario_id = (select auth.uid())));
