# Скрипт для автоматической настройки Ollama на новом сервере
# Использование: .\setup_ollama_server.ps1 -ServerIP "195.209.210.20"

param(
    [Parameter(Mandatory=$true)]
    [string]$ServerIP
)

$SSH_KEY = "$env:USERPROFILE\.ssh\immers-vm.pem"

Write-Host "=== Автоматическая настройка Ollama на сервере $ServerIP ===" -ForegroundColor Green
Write-Host ""

# Проверка SSH ключа
if (-not (Test-Path $SSH_KEY)) {
    Write-Host "❌ SSH ключ не найден: $SSH_KEY" -ForegroundColor Red
    Write-Host "Убедитесь, что ключ скачан из immers.cloud и сохранен в указанном месте."
    exit 1
}

Write-Host "✅ SSH ключ найден" -ForegroundColor Green
Write-Host ""

# Шаг 1: Проверка подключения
Write-Host "[1/6] Проверка SSH подключения..." -ForegroundColor Yellow
try {
    $test = ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10 ubuntu@${ServerIP} "echo 'Connected'" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ SSH подключение работает" -ForegroundColor Green
    } else {
        throw "SSH connection failed"
    }
} catch {
    Write-Host "❌ Не удалось подключиться к серверу" -ForegroundColor Red
    Write-Host "Проверьте:"
    Write-Host "  - IP адрес правильный: $ServerIP"
    Write-Host "  - Сервер в состоянии ACTIVE"
    Write-Host "  - SSH ключ правильный"
    exit 1
}

# Шаг 2: Проверка GPU
Write-Host ""
Write-Host "[2/6] Проверка GPU..." -ForegroundColor Yellow
$gpu = ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${ServerIP} "nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1"
if ($gpu) {
    Write-Host "✅ GPU обнаружен: $gpu" -ForegroundColor Green
} else {
    Write-Host "⚠️ GPU не обнаружен, но продолжаем..." -ForegroundColor Yellow
}

# Шаг 3: Установка Ollama
Write-Host ""
Write-Host "[3/6] Установка Ollama..." -ForegroundColor Yellow
$ollamaInstalled = ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${ServerIP} "which ollama > /dev/null 2>&1 && echo 'yes' || echo 'no'"
if ($ollamaInstalled -eq "yes") {
    Write-Host "✅ Ollama уже установлен" -ForegroundColor Green
    $version = ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${ServerIP} "ollama --version"
    Write-Host "   Версия: $version"
} else {
    Write-Host "Устанавливаю Ollama..." -ForegroundColor Cyan
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${ServerIP} "curl -fsSL https://ollama.com/install.sh | sh" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Ollama установлен" -ForegroundColor Green
    } else {
        Write-Host "❌ Ошибка установки Ollama" -ForegroundColor Red
        exit 1
    }
}

# Шаг 4: Настройка доступа через интернет
Write-Host ""
Write-Host "[4/6] Настройка доступа через интернет..." -ForegroundColor Yellow
ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${ServerIP} @"
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo bash -c 'cat > /etc/systemd/system/ollama.service.d/override.conf << EOF
[Service]
Environment=OLLAMA_HOST=0.0.0.0:11434
EOF'
sudo systemctl daemon-reload
sudo systemctl restart ollama
sleep 3
"@ | Out-Null

$listening = ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${ServerIP} "sudo ss -tlnp 2>/dev/null | grep ':11434' | grep -q '\*:11434' && echo 'yes' || echo 'no'"
if ($listening -eq "yes") {
    Write-Host "✅ Ollama слушает на всех интерфейсах (0.0.0.0:11434)" -ForegroundColor Green
} else {
    Write-Host "⚠️ Проверьте настройку доступа вручную" -ForegroundColor Yellow
}

# Шаг 5: Проверка и установка моделей
Write-Host ""
Write-Host "[5/6] Проверка моделей..." -ForegroundColor Yellow
$models = ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${ServerIP} "ollama list" 2>&1
Write-Host "Текущие модели:"
$models | Select-String -Pattern "^\w" | ForEach-Object { Write-Host "  - $_" }

$requiredModels = @("gpt-oss:20b", "qwen3-vl:8b-instruct")
$availableModels = ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${ServerIP} "ollama list 2>&1" | 
    Select-String -Pattern "^\w" | 
    ForEach-Object { ($_ -split '\s+')[0] }

foreach ($model in $requiredModels) {
    if ($availableModels -contains $model) {
        Write-Host "✅ $model - уже установлена" -ForegroundColor Green
    } else {
        Write-Host "Скачиваю $model..." -ForegroundColor Cyan
        ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${ServerIP} "ollama pull $model" 2>&1 | 
            ForEach-Object { 
                if ($_ -match "pulling|success|error") { Write-Host "  $_" }
            }
    }
}

# Шаг 6: Проверка API
Write-Host ""
Write-Host "[6/6] Проверка API..." -ForegroundColor Yellow
try {
    $apiTest = Invoke-RestMethod -Uri "http://${ServerIP}:11434/api/tags" -TimeoutSec 10 -ErrorAction Stop
    Write-Host "✅ API доступен из интернета!" -ForegroundColor Green
    Write-Host "Доступные модели через API:"
    $apiTest.models | ForEach-Object { Write-Host "  - $($_.name)" }
} catch {
    Write-Host "⚠️ API недоступен из интернета: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "Проверьте настройки firewall на immers.cloud"
}

Write-Host ""
Write-Host "=== Настройка завершена! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Следующие шаги:"
Write-Host "1. Обновите .env файл с IP: $ServerIP"
Write-Host "2. Запустите бота: uv run python src/bot.py"

