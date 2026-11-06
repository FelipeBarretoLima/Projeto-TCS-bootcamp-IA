# Frontend

Página web (React + TypeScript + Vite) para enviar um extrato e ver as transações extraídas.

## Rodar

Pré-requisito: **Node.js 22** (ou 20.19+). A API precisa estar rodando (ver o README da raiz).

```bash
cd frontend
npm install      # só na primeira vez
npm run dev      # http://localhost:5173
```

Em desenvolvimento, o Vite repassa tudo o que começa com `/api` para a API em `localhost:8000`
(`vite.config.ts`). Por isso o código sempre chama `/api/...`, sem endereço completo.

Outros comandos: `npm run build` (confere os tipos e gera `dist/`) e `npm run lint`.

## Estrutura

```
src/
  api/          cliente.ts: todas as chamadas à API · tipos.ts: formato das respostas
  components/   peças da tela (cabeçalho, formulário, resumo, tabela), cada uma com o seu .module.css
  pages/        uma tela por arquivo; junta os componentes e controla o estado
  utils/        formatação para exibição (datas, R$, códigos da API em português)
  App.tsx       estrutura da tela: cabeçalho + página
  index.css     cores e fonte globais (tema claro e escuro)
```

`api/tipos.ts` espelha `api/esquemas.py`: ao mudar a resposta da API, atualize os dois.
