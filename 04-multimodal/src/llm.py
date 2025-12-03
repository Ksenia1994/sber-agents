import logging
from openai import AsyncOpenAI
from openai import APIError, InternalServerError
from config import config
from models import TransactionResponse

logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    api_key=config.OPENAI_API_KEY,
    base_url=config.OPENAI_BASE_URL
)

async def get_transaction_response_text(
    last_message: str,
    message_history: list[dict]
) -> TransactionResponse:
    try:
        response = await client.chat.completions.create(
            model=config.MODEL_TEXT,
            messages=[
                {"role": "system", "content": config.SYSTEM_PROMPT_TEXT},
                *message_history[-10:],  # последние 10 сообщений для контекста
                {"role": "user", "content": last_message}
            ],
            response_format={"type": "json_schema", "json_schema": {
                "name": "transaction_response",
                "schema": TransactionResponse.model_json_schema(),
                "strict": True
            }}
        )
        raw_content = response.choices[0].message.content
        logger.info(f"Raw LLM response (length: {len(raw_content) if raw_content else 0}): {raw_content[:1000] if raw_content else 'EMPTY'}")
        
        # Проверяем что ответ не пустой
        if not raw_content or not raw_content.strip():
            logger.error("LLM returned empty response")
            raise ValueError("LLM returned empty response")
        
        try:
            # Парсим JSON ответ
            import json
            parsed_json = json.loads(raw_content)
            
            # Обрабатываем случай, когда поле transactions отсутствует
            if "transactions" not in parsed_json:
                logger.warning("Field 'transactions' missing in LLM response, adding empty list")
                parsed_json["transactions"] = []
            
            # Убеждаемся, что answer есть
            if "answer" not in parsed_json:
                logger.warning("Field 'answer' missing in LLM response, adding default")
                parsed_json["answer"] = "Обработал ваше сообщение."
            
            parsed_response = TransactionResponse.model_validate(parsed_json)
            logger.info(f"Successfully parsed TransactionResponse: transactions={len(parsed_response.transactions)}")
            return parsed_response
        except json.JSONDecodeError as json_error:
            # Детальное логирование проблемы с JSON
            logger.error(f"Failed to parse JSON from LLM response: {json_error}")
            logger.error(f"Full response content ({len(raw_content)} chars): {raw_content}")
            logger.error(f"First 200 chars: {raw_content[:200]}")
            logger.error(f"Last 200 chars: {raw_content[-200:]}")
            raise
        except Exception as parse_error:
            # Детальное логирование для других ошибок парсинга
            logger.error(f"Failed to parse LLM response as TransactionResponse: {parse_error}")
            logger.error(f"Full response content ({len(raw_content)} chars): {raw_content}")
            logger.error(f"First 200 chars: {raw_content[:200]}")
            logger.error(f"Last 200 chars: {raw_content[-200:]}")
            raise
    except (APIError, InternalServerError) as e:
        logger.error(f"LLM API error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error calling LLM: {e}", exc_info=True)
        raise

