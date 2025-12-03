#!/bin/bash
# Скрипт для проверки и установки моделей Ollama

SERVER_IP="195.209.210.20"
SSH_KEY="$HOME/.ssh/immers-vm.pem"

echo "=== Проверка доступности Ollama API ==="
if curl -s --max-time 5 "http://${SERVER_IP}:11434/api/tags" > /dev/null; then
    echo "✅ API доступен"
else
    echo "❌ API недоступен. Проверьте статус сервера."
    exit 1
fi

echo ""
echo "=== Список установленных моделей ==="
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@${SERVER_IP} "ollama list"

echo ""
echo "=== Проверка требуемых моделей ==="
REQUIRED_MODELS=("gpt-oss:20b" "qwen3-vl:8b-instruct")
AVAILABLE_MODELS=$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@${SERVER_IP} "ollama list" | awk '{print $1}' | tail -n +2)

for model in "${REQUIRED_MODELS[@]}"; do
    if echo "$AVAILABLE_MODELS" | grep -q "^${model}$"; then
        echo "✅ $model - установлена"
    else
        echo "❌ $model - не найдена"
        echo "   Скачиваю $model..."
        ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@${SERVER_IP} "ollama pull $model"
    fi
done

echo ""
echo "=== Итоговый список моделей ==="
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@${SERVER_IP} "ollama list"

