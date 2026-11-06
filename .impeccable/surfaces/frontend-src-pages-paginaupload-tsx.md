---
version: 1
slug: "frontend-src-pages-paginaupload-tsx"
primary_target: "frontend/src/pages/PaginaUpload.tsx"
related_targets: ["frontend/src/App.tsx"]
---

# Superfície: Importar extrato (frontend/src/pages/PaginaUpload.tsx)

Modo: Operate. Público: a equipe (uso real, notebook/desktop) e avaliadores do bootcamp (demonstração).
Tarefa: enviar um extrato PDF/CSV e ler o resultado (arquivo, resumo, tabela com categoria).
Estados: inicial, enviando, aceito (com/sem categoria, em revisão), rejeitado, erro de API, tema claro/escuro.
Restrições: nada de dado pessoal além do anonimizado; só o nome TAS aparece (sem citar a TCS); Dashboard e login dos mockups ficam fora até os classificadores ficarem prontos.

## Direction contract

THESIS: Uma ferramenta de trabalho limpa em que a marca TAS vive em um único fio: o degradê amarelo→laranja→vermelho→magenta→roxo. Recusa o painel genérico cinza com um acento solto.

OWN-WORLD: Fundo #F8FAFD, superfícies brancas, bordas #DCE2E8, tinta #0D1B2D, texto suave #586474, azul de ação #006EB8 em pílulas, selos de categoria #E6F0F8/#042F54, verde #0C9C5A e vermelho #E4243C só para entrada/saída. Manrope. Cantos 12–18px. Tema escuro derivado.

STORY: O visitante vê de cara onde soltar o extrato, entende em segundos se foi aceito e por quê, e lê cada transação com a categoria e de onde ela veio.

FIRST VIEWPORT: Faixa de 3px com o degradê no topo; cabeçalho branco com o logotipo tas em degradê e o nome em três linhas à esquerda, a pílula "Importar extrato" e o tema à direita. Título "Importar extrato" 38px/800 e subtítulo; zona tracejada de largura total com o círculo em degradê e o ícone de upload como ação principal.

FORM: Direção fixada pelos mockups do usuário em referencias/ (login, importação, tabela), código primeiro. Movimento assinatura: o degradê da marca (faixa, logotipo, círculo de upload que sobe no hover/arrasto).
seed: none (pinned: direction fixed by the user's own mockups in referencias/; new-work.md: "a user- or brief-pinned direction beats the roll, always", so no concept-seed roll ran)

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
