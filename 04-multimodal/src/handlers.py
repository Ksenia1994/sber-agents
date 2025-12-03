import logging
import base64
import json
import io
from datetime import time
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from openai import APIError, InternalServerError, NotFoundError, APIConnectionError
from llm import get_transaction_response_text, get_transaction_response_image
from models import Transaction
from config import config
from transcription import transcribe_voice

logger = logging.getLogger(__name__)
router = Router()

# Глобальные словари для хранения данных
chat_conversations: dict[int, list[dict]] = {}
transactions: dict[int, list[Transaction]] = {}

# Максимальная длина сообщения пользователя
MAX_MESSAGE_LENGTH = 4000

@router.message(Command("start"))
async def cmd_start(message: Message):
    chat_id = message.chat.id
    logger.info(f"User {chat_id} started the bot")
    
    # Очищаем историю и транзакции для данного чата
    chat_conversations[chat_id] = [
        {"role": "system", "content": config.SYSTEM_PROMPT_TEXT}
    ]
    transactions[chat_id] = []
    
    await message.answer(
        "Привет! Я персональный финансовый советник.\n\n"
        "Я могу:\n"
        "• Извлекать транзакции из ваших текстовых сообщений\n"
        "• Обрабатывать изображения чеков и скриншотов\n"
        "• Распознавать голосовые сообщения и извлекать из них транзакции\n"
        "• Вести учет доходов и расходов\n"
        "• Предоставлять советы по управлению финансами\n\n"
        "Используйте /start для начала нового диалога и очистки истории."
    )

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    chat_id = message.chat.id
    logger.info(f"Balance requested by {chat_id}")
    
    # Получаем транзакции пользователя
    user_transactions = transactions.get(chat_id, [])
    
    if not user_transactions:
        await message.answer(
            "💵 У вас пока нет транзакций.\n\n"
            "Отправьте сообщение с транзакцией или изображение чека для начала учета."
        )
        return
    
    # Расчет баланса, доходов и расходов
    total_income = sum(t.amount for t in user_transactions if t.type.value == "income")
    total_expense = sum(t.amount for t in user_transactions if t.type.value == "expense")
    balance = total_income - total_expense
    
    # Статистика по категориям
    category_stats: dict[str, float] = {}
    for t in user_transactions:
        category = t.category
        if category not in category_stats:
            category_stats[category] = 0.0
        if t.type.value == "income":
            category_stats[category] += t.amount
        else:
            category_stats[category] -= t.amount
    
    # Форматирование отчета
    report_lines = [
        "💵 **Отчет о балансе**\n",
        f"📊 Баланс: {balance:.2f} руб.",
        f"💰 Доходы: {total_income:.2f} руб.",
        f"💸 Расходы: {total_expense:.2f} руб.",
        f"\n📈 Всего транзакций: {len(user_transactions)}",
        "\n**Статистика по категориям:**"
    ]
    
    # Сортируем категории по сумме (от большей к меньшей)
    sorted_categories = sorted(category_stats.items(), key=lambda x: abs(x[1]), reverse=True)
    for category, amount in sorted_categories:
        sign = "💰" if amount > 0 else "💸"
        report_lines.append(f"{sign} {category}: {amount:+.2f} руб.")
    
    await message.answer("\n".join(report_lines))

