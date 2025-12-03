# Техническое видение проекта

## Технологии

**Основные технологии:**
- **Python 3.11+** - основной язык разработки
- **uv** - управление зависимостями и виртуальным окружением
- **aiogram 3.x** - фреймворк для Telegram Bot API (polling)
- **openai** - клиент для работы с LLM через OpenRouter/Ollama (единый интерфейс)
- **pydantic** - валидация данных и structured output для LLM
- **python-dotenv** - для работы с переменными окружения
- **Make** - автоматизация сборки и запуска

## Принципы разработки

**Принципы:**
- **KISS** (Keep It Simple, Stupid) - максимальная простота решений
- **YAGNI** (You Aren't Gonna Need It) - реализуем только то, что нужно сейчас
- **Монолитная архитектура** - весь код в одном месте, никаких микросервисов
- **Прямолинейный код** - минимум абстракций, максимум читаемости
- **Быстрый старт** - от идеи до рабочего прототипа за минимальное время

**Что НЕ делаем:**
- Не создаем сложные архитектурные паттерны
- Не делаем преждевременную оптимизацию
- Не добавляем функции "на будущее"
- Не усложняем без крайней необходимости

## Структура проекта

```
/
├── src/
│   ├── bot.py          # Основной файл бота, инициализация aiogram
│   ├── handlers.py     # Обработчики команд и сообщений Telegram
│   ├── llm.py          # Работа с LLM через OpenRouter/Ollama
│   ├── models.py       # Pydantic модели для транзакций
│   ├── transcription.py # Транскрибация голосовых сообщений (Yandex SpeechKit / OpenAI Whisper)
│   └── config.py       # Загрузка конфигурации из .env
├── prompts/
│   ├── system_prompt_text.txt   # Системный промпт для текстовых сообщений
│   └── system_prompt_image.txt  # Системный промпт для изображений
├── .env                # Переменные окружения (токены, настройки)
├── .env.example        # Пример конфигурации
├── pyproject.toml      # Конфигурация проекта для uv
├── Makefile            # Команды для запуска и управления
└── README.md           # Документация по запуску
```

**Принцип:** Всего 5 Python-файлов в одной папке `src/`. Никаких пакетов, подпакетов, сложной иерархии.

## Архитектура проекта

**Компоненты:**

1. **bot.py** - точка входа
   - Инициализирует aiogram Bot и Dispatcher
   - Регистрирует handlers
   - Запускает polling

2. **handlers.py** - обработка событий
   - `/start` - приветствие и очистка истории/транзакций
   - `/balance` - отчет о балансе и статистике
   - Обработчик текстовых сообщений → извлечение транзакций через LLM → сохранение транзакций → показ ответа + статус + баланс
   - Обработчик изображений → извлечение транзакций через VLM → сохранение транзакций → показ ответа + статус + баланс
   - Обработчик голосовых сообщений → транскрибация через Whisper API → текст → извлечение транзакций через LLM → сохранение транзакций → показ ответа + статус + баланс
   - Хранит историю диалогов в памяти: `dict[int, list]` (chat_id → список сообщений)
   - Хранит транзакции в памяти: `dict[int, list[Transaction]]` (chat_id → список транзакций)

3. **llm.py** - интеграция с LLM
   - Метод `get_transaction_response_text()` - обработка текстовых сообщений со structured output
   - Метод `get_transaction_response_image()` - обработка изображений (VLM) со structured output
   - Единый интерфейс через AsyncOpenAI для OpenRouter и Ollama
   - Переключение между внешними и локальными моделями через конфигурацию

4. **transcription.py** - транскрибация голосовых сообщений
   - Метод `transcribe_voice()` - универсальный метод, поддерживающий несколько провайдеров
   - `transcribe_voice_openai()` - транскрибация через OpenAI Whisper API
   - `transcribe_voice_yandex()` - транскрибация через Yandex SpeechKit API
   - Выбор провайдера через `TRANSCRIPTION_PROVIDER` в конфигурации
   - Конвертация форматов аудио (OGG Opus → формат для выбранного API)
   - Обработка ошибок транскрибации

4. **models.py** - модели данных
   - Pydantic модели для транзакций (Transaction, TransactionResponse)
   - Enums для типов транзакций (TransactionType, TransactionFrequency)
   - Валидация данных транзакций

5. **config.py** - конфигурация
   - Класс Config с полями: `TELEGRAM_TOKEN`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `MODEL_TEXT`, `MODEL_IMAGE`, `SYSTEM_PROMPT_TEXT`, `SYSTEM_PROMPT_IMAGE`
   - Конфигурация транскрибации: `WHISPER_API_KEY`, `TRANSCRIPTION_PROVIDER`, `YANDEX_SPEECHKIT_API_KEY`, `YANDEX_SPEECHKIT_FOLDER_ID`
   - Загрузка промптов из файлов (`prompts/system_prompt_text.txt`, `prompts/system_prompt_image.txt`) или переменных окружения
   - Пути к файлам промптов можно задать через `SYSTEM_PROMPT_TEXT_PATH` и `SYSTEM_PROMPT_IMAGE_PATH` в .env
   - Загрузка из .env через python-dotenv
   - `MODEL_TEXT` - модель для текстовых сообщений, `MODEL_IMAGE` - модель для изображений (vision)
   - `TRANSCRIPTION_PROVIDER` - выбор провайдера транскрибации: "openai" или "yandex"

**Поток данных (текстовые сообщения):**
```
Telegram → handlers.py (последнее сообщение) → llm.py (structured output) → OpenRouter/Ollama → 
llm.py → handlers.py (извлечь транзакции, сохранить в transactions, показать ответ + статус + баланс) → Telegram
```

**Поток данных (изображения):**
```
Telegram → handlers.py (изображение → base64) → llm.py (VLM + structured output) → OpenRouter/Ollama → 
llm.py → handlers.py (извлечь транзакции, сохранить в transactions, показать ответ + статус + баланс) → Telegram
```

**Поток данных (голосовые сообщения):**
```
Telegram → handlers.py (голосовое сообщение → скачивание → конвертация) → 
transcription.py (Yandex SpeechKit / OpenAI Whisper API) → текст → handlers.py → 
llm.py (structured output) → OpenRouter/Ollama → 
llm.py → handlers.py (извлечь транзакции, сохранить в transactions, показать ответ + статус + баланс) → Telegram
```

**Примечание:** Обработка голосовых сообщений реализована, но временно отключена в продакшене из-за проблем с настройкой прав доступа в Yandex Cloud. Код готов к использованию после настройки провайдера транскрибации.

**Принцип:** Никакой DI, никаких интерфейсов, никаких слоев абстракции. Просто прямые вызовы функций.

