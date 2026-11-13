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

### Testar no celular

```bash
npm run dev:celular   # https://<IP-do-computador>:5173 (aparece na linha "Network")
```

- O celular precisa estar na **mesma rede** do computador. Redes institucionais/de convidados
  costumam bloquear um aparelho de acessar outro (isolamento de clientes): nesse caso, conecte o
  computador ao hotspot do próprio celular.
- É HTTPS com certificado de teste: o navegador avisa que o site "não é seguro" na primeira vez;
  toque em **Avançado > Continuar**. Sem HTTPS, o navegador bloqueia o microfone da mensagem de voz.
- A API continua só no computador (`localhost:8000`): o Vite faz a ponte, como no `npm run dev`.
- No PowerShell, `npm run dev -- --host` **não** funciona (o `--` some no caminho); use o
  `dev:celular`.

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
