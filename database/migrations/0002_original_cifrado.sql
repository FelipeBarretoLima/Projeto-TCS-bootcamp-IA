-- 0002: texto original da transação (sem anonimizar), CIFRADO pela API.
--
-- A API cifra {"historico", "contraparte"} originais com a chave CHAVE_ORIGINAIS do .env (Fernet)
-- antes de gravar; a chave nunca vem para o banco. Serve só para mostrar ao dono a transação como
-- veio do banco dele. ML, chat e treino usam as colunas anonimizadas (historico, contraparte).
-- Null = gravada sem chave configurada (ou antes desta migração): a tela mostra o anonimizado.
-- Apagar o extrato ou o usuário apaga este texto junto (cascata das chaves estrangeiras).

alter table public.transacoes add column original_cifrado text;

comment on column public.transacoes.original_cifrado is
    'Historico e contraparte originais (sem anonimizar), cifrados pela API (Fernet). Só o dono vê, decifrado.';