@router.message(Command("transactions"))
async def cmd_transactions(message: Message):
    chat_id = message.chat.id
    logger.info(f"Transactions list requested by {chat_id}")
    
    # Получаем транзакции пользователя
    user_transactions = transactions.get(chat_id, [])
    
    if not user_transactions:
        await message.answer(
            "📋 У вас пока нет транзакций.\n\n"
            "Отправьте сообщение с транзакцией или изображение чека для начала учета."
        )
        return
    
    # Сортируем транзакции по дате (от новых к старым)
    sorted_transactions = sorted(user_transactions, key=lambda t: (t.date, t.get_time() or time(0, 0)), reverse=True)
    
    # Форматирование списка транзакций
    report_lines = [
        f"📋 **Все транзакции** ({len(user_transactions)} шт.)\n"
    ]
    
    for i, t in enumerate(sorted_transactions, 1):
        # Форматирование даты и времени
        date_str = t.date.strftime("%d.%m.%Y")
        time_obj = t.get_time()
        time_str = f" {time_obj.strftime('%H:%M')}" if time_obj else ""
        
        # Знак и тип транзакции
        sign = "💰" if t.type.value == "income" else "💸"
        type_str = "Доход" if t.type.value == "income" else "Расход"
        
        # Форматирование суммы
        amount_str = f"{t.amount:.2f}".rstrip('0').rstrip('.')
        
        # Описание (если есть)
        desc_str = f"\n   {t.description}" if t.description else ""
        
        report_lines.append(
            f"{i}. {sign} **{type_str}** {amount_str} руб.\n"
            f"   📅 {date_str}{time_str}\n"
            f"   🏷️ {t.category}{desc_str}"
        )
    
    # Если транзакций много, разбиваем на несколько сообщений (Telegram лимит ~4096 символов)
    report_text = "\n\n".join(report_lines)
    if len(report_text) > 4000:
        # Разбиваем на части
        parts = []
        current_part = [report_lines[0]]  # Заголовок
        current_length = len(report_lines[0])
        
        for line in report_lines[1:]:
            line_length = len(line) + 2  # +2 для "\n\n"
            if current_length + line_length > 4000:
                parts.append("\n\n".join(current_part))
                current_part = [line]
                current_length = len(line)
            else:
                current_part.append(line)
                current_length += line_length
        
        if current_part:
            parts.append("\n\n".join(current_part))
        
        # Отправляем части
        for part in parts:
            await message.answer(part)
    else:
        await message.answer(report_text)

