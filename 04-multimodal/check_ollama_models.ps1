# PowerShell скрипт для проверки и установки моделей Ollama

$SERVER_IP = "195.209.210.20"
$SSH_KEY = "$env:USERPROFILE\.ssh\immers-vm.pem"

Write-Host "=== Проверка доступности Ollama API ==="
try {
    $response = Invoke-RestMethod -Uri "http://${SERVER_IP}:11434/api/tags" -TimeoutSec 5 -ErrorAction Stop
    Write-Host "✅ API доступен"
} catch {
    Write-Host "❌ API недоступен: $($_.Exception.Message)"
    Write-Host "Проверьте статус сервера в immers.cloud"
    exit 1
}

Write-Host ""
Write-Host "=== Список установленных моделей ==="
$modelsList = ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${SERVER_IP} "ollama list" 2>&1
Write-Host $modelsList

Write-Host ""
Write-Host "=== Проверка требуемых моделей ==="
$requiredModels = @("gpt-oss:20b", "qwen3-vl:8b-instruct")
$availableModels = ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${SERVER_IP} "ollama list" 2>&1 | 
    Select-String -Pattern "^\w" | 
    ForEach-Object { ($_ -split '\s+')[0] }

foreach ($model in $requiredModels) {
    if ($availableModels -contains $model) {
        Write-Host "✅ $model - установлена"
    } else {
        Write-Host "❌ $model - не найдена"
        Write-Host "   Скачиваю $model..."
        ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${SERVER_IP} "ollama pull $model"
    }
}

Write-Host ""
Write-Host "=== Итоговый список моделей ==="
ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@${SERVER_IP} "ollama list"

