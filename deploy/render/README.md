# Publicar no Render

Um único serviço web (Docker): a API serve a página e o Render dá o HTTPS
(`https://<nome>.onrender.com`). Banco e login continuam no Supabase.

Arquivos envolvidos: `Dockerfile` e `render.yaml` (na raiz), `deploy/render/start.sh` (coloca os
Secret Files no lugar e sobe a API) e `deploy/render/make-secret-files.ps1`.

## Plano grátis: o que esperar

- **Dorme depois de 15 min sem acesso**; a primeira visita depois disso leva ~1 minuto.
- **512 MB de RAM** (a API usa ~230 MB) e CPU fraca: importar PDF e o retreino são mais lentos.
- **Disco temporário**: o modelo retreinado se perde a cada deploy ou reinício (volta o do Secret
  File). Para guardar, é preciso um plano pago com disco persistente.
- **Sem região no Brasil**: o serviço fica na Virgínia (EUA); cada consulta ao Supabase (São Paulo)
  leva ~0,1 s a mais.

## 1. Preparar os Secret Files (nesta máquina)

```powershell
.\deploy\render\make-secret-files.ps1
```
Cria `~\render-secret-files` (fora do projeto) com:

| Arquivo | Para quê |
|---|---|
| `svm_tfidf.pkl.gz.b64` | o classificador, compactado (gzip) e em base64 |
| `estabelecimentos_revisar.csv`, `estabelecimentos_novos.csv` | os mapas com as pessoas marcadas (anonimização) |
| `transacoes_rotuladas.csv.gz.b64` | CSV base do retreino, compactado (opcional) |

O Render limita **todos os Secret Files de um serviço a 1 MB juntos** e só aceita texto: por isso
os dois arquivos grandes vão compactados e em base64 (~660 KB no total). O `start.sh` desfaz isso
ao subir. O script mostra o total e avisa se passar do limite.

**Têm dados reais:** apague a pasta depois de colar no Render.

## 2. Criar o serviço

1. Entre em **render.com** com a conta do GitHub e dê acesso ao repositório.
2. **New > Blueprint**, escolha o repositório. O Render lê o `render.yaml` e pede os valores
   secretos: copie do seu `.env` os de `DATABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`,
   `GEMINI_API_KEY`, `GEMINI_MODEL` e `CHAVE_ORIGINAIS` (a **mesma** chave da equipe, senão os
   originais já gravados não abrem).
3. No serviço criado: **Environment > Secret Files > Add Secret File**, um para cada arquivo
   do passo 1. O **nome tem que ser exatamente o do arquivo**; no conteúdo, cole o texto do arquivo
   (ex.: `Get-Content -Raw -Encoding UTF8 "$HOME\render-secret-files\<arquivo>" | Set-Clipboard`).
4. **Manual Deploy > Deploy latest commit**. O primeiro build leva ~5–10 min.
5. Teste: `https://<nome>.onrender.com/api/saude` deve mostrar `{"status":"ok"}`.

## 3. Ajustar o login no Supabase

Em **Authentication > URL Configuration**: **Site URL** = `https://<nome>.onrender.com`; em
**Redirect URLs** adicione `https://<nome>.onrender.com/**` e **mantenha** `http://localhost:5173/**`.

## Versões novas

Cada merge na `main` publica sozinho (o Render faz o build e troca a versão). Se o modelo ou os
mapas mudarem, rode o passo 1 de novo e substitua os Secret Files.

## Se algo der errado

- **Logs**: aba **Logs** do serviço. Os avisos do `start.sh` aparecem lá (ex.: Secret File ausente).
- **Login não volta para a página**: falta o endereço no Supabase (passo 3).
- **"Out of memory"**: o plano grátis tem 512 MB; um PDF muito grande ou o retreino podem passar
  disso. O plano Starter tem o mesmo tanto de RAM, mas CPU melhor e não dorme.