async def get_transaction_response_image(
    image_base64: str,
    message_history: list[dict]
) -> TransactionResponse:
    if not config.MODEL_IMAGE:
        raise ValueError("MODEL_IMAGE not configured in .env file")
    
    if not config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not configured in .env file")
    
    try:
        schema = TransactionResponse.model_json_schema()
        logger.info(f"Using model: {config.MODEL_IMAGE}, base_url: {config.OPENAI_BASE_URL}")
        logger.info(f"API Key present: {bool(config.OPENAI_API_KEY)}")
        
        # Логируем размер изображения в более понятном формате
        image_size_bytes = len(image_base64.encode('utf-8')) * 3 // 4  # примерная оценка
        image_size_kb = image_size_bytes / 1024
        logger.info(f"Image size: ~{image_size_kb:.1f} KB ({len(image_base64)} base64 chars)")
        logger.info(f"Message history length: {len(message_history)} messages")
        
        # Для GPT-4o моделей используем structured output, для других - json_object или обычный режим
        logger.info("Attempting to call vision model with image...")
        is_gpt4o = "gpt-4o" in config.MODEL_IMAGE.lower() or "gpt-4" in config.MODEL_IMAGE.lower()
        
        try:
            if is_gpt4o:
                # Для GPT-4o используем structured output (json_schema)
                logger.info("Using structured output (json_schema) for GPT-4o model")
                response = await client.chat.completions.create(
                    model=config.MODEL_IMAGE,
                    messages=[
                        {"role": "system", "content": config.SYSTEM_PROMPT_IMAGE},
                        *message_history[-10:],  # последние 10 сообщений для контекста
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}", "detail": "high"}},
                                {"type": "text", "text": "Извлеки транзакции из этого изображения."}
                            ]
                        }
                    ],
                    response_format={"type": "json_schema", "json_schema": {
                        "name": "transaction_response",
                        "schema": schema,
                        "strict": True
                    }}
                )
                logger.info("Successfully called GPT-4o model with structured output")
            else:
                # Для других моделей пробуем json_object
                logger.info("Using json_object format for non-GPT-4o model")
                response = await client.chat.completions.create(
                    model=config.MODEL_IMAGE,
                    messages=[
                        {"role": "system", "content": config.SYSTEM_PROMPT_IMAGE + "\n\nВАЖНО: Отвечай ТОЛЬКО валидным JSON объектом без дополнительного текста. Формат: {\"answer\": \"текст\", \"transactions\": [...]}"},
                        *message_history[-10:],  # последние 10 сообщений для контекста
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}", "detail": "high"}},
                                {"type": "text", "text": "Извлеки транзакции из этого изображения. Ответь ТОЛЬКО валидным JSON в формате: {\"answer\": \"текст\", \"transactions\": [...]}. Не добавляй никакого текста до или после JSON."}
                            ]
                        }
                    ],
                    response_format={"type": "json_object"}
                )
                logger.info("Successfully called model with json_object format")
        except (APIError, InternalServerError) as e:
            # Если json_object не поддерживается, пробуем без response_format
            error_msg = str(e).lower()
            logger.warning(f"json_object format not supported, trying without response_format: {e}")
            if "json_object" in error_msg or "response_format" in error_msg or "not supported" in error_msg:
                try:
                    # Fallback: используем обычный режим без response_format
                    response = await client.chat.completions.create(
                        model=config.MODEL_IMAGE,
                        messages=[
                            {"role": "system", "content": config.SYSTEM_PROMPT_IMAGE + "\n\nВАЖНО: Всегда отвечай ТОЛЬКО валидным JSON объектом с полями 'answer' (строка) и 'transactions' (массив объектов транзакций). Не добавляй никакого текста до или после JSON. Не используй markdown code blocks."},
                            *message_history[-10:],
                            {
                                "role": "user",
                                "content": [
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                                    {"type": "text", "text": "Извлеки транзакции из этого изображения. Ответь ТОЛЬКО валидным JSON в формате: {\"answer\": \"текст\", \"transactions\": [...]}. Не добавляй никакого текста до или после JSON."}
                                ]
                            }
                        ]
                    )
                    logger.info("Successfully called model without response_format")
                except Exception as e2:
                    logger.error(f"Failed to call model even without response_format: {e2}")
                    raise
            else:
                raise
        
        # Логируем информацию о response объекте
        logger.info(f"Response received. Choices count: {len(response.choices)}")
        if response.choices:
            choice = response.choices[0]
            logger.info(f"Finish reason: {choice.finish_reason}")
            logger.info(f"Message role: {choice.message.role}")
            
            # Для structured output ответ может быть в другом формате
            raw_content = choice.message.content
            if raw_content:
                logger.info(f"Raw LLM response for image (length: {len(raw_content)}): {raw_content[:500]}...")
            else:
                logger.warning("Response content is None or empty")
                # Попробуем получить ответ из другого места (для некоторых моделей)
                if hasattr(choice.message, 'refusal'):
                    logger.warning(f"Model refusal: {choice.message.refusal}")
                raise ValueError("LLM returned empty response")
        else:
            logger.error("No choices in response")
            raise ValueError("LLM returned no choices")
        
        # Проверяем что ответ не пустой
        if not raw_content or not raw_content.strip():
            logger.error("LLM returned empty response for image")
            logger.error(f"Response object details: {response}")
            logger.error(f"Finish reason: {response.choices[0].finish_reason if response.choices else 'no choices'}")
            raise ValueError("LLM returned empty response")
        
        try:
            # Парсим ответ модели
            import json
            import re
            import ast
            
            logger.info(f"Attempting to parse response. First 500 chars: {raw_content[:500]}")
            
            # Сначала пытаемся распарсить весь ответ как JSON
            parsed_json = None
            try:
                parsed_json = json.loads(raw_content.strip())
                logger.info("Successfully parsed entire response as JSON")
            except json.JSONDecodeError:
                # Если не получилось, пытаемся найти JSON объект внутри текста
                json_obj_match = re.search(r'\{[^{}]*(?:"transactions"|"answer")[^{}]*\}', raw_content, re.DOTALL)
                if json_obj_match:
                    json_str = json_obj_match.group(0)
                    logger.info(f"Found JSON object in response: {json_str[:200]}...")
                    try:
                        parsed_json = json.loads(json_str)
                        logger.info("Successfully parsed JSON object from text")
                    except json.JSONDecodeError:
                        logger.warning("Could not parse JSON object, will try Python list")
                        parsed_json = None
            
            if not parsed_json:
                # Пытаемся найти Python-список (с одинарными кавычками)
                # Ищем список, который начинается с [ и заканчивается на ]
                # Используем жадный поиск, чтобы захватить весь список
                list_match = re.search(r'\[.*?\]', raw_content, re.DOTALL)
                if not list_match:
                    # Если не нашли, пробуем более широкий поиск (может быть многострочный)
                    list_match = re.search(r'\[[\s\S]*?\]', raw_content)
                if list_match:
                    logger.info("Found Python list in response, converting to JSON format")
                    python_list_str = list_match.group(0)
                    
                    # Извлекаем текст перед списком как answer
                    text_before = raw_content[:list_match.start()].strip()
                    if text_before:
                        # Убираем лишние символы и берем первые 200 символов
                        answer_text = re.sub(r'\s+', ' ', text_before)[:200]
                    else:
                        answer_text = "Обработал изображение."
                    
                    try:
                        # Парсим Python-список используя ast.literal_eval
                        python_list = ast.literal_eval(python_list_str)
                        logger.info(f"Parsed Python list with {len(python_list)} transactions")
                        
                        # Конвертируем в JSON-совместимый формат и валидируем
                        transactions_json = []
                        for item in python_list:
                            tx = {}
                            
                            # Обрабатываем обязательные поля
                            if 'date' in item:
                                tx['date'] = item['date']
                            else:
                                logger.warning(f"Transaction missing 'date' field, skipping: {item}")
                                continue
                            
                            # Обрабатываем time (может быть строка или None)
                            if 'time' in item and item['time']:
                                time_str = str(item['time'])
                                # Пытаемся распарсить время (может быть '16:44' или '16:44:00')
                                if ':' in time_str:
                                    parts = time_str.split(':')
                                    if len(parts) >= 2:
                                        try:
                                            hours = int(parts[0])
                                            minutes = int(parts[1])
                                            seconds = int(parts[2]) if len(parts) > 2 else 0
                                            # Создаем объект time для Pydantic
                                            from datetime import time as time_class
                                            # Оставляем как строку - валидатор в модели преобразует
                                            tx['time'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                                        except (ValueError, IndexError, TypeError):
                                            tx['time'] = None
                                    else:
                                        tx['time'] = None
                                else:
                                    tx['time'] = None
                            else:
                                tx['time'] = None
                            
                            # Обрабатываем type
                            if 'type' in item:
                                tx_type = str(item['type']).lower()
                                if tx_type in ['income', 'expense']:
                                    tx['type'] = tx_type
                                else:
                                    logger.warning(f"Invalid transaction type '{tx_type}', defaulting to 'expense'")
                                    tx['type'] = 'expense'
                            else:
                                tx['type'] = 'expense'
                            
                            # Обрабатываем amount
                            if 'amount' in item:
                                try:
                                    amount = float(item['amount'])
                                    if amount > 0:
                                        tx['amount'] = amount
                                    else:
                                        logger.warning(f"Invalid amount {amount}, skipping transaction")
                                        continue
                                except (ValueError, TypeError):
                                    logger.warning(f"Could not convert amount '{item.get('amount')}' to float, skipping")
                                    continue
                            else:
                                logger.warning(f"Transaction missing 'amount' field, skipping: {item}")
                                continue
                            
                            # Обрабатываем frequency (маппинг неправильных значений)
                            if 'frequency' in item:
                                freq = str(item['frequency']).lower()
                                # Маппинг неправильных значений
                                freq_mapping = {
                                    'daily': 'daily',
                                    'periodic': 'periodic',
                                    'one_time': 'one_time',
                                    'weekly': 'periodic',
                                    'monthly': 'periodic',
                                    'yearly': 'periodic',
                                    'other': 'one_time',
                                    'unknown': 'one_time'
                                }
                                tx['frequency'] = freq_mapping.get(freq, 'one_time')
                            else:
                                tx['frequency'] = 'one_time'
                            
                            # Обрабатываем category (исправляем неправильные значения)
                            if 'category' in item:
                                category = str(item['category']).lower()
                                # Маппинг категорий
                                category_mapping = {
                                    'salary': 'другие',  # зарплата не входит в стандартные категории
                                    'unknown': 'другие',
                                    'other': 'другие'
                                }
                                tx['category'] = category_mapping.get(category, category)
                            else:
                                tx['category'] = 'другие'
                            
                            # Обрабатываем description
                            if 'description' in item:
                                tx['description'] = str(item['description']) if item['description'] else ""
                            else:
                                tx['description'] = ""
                            
                            transactions_json.append(tx)
                        
                        # Создаем правильный JSON объект
                        parsed_json = {
                            "answer": answer_text,
                            "transactions": transactions_json
                        }
                        logger.info(f"Created JSON object with {len(transactions_json)} transactions")
                    except (ValueError, SyntaxError) as e:
                        logger.warning(f"Failed to parse Python list: {e}, trying regex extraction")
                        # Fallback: пытаемся извлечь данные через regex
                        parsed_json = {
                            "answer": answer_text if text_before else "Обработал изображение.",
                            "transactions": []
                        }
                else:
                    # Если ничего не найдено, пытаемся парсить весь текст как JSON
                    json_str = raw_content.strip()
                    
                    # Убираем markdown code blocks если есть
                    if json_str.startswith('```'):
                        json_str = re.sub(r'^```(?:json)?\s*\n', '', json_str)
                        json_str = re.sub(r'\n```\s*$', '', json_str)
                    
                    try:
                        parsed_json = json.loads(json_str)
                    except json.JSONDecodeError:
                        # Если не получилось, создаем пустой ответ
                        logger.warning("Could not parse response as JSON or Python list, creating empty response")
                        parsed_json = {
                            "answer": raw_content[:200] if raw_content else "Не удалось обработать изображение.",
                            "transactions": []
                        }
            
            # Обрабатываем случай, когда поле transactions отсутствует
            if "transactions" not in parsed_json:
                logger.warning("Field 'transactions' missing in LLM response, adding empty list")
                parsed_json["transactions"] = []
            
            # Убеждаемся, что answer есть
            if "answer" not in parsed_json:
                logger.warning("Field 'answer' missing in LLM response, adding default")
                parsed_json["answer"] = "Обработал изображение."
            
            # НЕ преобразуем время вручную - валидатор в модели Transaction сделает это автоматически
            # Просто убеждаемся, что формат времени правильный (HH:MM:SS или HH:MM)
            for tx in parsed_json["transactions"]:
                if "time" in tx and tx["time"] is not None:
                    if isinstance(tx["time"], str):
                        # Проверяем и форматируем время в стандартный формат
                        time_str = tx["time"]
                        if ':' in time_str:
                            parts = time_str.split(':')
                            if len(parts) >= 2:
                                try:
                                    hours = int(parts[0])
                                    minutes = int(parts[1])
                                    seconds = int(parts[2]) if len(parts) > 2 else 0
                                    # Проверяем валидность значений
                                    if 0 <= hours < 24 and 0 <= minutes < 60 and 0 <= seconds < 60:
                                        # Форматируем в стандартный формат HH:MM:SS
                                        tx["time"] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                                        logger.debug(f"Formatted time string: {tx['time']}")
                                    else:
                                        logger.warning(f"Invalid time values: {time_str}, setting to None")
                                        tx["time"] = None
                                except (ValueError, IndexError, TypeError) as e:
                                    logger.warning(f"Could not parse time '{time_str}': {e}, setting to None")
                                    tx["time"] = None
                            else:
                                tx["time"] = None
                        else:
                            tx["time"] = None
                    # Если это уже объект time или другой тип, оставляем как есть - валидатор разберется
                # Если time отсутствует или None, оставляем как есть
            
            # Логируем транзакции перед валидацией
            for i, tx in enumerate(parsed_json['transactions']):
                logger.info(f"Transaction {i} before validation: date={tx.get('date')}, time={tx.get('time')}, time_type={type(tx.get('time'))}")
                # Убеждаемся, что время - это строка, а не объект time
                if 'time' in tx and tx['time'] is not None:
                    if not isinstance(tx['time'], str):
                        logger.warning(f"Time is not a string: {type(tx['time'])}, converting to string")
                        if hasattr(tx['time'], 'strftime'):
                            tx['time'] = tx['time'].strftime("%H:%M:%S")
                        else:
                            tx['time'] = str(tx['time'])
            
            # Время теперь хранится как строка, не нужно преобразовывать
            # Просто убеждаемся, что формат правильный (HH:MM:SS)
            for tx in parsed_json['transactions']:
                if 'time' in tx and tx['time'] is not None:
                    if isinstance(tx['time'], str):
                        # Проверяем и форматируем время
                        time_str = tx['time']
                        if ':' in time_str:
                            parts = time_str.split(':')
                            if len(parts) >= 2:
                                try:
                                    hours = int(parts[0])
                                    minutes = int(parts[1])
                                    seconds = int(parts[2]) if len(parts) > 2 else 0
                                    if 0 <= hours < 24 and 0 <= minutes < 60 and 0 <= seconds < 60:
                                        tx['time'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                                        logger.debug(f"Formatted time string: {tx['time']}")
                                    else:
                                        logger.warning(f"Invalid time values: {time_str}, setting to None")
                                        tx['time'] = None
                                except (ValueError, IndexError, TypeError):
                                    tx['time'] = None
                            else:
                                tx['time'] = None
                        else:
                            tx['time'] = None
                    else:
                        # Если это не строка, преобразуем в строку или устанавливаем None
                        logger.warning(f"Time is not a string: {type(tx['time'])}, converting")
                        if hasattr(tx['time'], 'strftime'):
                            tx['time'] = tx['time'].strftime("%H:%M:%S")
                        else:
                            tx['time'] = None
            
            # Используем model_validate - время хранится как строка
            parsed_response = TransactionResponse.model_validate(parsed_json)
            logger.info(f"Successfully parsed TransactionResponse for image: transactions={len(parsed_response.transactions)}")
            return parsed_response
        except json.JSONDecodeError as json_error:
            # Детальное логирование проблемы с JSON
            logger.error(f"Failed to parse JSON from LLM response for image: {json_error}")
            logger.error(f"Full response content ({len(raw_content)} chars): {raw_content}")
            logger.error(f"First 200 chars: {raw_content[:200]}")
            logger.error(f"Last 200 chars: {raw_content[-200:]}")
            raise
        except Exception as parse_error:
            # Детальное логирование для других ошибок парсинга
            logger.error(f"Failed to parse LLM response as TransactionResponse for image: {parse_error}")
            logger.error(f"Full response content ({len(raw_content)} chars): {raw_content}")
            logger.error(f"First 200 chars: {raw_content[:200]}")
            logger.error(f"Last 200 chars: {raw_content[-200:]}")
            raise
    except (APIError, InternalServerError) as e:
        logger.error(f"LLM API error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error calling LLM: {e}", exc_info=True)
        raise