@router.message(lambda message: message.photo or (message.document and message.document.mime_type and message.document.mime_type.startswith("image/")))
async def handle_image(message: Message):
    chat_id = message.chat.id
    
    logger.info(f"Image received from {chat_id}")
    
    # Проверяем, что модель для изображений настроена
    if not config.MODEL_IMAGE:
        logger.error("MODEL_IMAGE not configured!")
        await message.answer(
            "❌ Ошибка конфигурации: MODEL_IMAGE не установлен в .env файле.\n\n"
            "Добавьте в .env:\n"
            "MODEL_IMAGE=meta-llama/llama-3.2-11b-vision-instruct"
        )
        return
    
    # Инициализируем историю если её нет
    if chat_id not in chat_conversations:
        chat_conversations[chat_id] = [
            {"role": "system", "content": config.SYSTEM_PROMPT_IMAGE}
        ]
    
    try:
        # Определяем источник изображения
        if message.photo:
            # Берем самое большое изображение
            photo = message.photo[-1]
            file_info = await message.bot.get_file(photo.file_id)
        elif message.document:
            file_info = await message.bot.get_file(message.document.file_id)
        else:
            await message.answer("Не удалось обработать изображение.")
            return
        
        # Скачиваем изображение
        logger.info(f"Downloading image file: {file_info.file_path}")
        file_buffer = await message.bot.download_file(file_info.file_path)
        image_bytes = file_buffer.getvalue()
        logger.info(f"Image downloaded: {len(image_bytes)} bytes")
        
        # Определяем MIME type по расширению файла
        file_path = file_info.file_path.lower()
        if file_path.endswith('.png'):
            mime_type = 'image/png'
        elif file_path.endswith('.gif'):
            mime_type = 'image/gif'
        elif file_path.endswith('.webp'):
            mime_type = 'image/webp'
        else:
            mime_type = 'image/jpeg'  # По умолчанию JPEG
        
        # Конвертируем в base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        logger.info(f"Image converted to base64: {len(image_base64)} chars, MIME type: {mime_type}")
        
        # Проверяем размер (некоторые модели имеют лимиты)
        if len(image_base64) > 20_000_000:  # ~15MB в base64
            logger.warning(f"Image is very large: {len(image_base64)} chars, may cause issues")
        
        # Получаем историю сообщений без системного промпта для контекста
        message_history = chat_conversations[chat_id][1:] if chat_conversations[chat_id] else []
        logger.info(f"Calling LLM with model: {config.MODEL_IMAGE}")
        
        # Получаем ответ LLM с structured output
        response = await get_transaction_response_image(image_base64, message_history)
        
        # Детальное логирование ответа LLM
        logger.info(f"LLM response for image from {chat_id}: answer='{response.answer[:200]}...', transactions_count={len(response.transactions)}")
        if response.transactions:
            logger.info(f"Extracted {len(response.transactions)} transactions from image for {chat_id}: {[t.model_dump() for t in response.transactions]}")
        else:
            logger.warning(f"No transactions extracted from image for {chat_id}")
        
        # Сохраняем транзакции
        if response.transactions:
            if chat_id not in transactions:
                transactions[chat_id] = []
            transactions[chat_id].extend(response.transactions)
        
        # Рассчитываем баланс
        balance = sum(
            t.amount if t.type.value == "income" else -t.amount 
            for t in transactions.get(chat_id, [])
        )
        
        # Формируем ответ пользователю
        answer_text = response.answer
        
        # Добавляем статус транзакций
        if response.transactions:
            count = len(response.transactions)
            answer_text += f"\n\n✅ Найдено и сохранено {count} транзакция{'и' if count > 1 else ''}"
        else:
            answer_text += "\n\nℹ️ Транзакции не найдены"
        
        # Добавляем баланс
        balance_str = f"{balance:.0f}" if balance == int(balance) else f"{balance:.2f}"
        answer_text += f"\n💵 Баланс: {balance_str} руб."
        
        # Добавляем изображение в историю как текстовое описание (для контекста)
        chat_conversations[chat_id].append(
            {"role": "user", "content": "[Изображение: чек/скриншот]"}
        )
        
        # Добавляем ответ LLM в историю
        chat_conversations[chat_id].append(
            {"role": "assistant", "content": response.answer}
        )
        
        await message.answer(answer_text)
    except APIConnectionError as e:
        # Ошибка подключения к серверу (Ollama недоступен и т.д.)
        logger.error(f"Connection error for image from {chat_id}: {e}", exc_info=True)
        base_url = config.OPENAI_BASE_URL or "не указан"
        
        # Проверяем, используется ли Ollama
        is_ollama = "ollama" in base_url.lower() or ":11434" in base_url or "localhost" in base_url.lower() or any(ip in base_url for ip in ["195.", "192.", "10."])
        
        if is_ollama:
            await message.answer(
                "❌ Не удалось подключиться к Ollama серверу.\n\n"
                f"Сервер: {base_url}\n"
                f"Модель: {config.MODEL_IMAGE}\n\n"
                "Возможные причины:\n"
                "• Сервер выключен или недоступен\n"
                "• Модель не установлена\n"
                "• Проблемы с сетью\n\n"
                "💡 Решение: Переключитесь на OpenRouter\n\n"
                "Измените в .env:\n"
                "```\n"
                "OPENAI_BASE_URL=https://openrouter.ai/api/v1\n"
                "MODEL_IMAGE=meta-llama/llama-3.2-11b-vision-instruct\n"
                "```\n\n"
                "Или используйте:\n"
                "• openai/gpt-4o-mini\n"
                "• openai/gpt-4o"
            )
        else:
            await message.answer(
                f"❌ Ошибка подключения к API серверу.\n\n"
                f"Сервер: {base_url}\n"
                f"Модель: {config.MODEL_IMAGE}\n\n"
                "Проверьте:\n"
                "• Доступность сервера\n"
                "• Правильность URL в OPENAI_BASE_URL\n"
                "• Настройки сети/файрвола"
            )
    except (APIError, InternalServerError, NotFoundError) as e:
        logger.error(f"LLM API error for image from {chat_id}: {e}", exc_info=True)
        error_message = str(e).lower()
        error_details = f"Ошибка: {str(e)}"
        
        if "image input" in error_message or "vision" in error_message or "not support" in error_message:
            await message.answer(
                f"❌ Модель {config.MODEL_IMAGE} не поддерживает обработку изображений.\n\n"
                f"{error_details}\n\n"
                "Попробуйте изменить MODEL_IMAGE в .env на:\n"
                "• openai/gpt-4o-mini (рекомендуется)\n"
                "• openai/gpt-4o\n"
                "• meta-llama/llama-3.2-11b-vision-instruct"
            )
        elif "404" in error_message or "not found" in error_message:
            await message.answer(
                f"❌ Модель {config.MODEL_IMAGE} не найдена на OpenRouter.\n\n"
                f"{error_details}\n\n"
                "Проверьте правильность названия модели в .env файле."
            )
        elif "rate limit" in error_message or "quota" in error_message:
            await message.answer(
                "⏳ Превышен лимит запросов к API. Попробуйте через несколько секунд."
            )
        else:
            await message.answer(
                f"❌ Ошибка API при обработке изображения:\n{error_details}\n\n"
                "Проверьте логи бота для деталей."
            )
    except ValueError as e:
        # Ошибки валидации (например, пустой ответ от LLM)
        logger.error(f"Validation error for image from {chat_id}: {e}", exc_info=True)
        error_msg = str(e)
        if "empty response" in error_msg.lower():
            await message.answer(
                f"❌ Модель {config.MODEL_IMAGE} вернула пустой ответ.\n\n"
                "Возможные причины:\n"
                "• Модель не поддерживает обработку изображений\n"
                "• Модель не поддерживает structured output\n"
                "• Проблема с API провайдером\n\n"
                "Попробуйте изменить MODEL_IMAGE в .env на:\n"
                "• openai/gpt-4o-mini\n"
                "• openai/gpt-4o"
            )
        else:
            await message.answer(f"❌ Ошибка валидации: {error_msg}")
    except json.JSONDecodeError as e:
        # Ошибки парсинга JSON
        logger.error(f"JSON decode error for image from {chat_id}: {e}", exc_info=True)
        await message.answer(
            f"❌ Ошибка парсинга ответа от модели.\n\n"
            f"Модель вернула невалидный JSON.\n"
            f"Ошибка: {str(e)}\n\n"
            "Попробуйте другую модель или отправьте изображение еще раз."
        )
    except Exception as e:
        # Все остальные ошибки
        logger.error(f"Error processing image from {chat_id}: {e}", exc_info=True)
        error_type = type(e).__name__
        error_msg = str(e)
        
        # Формируем понятное сообщение для пользователя
        user_message = f"❌ Ошибка при обработке изображения:\n\n"
        user_message += f"Тип ошибки: {error_type}\n"
        user_message += f"Сообщение: {error_msg[:200]}\n\n"
        
        # Добавляем рекомендации в зависимости от типа ошибки
        if "connection" in error_msg.lower() or "timeout" in error_msg.lower():
            user_message += "Проблема с подключением к API. Проверьте интернет-соединение."
        elif "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower() or "401" in error_msg:
            user_message += "Ошибка аутентификации. Проверьте OPENAI_API_KEY в .env файле."
        elif "model" in error_msg.lower():
            user_message += f"Проблема с моделью {config.MODEL_IMAGE}. Попробуйте другую модель."
        else:
            user_message += "Проверьте логи бота для деталей или используйте /start для начала нового диалога."
        
        await message.answer(user_message)

