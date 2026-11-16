<#
Prepares the files to paste into Render > Environment > Secret Files, in a folder OUTSIDE the project.

    .\deploy\render\make-secret-files.ps1

Render limits all the Secret Files of a service to 1 MB together and takes text only, so the two
large files (the model and the base CSV) go compressed with gzip and then as base64;
deploy/render/start.sh undoes both. The two maps are small CSVs and go as they are.
These files contain real data: delete the folder after pasting them into Render.
#>
param([string]$OutDir = "$HOME\render-secret-files")

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$limitKb = 1024

function Write-GzipBase64([string]$source, [string]$target) {
    $bytes = [IO.File]::ReadAllBytes($source)
    $buffer = New-Object IO.MemoryStream
    $gzip = New-Object IO.Compression.GZipStream($buffer, [IO.Compression.CompressionLevel]::Optimal)
    $gzip.Write($bytes, 0, $bytes.Length)
    $gzip.Close()
    [IO.File]::WriteAllText($target, [Convert]::ToBase64String($buffer.ToArray()))
}

# start clean: files from older versions (e.g. svm_tfidf.pkl.b64) must not be pasted by mistake
if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Force $OutDir | Out-Null

Write-GzipBase64 "$root\ml\modelos\svm_tfidf.pkl" "$OutDir\svm_tfidf.pkl.gz.b64"
Write-GzipBase64 "$root\ml\dados\transacoes_rotuladas.csv" "$OutDir\transacoes_rotuladas.csv.gz.b64"
Copy-Item "$root\data\private\estabelecimentos_revisar.csv", "$root\data\private\estabelecimentos_novos.csv" $OutDir

$files = Get-ChildItem $OutDir
$totalKb = [math]::Round(($files | Measure-Object Length -Sum).Sum / 1KB)
Write-Host "Arquivos para o Render em: $OutDir"
$files | Format-Table Name, @{ Name = "KB"; Expression = { [math]::Round($_.Length / 1KB) } } -AutoSize
Write-Host "Total: $totalKb KB (limite do Render: $limitKb KB para todos juntos)"
if ($totalKb -ge $limitKb) { Write-Warning "Passou do limite: o Render vai recusar. Deixe o transacoes_rotuladas.csv.gz.b64 de fora (só o retreino usa)." }
