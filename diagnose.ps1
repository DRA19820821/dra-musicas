# Script de diagnostico do Suno Music Processor
# Uso: .\diagnose.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Diagnostico do Sistema" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Verifica se Docker esta rodando
Write-Host "[1/7] Verificando Docker..." -ForegroundColor Yellow
try {
    $dockerVersion = docker --version
    Write-Host "  OK Docker instalado: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERRO Docker nao encontrado ou nao esta rodando!" -ForegroundColor Red
    exit 1
}

# Verifica se docker-compose esta disponivel
Write-Host ""
Write-Host "[2/7] Verificando Docker Compose..." -ForegroundColor Yellow
try {
    $composeVersion = docker compose version
    Write-Host "  OK Docker Compose disponivel: $composeVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERRO Docker Compose nao encontrado!" -ForegroundColor Red
    exit 1
}

# Verifica arquivo .env
Write-Host ""
Write-Host "[3/7] Verificando arquivo .env..." -ForegroundColor Yellow
if (Test-Path ".env") {
    Write-Host "  OK Arquivo .env encontrado" -ForegroundColor Green
    
    $envContent = Get-Content ".env" -Raw
    
    if ($envContent -match 'SUNO_COOKIE="(.+)"') {
        $cookie = $matches[1]
        $cookieLength = $cookie.Length
        Write-Host "  OK SUNO_COOKIE presente (tamanho: $cookieLength caracteres)" -ForegroundColor Green
        
        if ($cookieLength -lt 100) {
            Write-Host "  ATENCAO: Cookie parece muito curto!" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  ERRO SUNO_COOKIE nao encontrado ou malformatado!" -ForegroundColor Red
    }
    
    if ($envContent -match 'TWOCAPTCHA_KEY') {
        Write-Host "  OK TWOCAPTCHA_KEY presente" -ForegroundColor Green
    } else {
        Write-Host "  AVISO TWOCAPTCHA_KEY nao encontrado" -ForegroundColor Yellow
    }
} else {
    Write-Host "  ERRO Arquivo .env nao encontrado!" -ForegroundColor Red
}

# Verifica se containers estao rodando
Write-Host ""
Write-Host "[4/7] Verificando containers..." -ForegroundColor Yellow
try {
    $psOutput = docker compose ps --format json 2>&1
    
    if ($psOutput -match "no configuration file provided") {
        Write-Host "  ERRO docker-compose.yml nao encontrado!" -ForegroundColor Red
    } elseif ($psOutput) {
        $containers = $psOutput | ConvertFrom-Json
        
        if ($containers) {
            $requiredServices = @("backend", "suno-api", "postgres", "redis")
            
            foreach ($service in $requiredServices) {
                $container = $containers | Where-Object { $_.Service -eq $service }
                if ($container) {
                    $status = $container.State
                    if ($status -eq "running") {
                        Write-Host "  OK $service esta rodando" -ForegroundColor Green
                    } else {
                        Write-Host "  ERRO $service esta $status" -ForegroundColor Red
                    }
                } else {
                    Write-Host "  ERRO $service nao encontrado" -ForegroundColor Red
                }
            }
        } else {
            Write-Host "  AVISO Nenhum container rodando" -ForegroundColor Yellow
            Write-Host "  Execute: docker compose up -d" -ForegroundColor Cyan
        }
    }
} catch {
    Write-Host "  AVISO Nao foi possivel verificar containers" -ForegroundColor Yellow
    Write-Host "  Erro: $($_.Exception.Message)" -ForegroundColor Gray
}

# Testa conectividade com backend
Write-Host ""
Write-Host "[5/7] Testando backend (http://localhost:8000)..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/models" -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
        Write-Host "  OK Backend respondendo corretamente" -ForegroundColor Green
        $models = ($response.Content | ConvertFrom-Json).models
        Write-Host "  OK Modelos disponiveis: $($models -join ', ')" -ForegroundColor Green
    }
} catch {
    Write-Host "  ERRO Backend nao esta acessivel" -ForegroundColor Red
    Write-Host "    Erro: $($_.Exception.Message)" -ForegroundColor Gray
}