@router.message(lambda message: message.voice is not None)
async def handle_voice(message: Message):
    """Обработчик голосовых сообщений."""
    chat_id = message.chat.id
    
    logger.info(f"Voice message received from {chat_id}")
    
    # Проверяем наличие настроек для транскрибации
    provider = config.TRANSCRIPTION_PROVIDER.lower()
    
    if provider == "openai":
        whisper_api_key = config.WHISPER_API_KEY
        if not whisper_api_key or whisper_api_key == "ollama" or whisper_api_key.startswith("sk-or-v1-"):
            logger.error("WHISPER_API_KEY not configured for Whisper API")
            await message.answer(
                "❌ Транскрибация голосовых сообщений недоступна.\n\n"
                "Для работы через OpenAI Whisper необходим API ключ от OpenAI.\n"
                "Добавьте в .env:\n"
                "WHISPER_API_KEY=sk-proj-... (ключ от OpenAI)\n\n"
                "Или используйте Yandex SpeechKit:\n"
                "TRANSCRIPTION_PROVIDER=yandex\n"
                "YANDEX_SPEECHKIT_API_KEY=...\n"
                "YANDEX_SPEECHKIT_FOLDER_ID=..."
            )
            return
    elif provider == "yandex":
        if not config.YANDEX_SPEECHKIT_API_KEY or not config.YANDEX_SPEECHKIT_FOLDER_ID:
            logger.error("Yandex SpeechKit not configured")
            await message.answer(
                "❌ Транскрибация голосовых сообщений недоступна.\n\n"
                "Для работы через Yandex SpeechKit добавьте в .env:\n"
                "YANDEX_SPEECHKIT_API_KEY=ваш_ключ\n"
                "YANDEX_SPEECHKIT_FOLDER_ID=ваш_folder_id"
            )
            return
    else:
        await message.answer(
            f"❌ Неизвестный провайдер транскрибации: {provider}\n\n"
            "Установите в .env:\n"
            "TRANSCRIPTION_PROVIDER=openai  # или yandex"
        )
        return
    
    try:
        # Получаем информацию о голосовом файле
        voice = message.voice
        file_info = await message.bot.get_file(voice.file_id)
        
        logger.info(f"Downloading voice file: {file_info.file_path}, duration: {voice.duration}s")
        
        # Скачиваем аудиофайл
        file_buffer = await message.bot.download_file(file_info.file_path)
        audio_bytes = file_buffer.getvalue()
        logger.info(f"Voice file downloaded: {len(audio_bytes)} bytes")
        
        # Создаем BytesIO объект для транскрибации
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = file_info.file_path or "voice.ogg"
        
        # Отправляем сообщение о начале обработки
        processing_msg = await message.answer("🎤 Распознаю голосовое сообщение...")
        
        # Транскрибируем голосовое сообщение
        transcribed_text = await transcribe_voice(audio_file, audio_file.name)
        
        logger.info(f"Transcription successful for {chat_id}: {transcribed_text[:100]}...")
        
        # Удаляем сообщение о обработке
        await processing_msg.delete()
        
        # Отправляем транскрибированный текст пользователю
        await message.answer(f"📝 Распознанный текст:\n\n{transcribed_text}")
        
        # Теперь обрабатываем транскрибированный текст как обычное текстовое сообщение
        # Инициализируем историю если её нет
        if chat_id not in chat_conversations:
            chat_conversations[chat_id] = [
                {"role": "system", "content": config.SYSTEM_PROMPT_TEXT}
            ]
        
        # Получаем историю сообщений без системного промпта для контекста
        message_history = chat_conversations[chat_id][1:] if chat_conversations[chat_id] else []
        
        # Получаем ответ LLM с structured output
        response = await get_transaction_response_text(transcribed_text, message_history)
        
        # Детальное логирование ответа LLM
        logger.info(f"LLM response for voice from {chat_id}: answer='{response.answer[:200]}...', transactions_count={len(response.transactions)}")
        if response.transactions:
            logger.info(f"Extracted {len(response.transactions)} transactions from voice for {chat_id}: {[t.model_dump() for t in response.transactions]}")
        else:
            logger.warning(f"No transactions extracted from transcribed text: '{transcribed_text}' for {chat_id}")
        
        # Сохраняем транзакции
        if response.transactions:
            if chat_id not in transactions:
                transactions[chat_id] = []
            transactions[chat_id].extend(response.transactions)
        
        # Рассчитываем баланс
        balance = sum(
            t.amount if t.type.value == "income" else -t.amount 
            for t in transactions.get(chat_id, [])
        )
        
        # Формируем ответ пользователю
        answer_text = response.answer
        
        # Добавляем статус транзакций
        if response.transactions:
            count = len(response.transactions)
            answer_text += f"\n\n✅ Найдено и сохранено {count} транзакция{'и' if count > 1 else ''}"
        else:
            answer_text += "\n\nℹ️ Транзакции не найдены"
        
        # Добавляем баланс
        balance_str = f"{balance:.0f}" if balance == int(balance) else f"{balance:.2f}"
        answer_text += f"\n💵 Баланс: {balance_str} руб."
        
        # Добавляем транскрибированный текст в историю как сообщение пользователя
        chat_conversations[chat_id].append(
            {"role": "user", "content": transcribed_text}
        )
        
        # Добавляем ответ LLM в историю
        chat_conversations[chat_id].append(
            {"role": "assistant", "content": response.answer}
        )
        
        await message.answer(answer_text)
        
    except ValueError as e:
        logger.error(f"ValueError during voice transcription for {chat_id}: {e}", exc_info=True)
        error_msg = str(e)
        if "OPENAI_API_KEY" in error_msg or "WHISPER_API_KEY" in error_msg:
            await message.answer(
                "❌ Ошибка конфигурации: API ключ не установлен для транскрибации.\n\n"
                f"{error_msg}\n\n"
                "Бот продолжает работать с текстовыми сообщениями и изображениями."
            )
        else:
            await message.answer(f"❌ Ошибка транскрибации: {error_msg}")
    except APIError as e:
        logger.error(f"OpenAI API error during voice transcription for {chat_id}: {e}", exc_info=True)
        error_message = str(e).lower()
        if "rate limit" in error_message or "quota" in error_message:
            await message.answer(
                "⏳ Превышен лимит запросов к API. Попробуйте через несколько секунд."
            )
        elif "invalid" in error_message or "format" in error_message:
            await message.answer(
                "❌ Ошибка формата аудио. Убедитесь, что отправлено голосовое сообщение."
            )
        else:
            await message.answer(
                f"❌ Ошибка API при транскрибации:\n{str(e)}\n\n"
                "Проверьте логи бота для деталей."
            )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error processing voice message from {chat_id}: {e}", exc_info=True)
        
        # Специальная обработка ошибок Yandex SpeechKit с правами доступа
        if "PermissionDenied" in error_msg or "UNAUTHORIZED" in error_msg or "resource-manager" in error_msg:
            await message.answer(
                "❌ Ошибка доступа к Yandex SpeechKit.\n\n"
                "Проблема с правами доступа сервисного аккаунта.\n"
                "Проверьте настройки в Yandex Cloud:\n"
                "• Роль 'ai.speechkit-stt.user' на уровне каталога\n"
                "• Роль 'editor' на уровне каталога\n\n"
                "Бот продолжает работать с текстовыми сообщениями и изображениями.\n"
                "Голосовые сообщения временно недоступны."
            )
        else:
            error_type = type(e).__name__
            await message.answer(
                f"❌ Ошибка при обработке голосового сообщения:\n\n"
                f"Тип: {error_type}\n"
                f"Сообщение: {error_msg[:200]}\n\n"
                "Бот продолжает работать с текстовыми сообщениями и изображениями.\n"
                "Попробуйте отправить транзакцию текстом или изображением."
            )

