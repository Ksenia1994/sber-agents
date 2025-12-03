"""
Модуль для транскрибации голосовых сообщений.
Поддерживает OpenAI Whisper API и Yandex SpeechKit.
"""
import logging
import io
import aiohttp
import base64
from openai import AsyncOpenAI
from config import config

logger = logging.getLogger(__name__)

async def transcribe_voice_openai(audio_file: io.BytesIO, filename: str = "voice.ogg") -> str:
    """Транскрибация через OpenAI Whisper API."""
    whisper_api_key = config.WHISPER_API_KEY
    
    if not whisper_api_key or whisper_api_key == "ollama" or whisper_api_key.startswith("sk-or-v1-"):
        raise ValueError(
            "WHISPER_API_KEY не установлен или неверный.\n\n"
            "Для работы с голосовыми сообщениями через OpenAI необходим API ключ от OpenAI (не от OpenRouter).\n"
            "Добавьте в .env:\n"
            "WHISPER_API_KEY=sk-proj-... (ключ от OpenAI)\n\n"
            "Или используйте Yandex SpeechKit:\n"
            "TRANSCRIPTION_PROVIDER=yandex\n"
            "YANDEX_SPEECHKIT_API_KEY=...\n"
            "YANDEX_SPEECHKIT_FOLDER_ID=..."
        )
    
    client = AsyncOpenAI(
        api_key=whisper_api_key,
        base_url="https://api.openai.com/v1"
    )
    
    logger.info(f"Starting OpenAI Whisper transcription for file: {filename}, size: {len(audio_file.getvalue())} bytes")
    
    try:
        audio_file.seek(0)
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, audio_file, "audio/ogg"),
            language="ru",
            response_format="text"
        )
        
        text = transcript if isinstance(transcript, str) else transcript.text
        logger.info(f"OpenAI Whisper transcription successful: {len(text)} characters")
        return text.strip()
    
    except Exception as e:
        logger.error(f"Error during OpenAI Whisper transcription: {e}", exc_info=True)
        raise

async def transcribe_voice_yandex(audio_file: io.BytesIO, filename: str = "voice.ogg") -> str:
    """Транскрибация через Yandex SpeechKit."""
    if not config.YANDEX_SPEECHKIT_API_KEY:
        raise ValueError(
            "YANDEX_SPEECHKIT_API_KEY не установлен в .env файле.\n\n"
            "Для работы с голосовыми сообщениями через Yandex SpeechKit добавьте в .env:\n"
            "YANDEX_SPEECHKIT_API_KEY=ваш_ключ\n"
            "YANDEX_SPEECHKIT_FOLDER_ID=ваш_folder_id"
        )
    
    if not config.YANDEX_SPEECHKIT_FOLDER_ID:
        raise ValueError(
            "YANDEX_SPEECHKIT_FOLDER_ID не установлен в .env файле.\n\n"
            "Добавьте в .env:\n"
            "YANDEX_SPEECHKIT_FOLDER_ID=ваш_folder_id"
        )
    
    logger.info(f"Starting Yandex SpeechKit transcription for file: {filename}, size: {len(audio_file.getvalue())} bytes")
    
    try:
        audio_file.seek(0)
        audio_data = audio_file.read()
        
        # Конвертируем в base64
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        # Yandex SpeechKit API endpoint
        url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
        
        headers = {
            "Authorization": f"Api-Key {config.YANDEX_SPEECHKIT_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # При использовании API ключа folderId НЕ нужно передавать
        # API ключ автоматически привязан к каталогу, где создан сервисный аккаунт
        data = {
            "format": "oggopus",  # Telegram использует OGG Opus
            "lang": "ru-RU",  # Русский язык
            "sampleRateHertz": 48000,  # Стандартная частота для Telegram
            "data": audio_base64  # Аудио в base64
        }
        
        # НЕ передаем folderId - при использовании API ключа он определяется автоматически
        
        # Отправляем запрос
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Yandex SpeechKit API error {response.status}: {error_text}")
                
                result = await response.json()
                
                if "result" not in result:
                    raise Exception(f"Unexpected response from Yandex SpeechKit: {result}")
                
                text = result["result"]
                logger.info(f"Yandex SpeechKit transcription successful: {len(text)} characters")
                return text.strip()
    
    except Exception as e:
        logger.error(f"Error during Yandex SpeechKit transcription: {e}", exc_info=True)
        raise

async def transcribe_voice(audio_file: io.BytesIO, filename: str = "voice.ogg") -> str:
    """
    Транскрибирует голосовое сообщение.
    Использует провайдера, указанного в TRANSCRIPTION_PROVIDER.
    
    Args:
        audio_file: BytesIO объект с аудио данными
        filename: Имя файла (используется для определения формата)
    
    Returns:
        str: Транскрибированный текст
    
    Raises:
        Exception: При ошибках транскрибации
    """
    provider = config.TRANSCRIPTION_PROVIDER.lower()
    
    if provider == "yandex":
        return await transcribe_voice_yandex(audio_file, filename)
    elif provider == "openai":
        return await transcribe_voice_openai(audio_file, filename)
    else:
        raise ValueError(
            f"Неизвестный провайдер транскрибации: {provider}\n\n"
            "Установите в .env:\n"
            "TRANSCRIPTION_PROVIDER=openai  # или yandex"
        )

