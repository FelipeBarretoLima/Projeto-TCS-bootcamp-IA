---
name: app-extratos-extracao
description: Como construir a camada de extração de uma aplicação de extratos bancários. Um parser determinístico por formato (banco + conta/cartão + PDF/CSV) lê o arquivo, confere a soma contra os totais declarados no documento, anonimiza (CPF, CNPJ, cartão, conta, nomes do titular, pessoa física) e valida antes de gravar um CSV padronizado. Use sempre que for criar ou mudar um parser de extrato ou fatura (Nubank, Itaú, Bradesco, Inter, Santander, Sicoob...), ler PDF de banco com pdfplumber, anonimizar transações, ou investigar um extrato rejeitado (FormatoNaoReconhecido, LayoutInesperado, HistoricoDesconhecido, ReconciliacaoFalhou).
---

# Camada de extração (`extraction/`, pacote `statement`)

Entrada: um arquivo de extrato (PDF ou CSV). Saída: linhas no contrato
`id_usuario,data,historico,contraparte,valor,tipo,meio,banco` (detalhes na skill `app-extratos`,
`references/contratos.md`), um relatório por arquivo e, à parte, o texto original de cada linha
(só em memória, para a API cifrar).

## Por que ela é assim

- **Determinística.** Um parser por formato, com regex ancoradas para cada tipo de linha. Qualquer
  linha desconhecida rejeita o arquivo com um código. Um palpite errado poderia jogar um dado
  pessoal ou um valor errado na saída; rejeitar é seguro e explicável.
- **Conferida.** Todo extrato declara saldos ou totais. Se a soma dos lançamentos lidos não bater,
  faltou ou sobrou alguma linha: o arquivo é rejeitado.
- **Anônima antes de qualquer saída.** Padrões de dado pessoal são apagados, a contraparte passa
  por uma regra de pessoa física/empresa e, no fim, um validador varre tudo de novo. Se achar algo,
  nada é gravado. O que não dá para decidir com segurança vai para uma revisão privada, fora da
  saída.
- **Sem conteúdo em erros.** As exceções carregam só um código estável e a página. Um
  `except Exception` registra só o tipo da exceção, porque a mensagem pode trazer texto do extrato.

## Estrutura

```
extraction/src/statement/
  models.py           contrato da linha: OutputRow (pydantic estrito), TransactionType, PaymentMethod, COLUMNS
  normalization.py    normalize_text, normalize_history, br_amount, strip_accents
  patterns.py         regex de dado pessoal; variantes do nome do titular
  anonymization.py    regra da contraparte (pessoa física / empresa / ambíguo)
  merchants.py        nome-base do estabelecimento; pessoa na maquininha -> PESSOA_FISICA
  cities.py           separa a cidade do fim do nome do estabelecimento (lista do IBGE)
  reconciliation.py   soma x totais declarados
  validation.py       varredura final e gravação atômica do CSV
  pipeline.py         junta as etapas; relatório por arquivo
  cli.py, __main__.py python -m statement extrair | tudo
  parsers/
    base.py           interface Parser, RawTransaction, Segment, ExtractionResult, exceções
    registry.py       lista dos parsers e escolha do único que reconhece o arquivo
    <banco>_<produto>_<ext>.py   um arquivo por formato
  dados/              listas públicas: municipios.txt (IBGE), primeiros_nomes.txt
extraction/tests/     só dados inventados
```

No `pyproject.toml`: `packages.find.where = ["extraction/src"]` e `package-data` com
`dados/*.txt`. As listas são lidas com `importlib.resources.files("statement")`.

## O pipeline, etapa por etapa

1. **Detectar.** `choose_parser(path)` chama `detect()` de cada parser (rápido, nunca levanta
   exceção). Exatamente um precisa reconhecer: nenhum → `FormatoNaoReconhecido`; dois ou mais →
   `FormatoAmbiguo`.
2. **Extrair.** `parser.extract(path)` devolve `ExtractionResult(banco, product, transactions,
   segmentos, holder_names)`. Cada `RawTransaction` tem data, histórico (o tipo do lançamento),
   valor, a que segmento pertence, contraparte e documento (se o layout tiver), e as marcas
   `duplicate`, `omitted` e `review_reason`.
3. **Conferir.** Para cada `Segment`: `opening + soma dos valores == closing`. Formatos que
   comprovadamente não têm totais (`NO_TOTALS`, ex.: o CSV do Nubank) passam como `sem_totais`.
   Arquivos que juntam vários documentos (`REJECT_BY_DOCUMENT`) rejeitam só o documento que não
   bate.