@router.message()
async def handle_message(message: Message):
    # Игнорируем сообщения без текста
    if not message.text:
        await message.answer("Извините, я работаю только с текстовыми сообщениями.")
        return
    
    # Проверяем длину сообщения
    if len(message.text) > MAX_MESSAGE_LENGTH:
        await message.answer(
            f"Извините, ваше сообщение слишком длинное ({len(message.text)} символов). "
            f"Максимальная длина: {MAX_MESSAGE_LENGTH} символов."
        )
        return
    
    chat_id = message.chat.id
    last_message = message.text
    
    logger.info(f"Message from {chat_id}: {last_message[:100]}...")
    
    # Инициализируем историю если её нет
    if chat_id not in chat_conversations:
        chat_conversations[chat_id] = [
            {"role": "system", "content": config.SYSTEM_PROMPT_TEXT}
        ]
    
    # Получаем историю сообщений без системного промпта для контекста
    message_history = chat_conversations[chat_id][1:] if chat_conversations[chat_id] else []
    
    try:
        # Получаем ответ LLM с structured output (извлечение транзакций только из последнего сообщения)
        response = await get_transaction_response_text(last_message, message_history)
        
        # Детальное логирование ответа LLM
        logger.info(f"LLM response for {chat_id}: answer='{response.answer[:200]}...', transactions_count={len(response.transactions)}")
        if response.transactions:
            logger.info(f"Extracted {len(response.transactions)} transactions for {chat_id}: {[t.model_dump() for t in response.transactions]}")
        else:
            logger.warning(f"No transactions extracted from message: '{last_message}' for {chat_id}")
        
        # Сохраняем транзакции
        if response.transactions:
            if chat_id not in transactions:
                transactions[chat_id] = []
            transactions[chat_id].extend(response.transactions)
        
        # Рассчитываем баланс
        balance = sum(
            t.amount if t.type.value == "income" else -t.amount 
            for t in transactions.get(chat_id, [])
        )
        
        # Формируем ответ пользователю
        answer_text = response.answer
        
        # Добавляем статус транзакций
        if response.transactions:
            count = len(response.transactions)
            answer_text += f"\n\n✅ Найдено и сохранено {count} транзакция{'и' if count > 1 else ''}"
        else:
            answer_text += "\n\nℹ️ Транзакции не найдены"
        
        # Добавляем баланс
        balance_str = f"{balance:.0f}" if balance == int(balance) else f"{balance:.2f}"
        answer_text += f"\n💵 Баланс: {balance_str} руб."
        
        # Добавляем сообщение пользователя в историю
        chat_conversations[chat_id].append(
            {"role": "user", "content": last_message}
        )
        
        # Добавляем ответ LLM в историю
        chat_conversations[chat_id].append(
            {"role": "assistant", "content": response.answer}
        )
        
        await message.answer(answer_text)
    except (APIError, InternalServerError) as e:
        logger.error(f"LLM API error for {chat_id}: {e}", exc_info=True)
        await message.answer(
            "Извините, произошла ошибка на стороне провайдера LLM. "
            "Пожалуйста, попробуйте еще раз через несколько секунд."
        )
    except Exception as e:
        logger.error(f"Error in handle_message for {chat_id}: {e}", exc_info=True)
        await message.answer(
            "Произошла ошибка при обработке вашего сообщения. "
            "Попробуйте еще раз или используйте /start для начала нового диалога."
        )