# Testa conectividade com suno-api
Write-Host ""
Write-Host "[6/7] Testando suno-api (http://localhost:3000)..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:3000/" -UseBasicParsing -TimeoutSec 5
    Write-Host "  OK Suno-API respondendo (status: $($response.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "  ERRO Suno-API nao esta acessivel" -ForegroundColor Red
    Write-Host "    Erro: $($_.Exception.Message)" -ForegroundColor Gray
}

# Verifica logs recentes do suno-api
Write-Host ""
Write-Host "[7/7] Verificando logs do suno-api..." -ForegroundColor Yellow
try {
    $logs = docker compose logs suno-api --tail 10 2>&1
    
    if ($logs -match "503") {
        Write-Host "  ERRO Erro 503 detectado nos logs!" -ForegroundColor Red
        Write-Host "    >> A API do Suno esta rejeitando as requisicoes" -ForegroundColor Yellow
        Write-Host "    >> Provavelmente o cookie expirou ou esta invalido" -ForegroundColor Yellow
    } elseif ($logs -match "NoneType.*items") {
        Write-Host "  ERRO Erro de parsing detectado nos logs!" -ForegroundColor Red
        Write-Host "    >> O suno-api nao conseguiu processar a resposta" -ForegroundColor Yellow
    } elseif ($logs -match "INFO.*running") {
        Write-Host "  OK Suno-API operacional" -ForegroundColor Green
    } else {
        Write-Host "  AVISO Nao foi possivel determinar status pelos logs" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  AVISO Nao foi possivel ler logs" -ForegroundColor Yellow
}

# Resumo e recomendacoes
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Resumo e Recomendacoes" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Detecta problemas comuns
$issues = @()

if (-not (Test-Path ".env")) {
    $issues += "Arquivo .env nao encontrado"
}

if ($logs -match "503") {
    $issues += "API Suno retornando erro 503 - Cookie provavelmente expirado"
}

$containersRunning = $false
try {
    $psOutput = docker compose ps --format json 2>&1
    $containersRunning = $psOutput -and ($psOutput | ConvertFrom-Json)
} catch {}

if (-not $containersRunning) {
    $issues += "Containers nao estao rodando"
}

if ($issues.Count -gt 0) {
    Write-Host "PROBLEMAS DETECTADOS:" -ForegroundColor Red
    foreach ($issue in $issues) {
        Write-Host "  - $issue" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "ACOES RECOMENDADAS:" -ForegroundColor Cyan
    Write-Host ""
    
    if ($issues -contains "API Suno retornando erro 503 - Cookie provavelmente expirado") {
        Write-Host "1. Atualize o cookie:" -ForegroundColor White
        Write-Host "   .\update-cookie.ps1" -ForegroundColor Cyan
        Write-Host ""
    }
    
    if ($issues -contains "Containers nao estao rodando") {
        Write-Host "2. Inicie os containers:" -ForegroundColor White
        Write-Host "   docker compose up -d" -ForegroundColor Cyan
        Write-Host ""
    }
    
    Write-Host "3. Verifique os logs completos:" -ForegroundColor White
    Write-Host "   docker compose logs --tail 50" -ForegroundColor Cyan
    Write-Host ""
} else {
    Write-Host "OK Sistema aparenta estar funcionando corretamente!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Se ainda assim voce esta tendo problemas, verifique:" -ForegroundColor Yellow
    Write-Host "  - Os logs completos: docker compose logs" -ForegroundColor Gray
    Write-Host "  - Se sua conta Suno tem creditos" -ForegroundColor Gray
    Write-Host "  - A interface web: http://localhost:8000" -ForegroundColor Gray
}

Write-Host ""