4. **Transformar cada lançamento** (os `duplicate`/`omitted` entram na conferência, mas não na
   saída):
   1. `historico = normalize_history(patterns.remove(bruto, nomes_do_titular))`;
   2. `meio = parser.METHODS[historico]`. O mapa é explícito: um histórico fora dele rejeita o
      arquivo (`HistoricoDesconhecido`) e é anotado em `data/privado/historicos_desconhecidos.csv`
      para ser incluído;
   3. `contraparte = resolve_counterparty(nome, documento, meio, nomes)`. O resultado é o valor
      final ou `Review(motivo)`. Nesse caso a linha vai para `data/privado/revisar.csv` e sai da
      saída;
   4. `merchants.standardize`: nome-base do estabelecimento e pessoa na maquininha →
      `PESSOA_FISICA`;
   5. `OutputRow(...)`, um modelo pydantic estrito. Linha inválida rejeita o arquivo
      (`linhas_invalidas:<n>`). Nunca propague a mensagem do pydantic, porque ela contém o valor;
   6. guarda o original `{historico, contraparte}` na mesma ordem das linhas.
5. **Validar e gravar.** `write_csv` varre `historico` e `contraparte` de todas as linhas (padrões
   + nomes do titular). Achou → `LeakDetected` e nada é gravado. Senão grava num `.tmp` e renomeia.

Os nomes do titular e dos portadores vêm do cabeçalho de cada documento (`holder_names`). Com eles
se monta uma regex de variantes (nome completo e cada par de nomes consecutivos) usada para apagar
e para validar. No modo `tudo`, os nomes de todas as pastas valem para todas, porque o titular de
uma pasta pode aparecer como contraparte no extrato de outra.

Código: [references/pipeline.md](references/pipeline.md) (modelos, normalização, pipeline,
validador, CLI).

## Como escrever um parser para um formato novo

1. **Arquivo real só na máquina do usuário** (`data/raw/<n>/`), nunca no git nem num teste.
2. **Veja o texto como o pdfplumber extrai.** A saída tem dados pessoais: use só para entender o
   layout, sem colar em testes ou commits.
   ```python
   import sys, pdfplumber
   with pdfplumber.open(sys.argv[1]) as pdf:
       for n, pagina in enumerate(pdf.pages, 1):
           for i, linha in enumerate((pagina.extract_text() or "").splitlines()):
               print(f"p{n} {i:03} {linha}")
   ```
3. **Classifique cada tipo de linha**: cabeçalho fixo (vira a assinatura de `detect` e dá o nome do
   titular), período, linha de dia/saldo, lançamento, continuação de lançamento, rodapé e cabeçalho
   repetido (ignorados explicitamente), totais. Cada tipo ganha uma regex ancorada (`^...$`). Linha
   que não casa com nenhuma → `UnexpectedLayout(self.name, "linha_desconhecida", pagina)`.
4. **Valores** com `br_amount` ("1.234,56", "R$ -1,00", "1.234,56-"). Sufixos próprios do banco
   (C/D) são tratados antes.
5. **Segmentos**: modele o que o documento declara.
   - Conta com saldo após cada lançamento: cada lançamento é um segmento (saldo anterior + valor
     == saldo após).
   - Conta com "saldo do dia": um segmento por dia.
   - Fatura: `opening = -saldo da fatura anterior` (0 se não houver) e `closing = -total da
     fatura`. O pagamento da fatura anterior e o saldo remanescente entram com `omitted=True`,
     porque já estão no extrato da conta.
   - Vários documentos num arquivo: preencha `Segment.document` e use `REJECT_BY_DOCUMENT = True`.
   - Um lançamento pode pertencer a mais de um segmento (`segment=(i, j)`, por exemplo o dia e o
     extrato todo).
   - Outros números declarados viram checagens de layout (ex.: "saldo total" do cabeçalho == saldo
     do último lançamento).
6. **`METHODS`**: um dicionário histórico normalizado → `PaymentMethod`, só com os tipos vistos em
   extratos reais. Um tipo novo depois rejeita o arquivo com uma mensagem clara, nunca um palpite.
7. **Contraparte**: para cada tipo de lançamento, decida de onde vêm o nome e o documento, ou se
   não há contraparte. Se o parser não consegue garantir a anonimização (ex.: não achou a cidade no
   fim do nome do estabelecimento), preencha `review_reason`.
8. **Registre** o parser em `registry.PARSERS`. O nome segue `<banco>_<produto>_<ext>` e nunca
   muda, porque fica gravado no banco e o frontend o traduz.
9. **Teste com conteúdo inventado** que imita o layout ("FULANO DE TESTE", valores inventados). Para
   PDF, leia o texto só por `pdf_text(path)` e, nos testes, troque essa função por páginas
   inventadas (`monkeypatch.setattr("statement.parsers.<modulo>.pdf_text", ...)`). Exemplos em
   [references/parsers.md](references/parsers.md).
10. **Rode contra o arquivo real** na máquina do usuário:
    `python -m statement extrair --entrada data/raw/7 --usuario u07 --saida data/saida/u07.csv`.
    Confira no relatório: reconciliação `ok`, `revisar` zerado ou explicado, nenhum histórico
    desconhecido. Rejeições viram ajustes no parser, com um teste novo para cada variante de layout.

O código de `base.py`, `registry.py`, `reconciliation.py`, um parser CSV completo, o esqueleto de um
parser PDF e os testes está em [references/parsers.md](references/parsers.md).

## Anonimização (resumo)

Regras completas e código em [references/anonimizacao.md](references/anonimizacao.md).

