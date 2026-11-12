-- 0005: correções de categoria numa tabela própria (decisão do usuário em 2026-11-12).
--
-- Antes, a correção vivia só na transação: excluir o extrato apagava a correção junto, e o
-- próximo retreino "esquecia" o que ela ensinava (as lojas voltavam ao rótulo antigo do CSV base).
-- Agora cada correção é guardada aqui, só com os campos anonimizados do contrato do parser
-- (nunca original_cifrado). Ela sobrevive à exclusão do extrato (transacao_id vira null) e só é
-- apagada com a conta (cascata, LGPD) ou quando o usuário volta a transação para "sem categoria".
-- O retreino (api/services/retraining.py) lê as correções desta tabela.

create table public.correcoes (
    id           bigint generated always as identity primary key,
    usuario_id   uuid not null references public.usuarios (id) on delete cascade,
    -- a transação corrigida; null = o extrato dela foi excluído (a correção continua valendo)
    transacao_id bigint references public.transacoes (id) on delete set null,
    data         date not null,
    historico    text not null,
    contraparte  text not null default '',
    valor        numeric(12, 2) not null,
    tipo         text not null,
    meio         text not null,
    banco        text not null,
    categoria    text not null,
    corrigida_em timestamptz not null default now(),
    unique (transacao_id)  -- uma correção por transação (corrigir de novo atualiza a mesma linha)
);

-- os valores permitidos são os mesmos de public.transacoes (de onde a correção é copiada)
alter table public.correcoes
    add constraint correcoes_tipo_valido check (tipo in ('entrada', 'saida')),
    add constraint correcoes_categoria_valida check (categoria in (
        'mercado', 'alimentacao_fora', 'transporte', 'compras', 'contas_servicos',
        'transferencia_pessoa', 'receitas', 'financeiro'));

create index correcoes_por_data on public.correcoes (corrigida_em);
create index correcoes_por_usuario on public.correcoes (usuario_id);

-- correções já feitas antes desta migração
insert into public.correcoes (usuario_id, transacao_id, data, historico, contraparte, valor, tipo, meio,
                              banco, categoria, corrigida_em)
select usuario_id, id, data, historico, contraparte, valor, tipo, meio, banco, categoria,
       coalesce(corrigida_em, now())
from public.transacoes
where origem_categoria = 'usuario' and categoria is not null;

alter table public.correcoes enable row level security;

create policy "le as proprias correcoes" on public.correcoes
    for select to authenticated using ((select auth.uid()) = usuario_id);
