# Script para corrigir o arquivo .env escapando $ para $$
# Uso: .\fix-env.ps1

$envPath = ".env"

if (-not (Test-Path $envPath)) {
    Write-Host "Erro: Arquivo .env não encontrado!" -ForegroundColor Red
    exit 1
}

Write-Host "Lendo arquivo .env..." -ForegroundColor Cyan

# Ler conteúdo
$content = Get-Content $envPath -Raw

Write-Host "Original:" -ForegroundColor Yellow
Write-Host $content.Substring(0, [Math]::Min(200, $content.Length))
Write-Host "..." -ForegroundColor Gray

# Fazer backup
$backupPath = ".env.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Copy-Item $envPath $backupPath
Write-Host "`nBackup criado: $backupPath" -ForegroundColor Green

# Escapar $ para $$ APENAS dentro das aspas do SUNO_COOKIE
$lines = $content -split "`n"
$fixedLines = @()

foreach ($line in $lines) {
    if ($line -match '^SUNO_COOKIE="(.+)"') {
        # Pega o valor do cookie
        $cookieValue = $matches[1]
        
        # Escapa todos os $ para $$
        $fixedCookie = $cookieValue -replace '\$', '$$$$'  # 4x $ porque regex também precisa escape
        
        # Reconstrói a linha
        $fixedLine = "SUNO_COOKIE=`"$fixedCookie`""
        $fixedLines += $fixedLine
        
        Write-Host "`nSUNO_COOKIE corrigido!" -ForegroundColor Green
        Write-Host "Cifrões encontrados: $(($cookieValue.ToCharArray() | Where-Object { $_ -eq '$' }).Count)" -ForegroundColor Yellow
    } else {
        $fixedLines += $line
    }
}

# Salvar arquivo corrigido
$fixedContent = $fixedLines -join "`n"
Set-Content -Path $envPath -Value $fixedContent -NoNewline

Write-Host "`nArquivo .env corrigido!" -ForegroundColor Green
Write-Host "`nPróximos passos:" -ForegroundColor Cyan
Write-Host "1. Execute: docker compose down" -ForegroundColor White
Write-Host "2. Execute: docker compose build suno-api" -ForegroundColor White
Write-Host "3. Execute: docker compose up" -ForegroundColor White
Write-Host "`nVocê NÃO deve mais ver warnings sobre variáveis não definidas." -ForegroundColor Yellow