- **Padrões apagados de todo texto**: linha digitável e código de barras de boleto, e-mail, chave
  PIX aleatória (UUID), CNPJ, CPF (completo ou mascarado com `*`, `•` ou `X`), número de cartão
  (inteiro, mascarado, "FINAL 1234"), agência/conta, telefone, CEP, endereço, qualquer sequência de
  6 ou mais dígitos. Também as variantes do nome do titular.
- **Regra da contraparte**, em ordem:
  1. ambíguo (vai para revisão): CPF e CNPJ juntos, sufixo ME/MEI/EPP, nome começando com raiz de
     CNPJ, ou nome com 8+ dígitos em PIX/TED/boleto;
  2. CPF → `PESSOA_FISICA` (ambíguo se o nome tiver marca de empresa);
  3. CNPJ ou marca de empresa (LTDA, S.A., EIRELI, CIA) → empresa;
  4. sem documento em PIX/TED/boleto → `PESSOA_FISICA`, a menos que o nome não comece com um
     primeiro nome e tenha palavra de empresa ou seja uma palavra só;
  5. sem documento nos outros meios (cartão) → empresa.
- **Cartão**: fica só o que vem antes do `*` ("IFOOD *RESTAURANTE X" → "IFOOD"). Intermediários
  (PAG, MP, STONE, PICPAY...) ficam só com o próprio nome, porque o que vem depois é o vendedor,
  muitas vezes uma pessoa.
- **Nome-base**: tira o número da loja no fim ("LOJA X 37" → "LOJA X"). Se o nome-base parece de
  pessoa (começa com um primeiro nome brasileiro e não tem palavra de empresa) vira `PESSOA_FISICA`.
  A regra erra de propósito para o lado de "é pessoa". O usuário também pode marcar pessoas no mapa
  privado (`e_pessoa = sim`).
- **A mesma padronização vale no treino e na inferência**: o modelo de ML vê sempre o mesmo tipo
  de contraparte.

## Erros com código estável

| Exceção | `code` (vai para o relatório e a API) |
|---|---|
| `UnrecognizedFormat` | `FormatoNaoReconhecido` |
| `AmbiguousFormat` | `FormatoAmbiguo` |
| `UnexpectedLayout(parser, motivo, page)` | `LayoutInesperado` → motivo `LayoutInesperado:<motivo>@p<página>` |
| `UnknownHistory(parser, historico)` | `HistoricoDesconhecido` (o histórico fica no atributo, não na mensagem) |
| `ReconciliationFailed` | `ReconciliacaoFalhou` |
| `LeakDetected(counts)` | `VazamentoDetectado` (só contagens por tipo de padrão) |

O código é um atributo de classe, não o nome da classe: assim a classe pode ser renomeada sem
mudar o contrato.

## CLI e arquivos

```bash
python -m statement extrair --entrada <pasta|arquivo> --usuario uNN --saida data/saida/uNN.csv
python -m statement tudo        # cada subpasta N de data/raw/ é o usuário uNN; junta em data/saida/transacoes.csv
```

- `--privado` (padrão `data/privado`) recebe `revisar.csv` e `historicos_desconhecidos.csv`. Os
  dois têm dados reais e ficam fora do git. Cada execução substitui só as linhas daquele usuário.
- `<saida>.relatorio.csv` traz só contagens por arquivo.
- Códigos de saída: `0` tudo aceito, `1` algum arquivo rejeitado, `2` gravação bloqueada por
  possível vazamento, `3` argumento inválido.

## Testes desta camada

- `models`: pseudônimo `uNN`, slug do banco, histórico já normalizado, valor ≠ 0 com 2 casas, sinal
  coerente com o tipo.
- `normalization`: as formas aceitas e recusadas de `br_amount`; `normalize_history` tira tokens
  com dígito.
- `anonymization`: cada regra da contraparte com nomes inventados (CPF mascarado, MEI,
  intermediário de cartão, empresa sem documento em PIX).
- `validation`: vazamento bloqueia a gravação e o CSV anterior continua intacto.
- `pipeline` com um parser falso (arquivo `.fake`): registro (nenhum, ambíguo, um), conferência
  ok e falha, histórico desconhecido rejeita, linhas de revisão saem da saída, CSV final exato.
- Cada parser real: `detect` pela assinatura, extração de linhas inventadas, rejeição fora do
  layout (`parametrize` com o `motivo` esperado).

## Armadilhas

- `Decimal`, nunca `float`, do texto até o CSV.
- Saída em NFC com acentos. `strip_accents` só para comparar, nunca para gravar.
- `pdf_text` e `first_line` usam `lru_cache`: num servidor, limpe os caches depois de processar,
  porque eles guardam o texto do arquivo em memória.
- Não corte a cidade de forma genérica: muitos nomes de loja terminam numa palavra que também é
  município ("PADARIA MODELO"). Corte só onde o layout garante a cidade no fim, com
  `cities.split_city`.
- Não "conserte" um layout desconhecido afrouxando a regex. Acrescente a variante exata vista, com
  teste.
- O nome do arquivo enviado pode ter dado pessoal: na API, grave o arquivo temporário com nome fixo.
