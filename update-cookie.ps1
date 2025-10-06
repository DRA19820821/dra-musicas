# Script para atualizar o cookie do Suno no arquivo .env
# Uso: .\update-cookie.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Atualizador de Cookie Suno" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$envPath = ".env"

# Backup do .env atual
if (Test-Path $envPath) {
    $backupPath = ".env.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Copy-Item $envPath $backupPath
    Write-Host "[OK] Backup criado: $backupPath" -ForegroundColor Green
    Write-Host ""
}

Write-Host "INSTRUCOES PARA OBTER O COOKIE:" -ForegroundColor Yellow
Write-Host "1. Abra o navegador e acesse: https://suno.com" -ForegroundColor White
Write-Host "2. Faca login na sua conta" -ForegroundColor White
Write-Host "3. Pressione F12 para abrir o DevTools" -ForegroundColor White
Write-Host "4. Va em: Application (ou Aplicativo) -> Cookies -> https://suno.com" -ForegroundColor White
Write-Host "5. Na coluna 'Name', procure por '__client'" -ForegroundColor White
Write-Host "6. Copie APENAS o valor do cookie '__client'" -ForegroundColor White
Write-Host ""
Write-Host "ATENCAO: Voce pode copiar TODO o cookie header se preferir," -ForegroundColor Cyan
Write-Host "mas o campo '__client' eh o mais importante." -ForegroundColor Cyan
Write-Host ""

# Solicita o novo cookie
$newCookie = Read-Host "Cole o novo cookie aqui e pressione Enter"

if ([string]::IsNullOrWhiteSpace($newCookie)) {
    Write-Host ""
    Write-Host "[ERRO] Cookie vazio! Operacao cancelada." -ForegroundColor Red
    exit 1
}

# Remove espacos em branco
$newCookie = $newCookie.Trim()

Write-Host ""
Write-Host "[INFO] Cookie recebido (primeiros 50 caracteres): $($newCookie.Substring(0, [Math]::Min(50, $newCookie.Length)))..." -ForegroundColor Cyan

# Le o arquivo .env atual
$envContent = @()
if (Test-Path $envPath) {
    $envContent = Get-Content $envPath
}

# Atualiza ou adiciona o SUNO_COOKIE
$cookieFound = $false
$newContent = @()

foreach ($line in $envContent) {
    if ($line -match '^SUNO_COOKIE=') {
        $newContent += "SUNO_COOKIE=`"$newCookie`""
        $cookieFound = $true
        Write-Host "[OK] SUNO_COOKIE atualizado no .env" -ForegroundColor Green
    } elseif ($line -match '^TWOCAPTCHA_KEY=') {
        $newContent += $line
    } else {
        $newContent += $line
    }
}

if (-not $cookieFound) {
    $newContent += "SUNO_COOKIE=`"$newCookie`""
    Write-Host "[OK] SUNO_COOKIE adicionado ao .env" -ForegroundColor Green
}

# Garante que TWOCAPTCHA_KEY existe
if (-not ($newContent -match 'TWOCAPTCHA_KEY=')) {
    Write-Host ""
    $twocaptcha = Read-Host "Digite sua chave 2Captcha (ou deixe em branco para usar a atual)"
    if (-not [string]::IsNullOrWhiteSpace($twocaptcha)) {
        $newContent += "TWOCAPTCHA_KEY=`"$twocaptcha`""
    }
}

# Salva o novo .env
$newContent | Set-Content -Path $envPath -Encoding UTF8

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Cookie atualizado com sucesso!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "PROXIMOS PASSOS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Pare os containers:" -ForegroundColor White
Write-Host "   docker compose down" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. Copie o arquivo .env para o diretorio suno-api:" -ForegroundColor White
Write-Host "   Copy-Item .env suno-api\.env -Force" -ForegroundColor Cyan
Write-Host ""
Write-Host "3. Reconstrua o container suno-api:" -ForegroundColor White
Write-Host "   docker compose build suno-api" -ForegroundColor Cyan
Write-Host ""
Write-Host "4. Inicie novamente:" -ForegroundColor White
Write-Host "   docker compose up" -ForegroundColor Cyan
Write-Host ""
Write-Host "5. Teste gerando uma musica pela interface web" -ForegroundColor White
Write-Host ""
Write-Host "DICA: Se o erro persistir, verifique:" -ForegroundColor Yellow
Write-Host "  - Se sua conta Suno tem creditos disponiveis" -ForegroundColor Gray
Write-Host "  - Se o cookie foi copiado corretamente (sem espacos extras)" -ForegroundColor Gray
Write-Host "  - Os logs do suno-api com: docker compose logs suno-api" -ForegroundColor Gray
Write-Host ""