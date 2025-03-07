import time
import requests
import threading
import os
from loguru import logger

def keep_alive_service():
    """Функция для поддержания сервиса активным через регулярные запросы"""
    app_url = os.environ.get('RENDER_EXTERNAL_URL', '')
    
    if not app_url:
        logger.warning("RENDER_EXTERNAL_URL не найден в переменных окружения. Сервис keep-alive не будет работать")
        return
    
    logger.info(f"Запущен сервис keep-alive для {app_url}")
    
    while True:
        try:
            # Отправляем запрос к корневому пути бота
            response = requests.get(app_url)
            logger.info(f"Keep-alive пинг выполнен. Статус: {response.status_code}")
        except Exception as e:
            logger.error(f"Ошибка в keep-alive сервисе: {e}")
        
        # Делаем запрос каждые 14 минут (бесплатные сервисы Render спят после 15 минут бездействия)
        time.sleep(840)

def start_keep_alive_thread():
    """Запускает keep_alive_service в отдельном потоке"""
    keep_alive_thread = threading.Thread(target=keep_alive_service, daemon=True)
    keep_alive_thread.start()
    logger.info("Запущен фоновый поток keep-alive")
    return keep_alive_thread 