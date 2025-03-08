import telebot
from telebot import types, apihelper
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage
import sqlite3
import time
import random
import os
import logging
import re
import sys
import socket
import atexit
from dotenv import load_dotenv
import signal
import traceback
from keep_alive import start_keep_alive_thread

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Включаем middleware
apihelper.ENABLE_MIDDLEWARE = True

# Состояния пользователя
class UserStates:
    START = 'start'
    WAITING_NAME = 'waiting_name'
    WAITING_MEDIA = 'waiting_media'
    PREVIEW_SUBMISSION = 'preview_submission'
    WAITING_VOTES_COUNT = 'waiting_votes_count'
    WAITING_TOURNAMENT_TIME = 'waiting_tournament_time'

# Инициализация бота
token = os.environ.get('TOKEN', '8104692415:AAEFJiYdW85sXaAa4PFd-uOEcJZIBQfd31Q')
bot = telebot.TeleBot(token)

# Словари для хранения данных пользователей
user_states = {}
user_data = {}

# Константы
ADMIN_ID = 1758948212  # Замените на ваш ID администратора

# Список разрешенных пользователей (можно настроить в админ-панели)
ALLOWED_USERS = [ADMIN_ID]  # По умолчанию только админ

def create_admin_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("🎭 Начать голосование")
    btn2 = types.KeyboardButton("🏆 Топ участниц")
    btn3 = types.KeyboardButton("➕ Предложить участницу")
    btn_admin = types.KeyboardButton("👑 Админ-панель")
    btn_help = types.KeyboardButton("🔧 Сообщить о поломке")
    markup.row(btn1)
    markup.row(btn2, btn3)
    markup.row(btn_admin)
    markup.row(btn_help)
    return markup

def create_user_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("🎭 Начать голосование")
    btn2 = types.KeyboardButton("🏆 Топ участниц")
    btn3 = types.KeyboardButton("➕ Предложить участницу")
    btn_help = types.KeyboardButton("🔧 Сообщить о поломке")
    markup.row(btn1)
    markup.row(btn2, btn3)
    markup.row(btn_help)
    return markup

# Вспомогательные функции
def get_user_state(user_id):
    return user_states.get(user_id, UserStates.START)

def set_user_state(user_id, state):
    user_states[user_id] = state

def init_db():
    conn = sqlite3.connect('facemash.db')
    c = conn.cursor()
    
    # Создаем таблицу для предложений
    c.execute('''
        CREATE TABLE IF NOT EXISTS suggestions
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         name TEXT NOT NULL,
         file_id TEXT NOT NULL,
         media_type TEXT NOT NULL,
         suggested_by INTEGER NOT NULL,
         status TEXT DEFAULT 'pending',
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    ''')
    
    # Создаем таблицу для фотографий
    c.execute('''
        CREATE TABLE IF NOT EXISTS photos
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         name TEXT NOT NULL,
         file_id TEXT NOT NULL,
         approved INTEGER DEFAULT 0,
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    ''')
    
    # Проверяем наличие столбца media_type в таблице photos
    try:
        c.execute("SELECT media_type FROM photos LIMIT 1")
    except sqlite3.OperationalError:
        # Столбец не существует, добавляем его
        logger.info("Добавление столбца media_type в таблицу photos")
        c.execute("ALTER TABLE photos ADD COLUMN media_type TEXT DEFAULT 'photo'")
        logger.info("Столбец media_type добавлен успешно")
    
    # Проверяем наличие столбца votes в таблице photos
    try:
        c.execute("SELECT votes FROM photos LIMIT 1")
    except sqlite3.OperationalError:
        # Столбец не существует, добавляем его
        logger.info("Добавление столбца votes в таблицу photos")
        c.execute("ALTER TABLE photos ADD COLUMN votes INTEGER DEFAULT 0")
        logger.info("Столбец votes добавлен успешно")
    
    # Создаем таблицу для голосов
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_votes
        (user_id INTEGER NOT NULL,
         photo_id INTEGER NOT NULL,
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         PRIMARY KEY (user_id, photo_id))
    ''')
    
    # Создаем таблицу для настроек турнира
    c.execute('''
        CREATE TABLE IF NOT EXISTS tournament_settings
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         required_votes INTEGER NOT NULL,
         tournament_duration INTEGER NOT NULL,
         is_active INTEGER DEFAULT 0,
         current_tournament_start TIMESTAMP,
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    ''')
    
    # Обновляем количество голосов до 15 для всех активных турниров
    try:
        # Проверяем, есть ли активные турниры с required_votes = 100
        c.execute("SELECT id FROM tournament_settings WHERE is_active = 1 AND required_votes = 100")
        if c.fetchone():
            logger.info("Обновление количества голосов до 15 для активных турниров")
            c.execute("UPDATE tournament_settings SET required_votes = 15 WHERE is_active = 1 AND required_votes = 100")
            logger.info(f"Обновлено записей: {c.rowcount}")
    except Exception as e:
        logger.error(f"Ошибка при обновлении количества голосов: {e}")
    
    conn.commit()
    conn.close()
    
    logger.info("База данных инициализирована")

@bot.message_handler(commands=['propose'])
def start_proposal(message):
    try:
        logger.info(f"Пользователь {message.from_user.id} начал предложение участницы")
        
        user_id = message.from_user.id
        
        # Проверяем подписку на канал
        if not check_subscription(user_id):
            markup = types.InlineKeyboardMarkup()
            channel_btn = types.InlineKeyboardButton("Подписаться на канал", url="https://t.me/Simpatia_Liven57")
            check_btn = types.InlineKeyboardButton("✅ Проверить подписку", callback_data="check_subscription")
            markup.add(channel_btn)
            markup.add(check_btn)
            
            bot.reply_to(
                message,
                "⛔ Для использования бота необходимо подписаться на канал @Simpatia_Liven57",
                reply_markup=markup
            )
            return
            
        # Проверяем доступ пользователя
        if user_id not in ALLOWED_USERS:
            bot.reply_to(message, "⛔ У вас нет доступа к боту. Обратитесь к администратору.")
            return
        
        # Проверяем, не находится ли пользователь уже в процессе предложения
        if get_user_state(user_id) != UserStates.START:
            bot.reply_to(message, "У вас уже есть активный процесс предложения. Пожалуйста, завершите его или отмените командой /cancel")
            return
            
        # Устанавливаем состояние ожидания имени
        set_user_state(user_id, UserStates.WAITING_NAME)
        user_data[user_id] = {}
        
        # Создаем клавиатуру с кнопкой отмены
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        cancel_btn = types.KeyboardButton("❌ Отмена")
        markup.add(cancel_btn)
        
        bot.reply_to(
            message,
            "Введите имя участницы:",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка в start_proposal: {e}")
        bot.reply_to(message, "Произошла ошибка при начале предложения")
        
@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == UserStates.WAITING_NAME)
def handle_name(message):
    try:
        user_id = message.from_user.id
        
        # Проверяем подписку на канал перед любым действием
        if not check_subscription(user_id):
            send_subscription_message(message.chat.id)
            return
            
        # Если пользователь подписан, добавляем его в список разрешенных
        if user_id not in ALLOWED_USERS:
            ALLOWED_USERS.append(user_id)
            
        name = message.text.strip()
        
        # Проверяем отмену
        if name.lower() == "❌ отмена":
            cancel_proposal(message)
            return
            
        # Проверяем длину имени
        if len(name) < 2 or len(name) > 50:
            bot.send_message(message.chat.id, "Имя должно быть от 2 до 50 символов. Попробуйте еще раз:")
            return
            
        # Проверяем на запрещенные символы (исправленное регулярное выражение)
        if not re.match(r"^[а-яА-ЯёЁa-zA-Z0-9\s-]+$", name, re.UNICODE):
            bot.reply_to(message, "Имя может содержать только буквы, цифры, пробелы и дефис. Попробуйте еще раз:")
            return
            
        # Сохраняем имя и переходим к ожиданию медиа
        user_data[user_id]['name'] = name
        set_user_state(user_id, UserStates.WAITING_MEDIA)
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        cancel_btn = types.KeyboardButton("❌ Отмена")
        markup.add(cancel_btn)
        
        bot.reply_to(
            message,
            "Отправьте фото или видео участницы:",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка в handle_name: {e}")
        bot.reply_to(message, "Произошла ошибка при обработке имени")
        
@bot.message_handler(content_types=['photo', 'video'], func=lambda message: get_user_state(message.from_user.id) == UserStates.WAITING_MEDIA)
def handle_media(message):
    try:
        user_id = message.from_user.id
        logging.info(f"Обработка медиа от пользователя {user_id}")
        
        # Проверяем подписку на канал перед любым действием
        if not check_subscription(user_id):
            send_subscription_message(message.chat.id)
            return
            
        # Если пользователь подписан, добавляем его в список разрешенных
        if user_id not in ALLOWED_USERS:
            ALLOWED_USERS.append(user_id)
        
        # Проверяем, существуют ли данные пользователя
        if user_id not in user_data:
            logging.warning(f"Данные пользователя {user_id} отсутствуют")
            user_data[user_id] = {}
            
        # Проверяем наличие имени
        if 'name' not in user_data[user_id]:
            logging.warning(f"Отсутствует имя в данных пользователя {user_id}")
            bot.send_message(message.chat.id, "Произошла ошибка: данные о имени отсутствуют. Пожалуйста, начните заново с команды /propose")
            set_user_state(user_id, UserStates.START)
            return
        
        # Получаем file_id и тип медиа
        if message.content_type == 'photo':
            if not message.photo or len(message.photo) == 0:
                logger.warning(f"Получено пустое фото от пользователя {user_id}")
                bot.reply_to(message, "Не удалось получить фото. Пожалуйста, попробуйте еще раз.")
                return
                
            file_id = message.photo[-1].file_id
            media_type = 'photo'
            logger.info(f"Получено фото от пользователя {user_id}, file_id: {file_id}")
        else:  # video
            if not hasattr(message, 'video') or not message.video:
                logger.warning(f"Получено пустое видео от пользователя {user_id}")
                bot.reply_to(message, "Не удалось получить видео. Пожалуйста, попробуйте еще раз.")
                return
                
            file_id = message.video.file_id
            media_type = 'video'
            logger.info(f"Получено видео от пользователя {user_id}, file_id: {file_id}")
            
        # Сохраняем информацию о медиа
        user_data[user_id]['file_id'] = file_id
        user_data[user_id]['media_type'] = media_type
        
        # Создаем превью предложения
        name = user_data[user_id]['name']
        
        # Создаем клавиатуру для превью
        markup = types.InlineKeyboardMarkup(row_width=2)
        edit_name_btn = types.InlineKeyboardButton("✏️ Изменить имя", callback_data="edit_name")
        edit_media_btn = types.InlineKeyboardButton("🖼 Изменить медиа", callback_data="edit_media")
        send_btn = types.InlineKeyboardButton("✅ Отправить", callback_data="send_proposal")
        cancel_btn = types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_proposal")
        
        markup.add(edit_name_btn, edit_media_btn)
        markup.add(send_btn, cancel_btn)
        
        caption = f"📝 Предварительный просмотр:\n\n👤 Имя: {name}\n📎 Тип медиа: {'Фото' if media_type == 'photo' else 'Видео'}"
        
        try:
            # Удаляем предыдущее превью, если оно было
            if 'preview_message_id' in user_data[user_id]:
                try:
                    bot.delete_message(message.chat.id, user_data[user_id]['preview_message_id'])
                except Exception as del_err:
                    logger.warning(f"Не удалось удалить предыдущее превью: {del_err}")
            
            # Отправляем новое превью
            sent_msg = None
            if media_type == 'photo':
                try:
                    sent_msg = bot.send_photo(message.chat.id, file_id, caption=caption, reply_markup=markup)
                except telebot.apihelper.ApiException as api_err:
                    logger.error(f"Ошибка API при отправке фото: {api_err}")
                    bot.reply_to(message, "Не удалось отправить фото. Возможно, формат не поддерживается.")
                    return
            else:
                try:
                    sent_msg = bot.send_video(message.chat.id, file_id, caption=caption, reply_markup=markup)
                except telebot.apihelper.ApiException as api_err:
                    logger.error(f"Ошибка API при отправке видео: {api_err}")
                    bot.reply_to(message, "Не удалось отправить видео. Возможно, формат не поддерживается или размер слишком большой.")
                    return
                
            if sent_msg:
                # Сохраняем ID сообщения с превью для возможности его обновления
                user_data[user_id]['preview_message_id'] = sent_msg.message_id
            else:
                logger.error(f"Не удалось отправить превью - sent_msg is None")
                bot.reply_to(message, "Не удалось создать превью. Пожалуйста, попробуйте еще раз.")
                return
            
        except telebot.apihelper.ApiException as api_err:
            logger.error(f"Ошибка API при отправке превью: {api_err}")
            bot.reply_to(message, "Не удалось отправить превью. Проверьте формат медиа и попробуйте еще раз.")
            return
        except Exception as gen_err:
            logger.error(f"Неизвестная ошибка при отправке превью: {gen_err}")
            bot.reply_to(message, "Произошла ошибка при создании превью. Пожалуйста, попробуйте еще раз.")
            return
            
        # Убираем клавиатуру с кнопкой отмены
        markup = types.ReplyKeyboardRemove()
        bot.send_message(message.chat.id, "👆 Проверьте правильность данных", reply_markup=markup)
        
        # Обновляем состояние
        set_user_state(user_id, UserStates.PREVIEW_SUBMISSION)
        
    except Exception as e:
        logger.error(f"Ошибка в handle_media: {e}")
        bot.reply_to(message, "Произошла ошибка при обработке медиа. Пожалуйста, попробуйте еще раз или обратитесь к администратору.")
        # Сбрасываем состояние пользователя и очищаем данные
        try:
            set_user_state(message.from_user.id, UserStates.START)
            user_data.pop(message.from_user.id, None)
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data in ["edit_name", "edit_media", "send_proposal", "cancel_proposal"])
def handle_preview_buttons(call):
    try:
        user_id = call.from_user.id
        logging.info(f"Обработка нажатия кнопки {call.data} от пользователя {user_id}")
        
        # Проверяем подписку на канал перед любым действием
        if not check_subscription(user_id):
            bot.answer_callback_query(call.id, "⛔ Для использования бота необходимо подписаться на канал!")
            send_subscription_message(call.message.chat.id)
            return
            
        # Если пользователь подписан, добавляем его в список разрешенных
        if user_id not in ALLOWED_USERS:
            ALLOWED_USERS.append(user_id)
        
        # Проверяем наличие данных пользователя
        if user_id not in user_data:
            logging.warning(f"Данные пользователя {user_id} отсутствуют при нажатии кнопки {call.data}")
            bot.answer_callback_query(call.id, "Ошибка: данные устарели. Начните заново с команды /propose")
            return
            
        if call.data == "edit_name":
            # Возвращаемся к вводу имени
            set_user_state(user_id, UserStates.WAITING_NAME)
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            cancel_btn = types.KeyboardButton("❌ Отмена")
            markup.add(cancel_btn)
            
            bot.send_message(
                call.message.chat.id,
                "Введите новое имя участницы:",
                reply_markup=markup
            )
            
            # Удаляем старое превью
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение: {e}")
            
        elif call.data == "edit_media":
            # Возвращаемся к отправке медиа
            set_user_state(user_id, UserStates.WAITING_MEDIA)
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            cancel_btn = types.KeyboardButton("❌ Отмена")
            markup.add(cancel_btn)
            
            bot.send_message(
                call.message.chat.id,
                "Отправьте новое фото или видео участницы:",
                reply_markup=markup
            )
            
            # Удаляем старое превью
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение: {e}")
            
        elif call.data == "send_proposal":
            # Проверяем наличие всех необходимых данных
            if not user_data.get(user_id):
                logger.warning(f"user_data пользователя {user_id} пусты при отправке предложения")
                bot.answer_callback_query(call.id, "Ошибка: данные устарели. Начните заново с команды /propose")
                return
                
            required_fields = ['name', 'file_id', 'media_type']
            missing_fields = [field for field in required_fields if field not in user_data[user_id]]
            
            if missing_fields:
                logger.warning(f"Отсутствуют поля {missing_fields} при отправке предложения пользователем {user_id}")
                bot.answer_callback_query(call.id, f"Ошибка: неполные данные. Отсутствуют {', '.join(missing_fields)}. Начните заново.")
                return
                
            # Сохраняем предложение в базу данных
            name = user_data[user_id]['name']
            file_id = user_data[user_id]['file_id']
            media_type = user_data[user_id]['media_type']
            
            conn = None
            try:
                conn = sqlite3.connect('facemash.db')
                c = conn.cursor()
                
                logger.info(f"Сохранение предложения от пользователя {user_id}: {name}, {media_type}")
                
                c.execute("""
                    INSERT INTO suggestions (name, file_id, media_type, suggested_by, status)
                    VALUES (?, ?, ?, ?, 'pending')
                """, (name, file_id, media_type, user_id))
                
                suggestion_id = c.lastrowid
                conn.commit()
                
                # Уведомляем админа
                admin_markup = types.InlineKeyboardMarkup(row_width=2)
                accept_btn = types.InlineKeyboardButton("✅ Принять", callback_data=f"accept_suggestion_{suggestion_id}")
                reject_btn = types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_suggestion_{suggestion_id}")
                admin_markup.add(accept_btn, reject_btn)
                
                admin_caption = f"📝 Новое предложение!\n\n👤 Имя: {name}\n👤 От: {user_id}"
                
                try:
                    if media_type == 'photo':
                        bot.send_photo(ADMIN_ID, file_id, caption=admin_caption, reply_markup=admin_markup)
                    else:
                        bot.send_video(ADMIN_ID, file_id, caption=admin_caption, reply_markup=admin_markup)
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления админу: {e}")
                    # Предложение уже сохранено, поэтому продолжаем
                    
                # Очищаем данные пользователя
                set_user_state(user_id, UserStates.START)
                user_data.pop(user_id, None)
                
                # Удаляем превью и отправляем подтверждение
                try:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                except Exception as e:
                    logger.warning(f"Не удалось удалить сообщение: {e}")
                    
                bot.send_message(
                    call.message.chat.id,
                    "✅ Ваше предложение отправлено на рассмотрение администратору!",
                    reply_markup=types.ReplyKeyboardRemove()
                )
                
                bot.answer_callback_query(call.id, "Предложение отправлено!")
                
            except sqlite3.Error as db_err:
                logger.error(f"Ошибка базы данных в handle_preview_buttons: {db_err}")
                bot.answer_callback_query(call.id, "Произошла ошибка при сохранении предложения")
                if conn:
                    conn.rollback()
                return
            finally:
                if conn:
                    conn.close()
            
        elif call.data == "cancel_proposal":
            # Отменяем предложение
            cancel_proposal_callback(call)
            bot.answer_callback_query(call.id, "Предложение отменено")
            
    except Exception as e:
        logger.error(f"Ошибка в handle_preview_buttons: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Произошла ошибка")
        # Очищаем данные пользователя при ошибке
        try:
            if 'user_id' in locals():
                set_user_state(user_id, UserStates.START)
                user_data.pop(user_id, None)
        except:
            pass

# Функция отмены для колбэков
def cancel_proposal_callback(call):
    try:
        user_id = call.from_user.id
        
        # Очищаем данные пользователя
        set_user_state(user_id, UserStates.START)
        user_data.pop(user_id, None)
        
        # Удаляем сообщение с превью
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение при отмене: {e}")
            
        bot.send_message(
            call.message.chat.id,
            "❌ Предложение отменено",
            reply_markup=types.ReplyKeyboardRemove()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cancel_proposal_callback: {e}")
        bot.send_message(call.message.chat.id, "Произошла ошибка при отмене предложения")

# Функция для проверки подписки на канал
def check_subscription(user_id):
    """Проверяет, подписан ли пользователь на канал
    
    Args:
        user_id: ID пользователя Telegram
        
    Returns:
        bool: True если пользователь подписан, False если нет
    """
    try:
        # Проверяем, является ли пользователь админом
        if user_id == ADMIN_ID:
            logger.info(f"Пользователь {user_id} является админом, пропускаем проверку подписки")
            return True
            
        # Проверяем подписку на канал
        channel_username = 'Simpatia_Liven57'
        
        try:
            # Проверяем статус участника канала
            chat_member = bot.get_chat_member(f'@{channel_username}', user_id)
            
            # Проверяем статус пользователя
            member_status = chat_member.status
            if member_status in ['creator', 'administrator', 'member']:
                logger.info(f"Пользователь {user_id} подписан на канал (статус: {member_status})")
                return True
            else:
                logger.info(f"Пользователь {user_id} не подписан на канал (статус: {member_status})")
                return False
                
        except telebot.apihelper.ApiException as api_err:
            # Если произошла ошибка API Telegram (например, бот не админ в канале)
            logger.error(f"Ошибка API Telegram при проверке подписки: {api_err}")
            
            # В случае ошибки блокируем доступ для безопасности
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки: {e}")
        # В случае любой ошибки блокируем доступ для безопасности
        return False

# Функция для отправки сообщения о необходимости подписки
def send_subscription_message(chat_id):
    """Отправляет сообщение о необходимости подписки
    
    Args:
        chat_id: ID чата пользователя
        
    Returns:
        bool: False (для использования в цепочке return)
    """
    try:
        markup = types.InlineKeyboardMarkup(row_width=1)
        channel_btn = types.InlineKeyboardButton("👉 Подписаться на канал", url="https://t.me/Simpatia_Liven57")
        check_btn = types.InlineKeyboardButton("✅ Проверить подписку", callback_data="check_subscription")
        markup.add(channel_btn)
        markup.add(check_btn)
        
        # Используем safe_send_message для надежной отправки
        bot.send_message(
            chat_id,
            "⛔ <b>Доступ закрыт!</b>\n\n"
            "Для использования бота необходимо подписаться на канал @Simpatia_Liven57\n\n"
            "1. Нажмите кнопку «Подписаться на канал»\n"
            "2. Подпишитесь на канал\n"
            "3. Вернитесь в бот и нажмите «Проверить подписку»",
            parse_mode="HTML",
            reply_markup=markup
        )
        
        logger.info(f"Отправлено сообщение о необходимости подписки пользователю {chat_id}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения о подписке: {e}")
        # В случае ошибки отправляем простое сообщение без форматирования
        try:
            bot.send_message(
                chat_id,
                "Для использования бота необходимо подписаться на канал @Simpatia_Liven57"
            )
        except:
            pass
        return False

# Обработчик принятия/отклонения предложений
@bot.callback_query_handler(func=lambda call: call.data.startswith(('accept_suggestion_', 'reject_suggestion_')))
def handle_suggestion_decision(call):
    conn = None
    try:
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "У вас нет доступа к этой функции")
            return
            
        # Улучшенный парсинг callback_data
        parts = call.data.split('_')
        if len(parts) < 3:
            logger.error(f"Неверный формат callback_data: {call.data}")
            bot.answer_callback_query(call.id, "Ошибка формата данных")
            return
            
        action = parts[0]
        suggestion_id = int(parts[2])
        
        logger.info(f"Обработка {action} для предложения {suggestion_id}")
        
        conn = sqlite3.connect('facemash.db')
        conn.row_factory = sqlite3.Row  # Для более удобного доступа к данным
        c = conn.cursor()
        
        # Получаем информацию о предложении
        c.execute("""
            SELECT name, file_id, media_type, suggested_by, status
            FROM suggestions 
            WHERE id = ?
        """, (suggestion_id,))
        
        suggestion = c.fetchone()
        
        if not suggestion:
            logger.error(f"Предложение с ID {suggestion_id} не найдено")
            bot.answer_callback_query(call.id, "Предложение не найдено")
            return
            
        name = suggestion['name']
        file_id = suggestion['file_id']
        media_type = suggestion['media_type']
        suggested_by = suggestion['suggested_by']
        status = suggestion['status']
        
        # Проверяем, не обработано ли уже предложение
        if status != 'pending':
            bot.answer_callback_query(call.id, "Это предложение уже было обработано")
            return
        
        if action == 'accept':
            try:
                # Добавляем в основную таблицу
                c.execute("""
                    INSERT INTO photos (name, file_id, media_type, approved)
                    VALUES (?, ?, ?, 1)
                """, (name, file_id, media_type))
                
                # Получаем ID вставленной записи
                photo_id = c.lastrowid
                logger.info(f"Добавлена фотография с ID {photo_id}")
                
                # Обновляем статус предложения
                c.execute("UPDATE suggestions SET status = 'accepted' WHERE id = ?", (suggestion_id,))
                
                conn.commit()
                
                # Уведомляем пользователя
                try:
                    bot.send_message(
                        suggested_by,
                        f"✅ Ваше предложение участницы {name} было принято!"
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления пользователю {suggested_by}: {e}")
                
                bot.answer_callback_query(call.id, f"Участница {name} принята!")
                bot.send_message(call.message.chat.id, f"✅ Участница {name} успешно добавлена в турнир!")
                
            except sqlite3.Error as e:
                logger.error(f"Ошибка базы данных при принятии предложения: {e}")
                bot.answer_callback_query(call.id, "Ошибка при принятии предложения")
                if conn:
                    conn.rollback()
                return
                
        else:  # reject
            try:
                # Отклоняем предложение
                c.execute("UPDATE suggestions SET status = 'rejected' WHERE id = ?", (suggestion_id,))
                conn.commit()
                
                # Уведомляем пользователя
                try:
                    bot.send_message(
                        suggested_by,
                        f"❌ Ваше предложение участницы {name} было отклонено."
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления пользователю {suggested_by}: {e}")
                
                bot.answer_callback_query(call.id, f"Предложение {name} отклонено")
                bot.send_message(call.message.chat.id, f"❌ Предложение участницы {name} отклонено")
                
            except sqlite3.Error as e:
                logger.error(f"Ошибка базы данных при отклонении предложения: {e}")
                bot.answer_callback_query(call.id, "Ошибка при отклонении предложения")
                if conn:
                    conn.rollback()
                return
        
        # Удаляем сообщение с кнопками
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка в handle_suggestion_decision: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# Функция отмены для текстовых сообщений
def cancel_proposal(message):
    try:
        user_id = message.from_user.id
        logger.info(f"Отмена предложения пользователем {user_id} через команду")
        
        # Очищаем данные пользователя
        set_user_state(user_id, UserStates.START)
        user_data.pop(user_id, None)
        
        bot.send_message(
            message.chat.id,
            "❌ Предложение отменено",
            reply_markup=types.ReplyKeyboardRemove()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cancel_proposal: {e}")
        bot.reply_to(message, "Произошла ошибка при отмене предложения")

# Улучшаем обработку команды /start
@bot.message_handler(commands=['start'])
def start_command(message):
    try:
        user_id = message.from_user.id
        logger.info(f"Команда /start от пользователя {user_id}")
        
        # Сбрасываем состояние, если пользователь был в процессе предложения
        if user_id in user_states and user_states[user_id] != UserStates.START:
            logger.info(f"Сброс состояния пользователя {user_id} с {user_states[user_id]} на START")
            set_user_state(user_id, UserStates.START)
            user_data.pop(user_id, None)
        
        # Проверяем подписку на канал
        if not check_subscription(user_id):
            send_subscription_message(message.chat.id)
            return
        
        # Если пользователь подписан, добавляем его в список разрешенных
        if user_id not in ALLOWED_USERS:
            ALLOWED_USERS.append(user_id)
            
        # Создаем соответствующую клавиатуру
        markup = create_admin_markup() if user_id == ADMIN_ID else create_user_markup()
        
        bot.send_message(
            message.chat.id,
            f"👋 <b>Добро пожаловать в бот конкурса красоты!</b>\n\n"
            f"<b>Доступные команды:</b>\n"
            f"🎭 <b>Начать голосование</b> - участвовать в текущем турнире\n"
            f"🏆 <b>Топ участниц</b> - посмотреть рейтинг участниц\n"
            f"➕ <b>Предложить участницу</b> - предложить новую участницу",
            parse_mode="HTML",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка в start_command: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при запуске бота")

# Обработчик команды /admin
@bot.message_handler(commands=['admin'])
def admin_command(message):
    try:
        user_id = message.from_user.id
        
        if user_id != ADMIN_ID:
            bot.reply_to(message, "⛔ У вас нет доступа к админ-панели")
            return
            
        # Получаем базовую статистику для отображения
        conn = None
        try:
            conn = sqlite3.connect('facemash.db')
            c = conn.cursor()
            
            # Количество участниц
            c.execute("SELECT COUNT(*) FROM photos WHERE approved = 1")
            participants_count = c.fetchone()[0]
            
            # Количество предложений
            c.execute("SELECT COUNT(*) FROM suggestions WHERE status = 'pending'")
            pending_count = c.fetchone()[0]
            
            # Проверяем статус турнира
            c.execute("SELECT is_active FROM tournament_settings WHERE is_active = 1")
            tournament_active = bool(c.fetchone())
            
            conn.close()
        except:
            participants_count = "?"
            pending_count = "?"
            tournament_active = False
            if conn:
                conn.close()
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        # Управление участницами
        header1 = types.InlineKeyboardButton("👥 УПРАВЛЕНИЕ УЧАСТНИЦАМИ", callback_data="admin_header1")
        btn1 = types.InlineKeyboardButton(f"📥 Предложения ({pending_count})", callback_data="admin_suggestions")
        btn2 = types.InlineKeyboardButton(f"🗑 Удалить участницу", callback_data="admin_delete")
        btn3 = types.InlineKeyboardButton("👁 Посмотреть всех участниц", callback_data="admin_view_all")
        
        # Управление турниром
        header2 = types.InlineKeyboardButton("🏆 УПРАВЛЕНИЕ ТУРНИРОМ", callback_data="admin_header2")
        btn4 = types.InlineKeyboardButton("📈 Статистика", callback_data="admin_stats")
        btn5 = types.InlineKeyboardButton("⚙️ Настройки турнира", callback_data="admin_tournament_settings")
        
        # Статус турнира
        if tournament_active:
            btn6 = types.InlineKeyboardButton("🛑 Остановить турнир", callback_data="stop_tournament")
        else:
            btn6 = types.InlineKeyboardButton("▶️ Запустить турнир", callback_data="start_tournament")
        
        # Дополнительные функции
        header3 = types.InlineKeyboardButton("🛠 ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ", callback_data="admin_header3")
        btn7 = types.InlineKeyboardButton("📊 Экспорт данных", callback_data="admin_export")
        btn8 = types.InlineKeyboardButton("🔄 Перезапустить бота", callback_data="admin_restart")
        btn9 = types.InlineKeyboardButton("🔙 Вернуться в основное меню", callback_data="admin_back_to_main")
        
        # Добавляем кнопки в разделы
        markup.add(header1)
        markup.row(btn1, btn2)
        markup.add(btn3)
        
        markup.add(header2)
        markup.row(btn4, btn5)
        markup.add(btn6)
        
        markup.add(header3)
        markup.row(btn7, btn8)
        markup.add(btn9)
        
        status_emoji = "✅" if tournament_active else "❌"
        
        bot.reply_to(
            message,
            f"👑 *АДМИН-ПАНЕЛЬ*\n\n"
            f"📊 *Статистика:*\n"
            f"• Участниц: {participants_count}\n"
            f"• Ожидают проверки: {pending_count}\n"
            f"• Статус турнира: {status_emoji} {'Активен' if tournament_active else 'Не активен'}\n\n"
            f"Выберите действие:",
            parse_mode="Markdown",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка в admin_command: {e}", exc_info=True)
        bot.reply_to(message, "Произошла ошибка при открытии админ-панели. Проверьте логи.")

# Обработчик команды /cancel
@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    try:
        user_id = message.from_user.id
        cancel_proposal(message)
        
    except Exception as e:
        logger.error(f"Ошибка в cancel_command: {e}")
        bot.reply_to(message, "Произошла ошибка при отмене действия")

# Изменяем обработчик текстовых команд для проверки подписки
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    try:
        user_id = message.from_user.id
        
        # Проверяем подписку на канал перед любым действием
        if not check_subscription(user_id):
            send_subscription_message(message.chat.id)
            return
            
        # Если пользователь подписан, добавляем его в список разрешенных
        if user_id not in ALLOWED_USERS:
            ALLOWED_USERS.append(user_id)
            
        if message.text == "🎭 Начать голосование":
            start_voting(message)
        elif message.text == "🏆 Топ участниц" or message.text == "📊 Топ фото":
            show_top(message)
        elif message.text == "➕ Предложить участницу":
            start_proposal(message)
        elif message.text == "👑 Админ-панель":
            if user_id == ADMIN_ID:
                admin_command(message)
            else:
                bot.send_message(message.chat.id, "У вас нет доступа к админ-панели.")
        elif message.text == "🔧 Сообщить о поломке":
            handle_report_bug(message)
        else:
            # Обработка текущего состояния пользователя
            if user_id in user_states and user_id in user_data:
                handle_user_state(message)
            else:
                bot.send_message(message.chat.id, "Используйте кнопки для навигации по боту.")
    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при обработке вашего сообщения.")

@bot.message_handler(func=lambda message: message.text == "🔧 Сообщить о поломке")
def handle_report_bug(message):
    """Обработчик кнопки сообщения о поломке"""
    try:
        markup = types.InlineKeyboardMarkup()
        contact_button = types.InlineKeyboardButton("Написать разработчику", url="https://t.me/cloudysince")
        markup.add(contact_button)
        
        bot.reply_to(
            message,
            "Если вы обнаружили ошибку или у вас есть предложения по улучшению бота, "
            "пожалуйста, напишите разработчику, нажав кнопку ниже.",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке кнопки сообщения о поломке: {e}")
        bot.reply_to(message, "Произошла ошибка при обработке вашего запроса.")

@bot.message_handler(func=lambda message: message.text == "🏆 Топ участниц")
def show_top(message):
    """Показывает топ-3 участниц с наибольшим количеством голосов"""
    try:
        user_id = message.from_user.id
        
        # Проверяем подписку на канал
        if not check_subscription(user_id):
            markup = types.InlineKeyboardMarkup()
            channel_btn = types.InlineKeyboardButton("Подписаться на канал", url="https://t.me/Simpatia_Liven57")
            check_btn = types.InlineKeyboardButton("✅ Проверить подписку", callback_data="check_subscription")
            markup.add(channel_btn)
            markup.add(check_btn)
            
            bot.reply_to(
                message,
                "⛔ Для использования бота необходимо подписаться на канал @Simpatia_Liven57",
                reply_markup=markup
            )
            return
            
        # Проверяем доступ пользователя
        if user_id not in ALLOWED_USERS:
            bot.reply_to(message, "⛔ У вас нет доступа к боту. Обратитесь к администратору.")
            return
        
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Получаем топ-3 участниц с наибольшим количеством голосов
        c.execute("""
            SELECT p.id, p.name, p.file_id, p.media_type, p.votes
            FROM photos p
            WHERE p.approved = 1
            ORDER BY p.votes DESC
            LIMIT 3
        """)
        
        top_participants = c.fetchall()
        conn.close()
        
        if not top_participants:
            bot.reply_to(message, "🏆 В данный момент нет участниц в рейтинге")
            return
            
        # Отправляем сообщение с заголовком
        bot.send_message(
            message.chat.id,
            "🏆 *ТОП-3 УЧАСТНИЦ*\n\n"
            "_Участницы с наибольшим количеством голосов:_",
            parse_mode="Markdown"
        )
        
        # Отправляем информацию о каждой участнице
        for i, (photo_id, name, file_id, media_type, votes) in enumerate(top_participants, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}[i]
            caption = f"{medal} *{i} место*\n👤 {name}\n📊 Голосов: {votes}"
            
            try:
                if media_type == 'photo':
                    bot.send_photo(message.chat.id, file_id, caption=caption, parse_mode="Markdown")
                elif media_type == 'video':
                    bot.send_video(message.chat.id, file_id, caption=caption, parse_mode="Markdown")
            except Exception as media_error:
                logger.error(f"Ошибка при отправке медиа для участницы {name}: {media_error}")
                bot.send_message(
                    message.chat.id,
                    f"{caption}\n\n❌ _Ошибка при загрузке медиафайла_",
                    parse_mode="Markdown"
                )
                
    except Exception as e:
        logger.error(f"Ошибка при показе топ участниц: {e}")
        bot.reply_to(message, "Произошла ошибка при получении рейтинга участниц.")

def start_voting(message):
    try:
        user_id = message.from_user.id
        
        # Проверяем подписку на канал
        if not check_subscription(user_id):
            markup = types.InlineKeyboardMarkup()
            channel_btn = types.InlineKeyboardButton("Подписаться на канал", url="https://t.me/Simpatia_Liven57")
            check_btn = types.InlineKeyboardButton("✅ Проверить подписку", callback_data="check_subscription")
            markup.add(channel_btn)
            markup.add(check_btn)
            
            bot.reply_to(
                message,
                "⛔ Для использования бота необходимо подписаться на канал @Simpatia_Liven57",
                reply_markup=markup
            )
            return
            
        # Проверяем доступ пользователя
        if user_id not in ALLOWED_USERS:
            bot.reply_to(message, "⛔ У вас нет доступа к боту. Обратитесь к администратору.")
            return
        
        # Проверяем, есть ли активный турнир
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        c.execute("SELECT id FROM tournament_settings WHERE is_active = 1")
        tournament = c.fetchone()
        
        if not tournament:
            bot.reply_to(message, "🚫 В данный момент нет активного турнира")
            conn.close()
            return
            
        # Получаем две случайные участницы
        c.execute("""
            SELECT p.id, p.name, p.file_id, p.media_type, p.votes
            FROM photos p
            WHERE p.approved = 1
            AND NOT EXISTS (
                SELECT 1 FROM user_votes v
                WHERE v.user_id = ? AND v.photo_id = p.id
            )
            ORDER BY RANDOM()
            LIMIT 2
        """, (user_id,))
        
        participants = c.fetchall()
        conn.close()
        
        if len(participants) < 2:
            bot.reply_to(message, "🏁 Вы уже проголосовали за всех участниц!")
            return
            
        # Отправляем фото/видео для голосования
        for participant in participants:
            part_id, name, file_id, media_type, votes = participant
            
            markup = types.InlineKeyboardMarkup()
            vote_btn = types.InlineKeyboardButton("👍 Голосовать", callback_data=f"vote_{part_id}")
            markup.add(vote_btn)
            
            caption = f"👤 {name}\n📊 Текущие голоса: {votes}"
            
            if media_type == 'photo':
                bot.send_photo(message.chat.id, file_id, caption=caption, reply_markup=markup)
            else:
                bot.send_video(message.chat.id, file_id, caption=caption, reply_markup=markup)
                
    except Exception as e:
        logger.error(f"Ошибка в start_voting: {e}")
        bot.reply_to(message, "Произошла ошибка при начале голосования")

# Обработчик голосования
@bot.callback_query_handler(func=lambda call: call.data.startswith('vote_'))
def handle_vote(call):
    conn = None
    try:
        user_id = call.from_user.id
        
        # Проверяем подписку на канал перед любым действием
        if not check_subscription(user_id):
            bot.answer_callback_query(call.id, "⛔ Для голосования необходимо подписаться на канал!", show_alert=True)
            send_subscription_message(call.message.chat.id)
            return
            
        # Если пользователь подписан, добавляем его в список разрешенных
        if user_id not in ALLOWED_USERS:
            ALLOWED_USERS.append(user_id)
        
        photo_id = int(call.data.split('_')[1])
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Проверяем, есть ли активный турнир
        cursor.execute("SELECT id FROM tournament_settings WHERE is_active = 1")
        if not cursor.fetchone():
            bot.answer_callback_query(call.id, "🚫 В данный момент нет активного турнира")
            return
        
        # Проверяем, не голосовал ли уже пользователь за это фото
        cursor.execute("SELECT id FROM user_votes WHERE user_id = ? AND photo_id = ?", (user_id, photo_id))
        if cursor.fetchone():
            bot.answer_callback_query(call.id, "Вы уже голосовали за эту участницу!")
            return
            
        # Проверяем существование фото и получаем имя участницы
        cursor.execute("SELECT id, name FROM photos WHERE id = ? AND approved = 1", (photo_id,))
        photo_data = cursor.fetchone()
        if not photo_data:
            bot.answer_callback_query(call.id, "Участница не найдена или не одобрена")
            return
            
        photo_name = photo_data[1]
            
        # Добавляем голос
        cursor.execute("INSERT INTO user_votes (user_id, photo_id) VALUES (?, ?)", (user_id, photo_id))
        cursor.execute("UPDATE photos SET votes = votes + 1 WHERE id = ?", (photo_id,))
        
        # Проверяем, достигнуто ли необходимое количество голосов
        cursor.execute("""
            SELECT p.votes, t.required_votes 
            FROM photos p, tournament_settings t 
            WHERE p.id = ? AND t.is_active = 1
        """, (photo_id,))
        
        result = cursor.fetchone()
        if result:
            votes, required = result
            
            conn.commit()
            
            # Удаляем сообщение с кнопкой голосования
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщения голосования: {e}")
            
            if votes >= required:
                check_tournament_completion()
                
            # Отправляем сообщение об успешном голосовании
            bot.send_message(call.message.chat.id, f"✅ Вы успешно проголосовали за участницу {photo_name}! Текущее количество голосов: {votes}")
                
            bot.answer_callback_query(call.id, "Ваш голос учтен!")
        else:
            logger.error(f"Не удалось получить данные о голосах и требуемом количестве для фото {photo_id}")
            conn.rollback()
            bot.answer_callback_query(call.id, "Ошибка при обработке голоса")
            
    except Exception as e:
        logger.error(f"Ошибка в handle_vote: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при голосовании")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def check_tournament_completion():
    try:
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Проверяем условия завершения турнира
        c.execute("""
            SELECT COUNT(*) 
            FROM photos p, tournament_settings t
            WHERE p.approved = 1 
            AND t.is_active = 1 
            AND p.votes >= t.required_votes
        """)
        
        completed_count = c.fetchone()[0]
        
        if completed_count > 0:
            # Определяем победителя
            c.execute("""
                SELECT p.id, p.name, p.file_id, p.media_type, p.votes
                FROM photos p
                WHERE p.approved = 1
                ORDER BY p.votes DESC
                LIMIT 1
            """)
            
            winner = c.fetchone()
            
            if winner:
                winner_id, name, file_id, media_type, votes = winner
                
                # Завершаем турнир
                c.execute("UPDATE tournament_settings SET is_active = 0 WHERE is_active = 1")
                conn.commit()
                
                # Отправляем уведомление о победителе
                caption = (f"🎉 Турнир завершен!\n\n"
                          f"👑 Победитель: {name}\n"
                          f"📊 Набрано голосов: {votes}")
                          
                if media_type == 'photo':
                    bot.send_photo(ADMIN_ID, file_id, caption=caption)
                else:
                    bot.send_video(ADMIN_ID, file_id, caption=caption)
                    
        conn.close()
        
    except Exception as e:
        logger.error(f"Ошибка в check_tournament_completion: {e}")

# Обработчик проверки подписки
@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def check_subscription_callback(call):
    """Обработчик нажатия на кнопку проверки подписки"""
    try:
        user_id = call.from_user.id
        logger.info(f"Проверка подписки для пользователя {user_id}")
        
        # Добавляем feedback для пользователя пока проверяем подписку
        bot.answer_callback_query(call.id, "Проверяем вашу подписку...", show_alert=False)
        
        if check_subscription(user_id):
            # Если пользователь подписан, добавляем его в список разрешенных
            if user_id not in ALLOWED_USERS:
                ALLOWED_USERS.append(user_id)
                logger.info(f"Пользователь {user_id} добавлен в список разрешенных пользователей")
                
            # Создаем соответствующую клавиатуру
            markup = create_admin_markup() if user_id == ADMIN_ID else create_user_markup()
            
            try:
                # Редактируем сообщение о подписке
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="✅ <b>Подписка подтверждена!</b>\n\nТеперь вы можете использовать все функции бота.",
                    parse_mode="HTML",
                    reply_markup=None
                )
                
                # Отправляем главное меню
                bot.send_message(
                    call.message.chat.id,
                    "Выберите действие из меню ниже:",
                    reply_markup=markup
                )
                
                # Отправляем уведомление о подтверждении подписки
                bot.answer_callback_query(call.id, "✅ Подписка подтверждена! Доступ открыт.")
            except Exception as edit_error:
                logger.error(f"Ошибка при обновлении сообщения о подписке: {edit_error}")
                # Если не получится отредактировать, просто отправим новое сообщение
                bot.send_message(
                    call.message.chat.id,
                    "✅ <b>Подписка подтверждена!</b>\n\nТеперь вы можете использовать все функции бота.",
                    parse_mode="HTML",
                    reply_markup=markup
                )
        else:
            # Отправляем уведомление о неудачной проверке
            bot.answer_callback_query(
                call.id, 
                "❌ Вы не подписаны на канал! Подпишитесь и нажмите кнопку проверки еще раз.", 
                show_alert=True
            )
            
            # Обновляем сообщение с кнопками подписки (для обновления timestamp)
            try:
                markup = types.InlineKeyboardMarkup(row_width=1)
                channel_btn = types.InlineKeyboardButton("👉 Подписаться на канал", url="https://t.me/Simpatia_Liven57")
                check_btn = types.InlineKeyboardButton("✅ Проверить подписку", callback_data="check_subscription")
                markup.add(channel_btn)
                markup.add(check_btn)
                
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=markup
                )
            except Exception as markup_error:
                logger.error(f"Ошибка при обновлении клавиатуры: {markup_error}")
            
    except Exception as e:
        logger.error(f"Ошибка в check_subscription_callback: {e}")
        # В случае ошибки отправляем уведомление пользователю
        try:
            bot.answer_callback_query(call.id, "Произошла ошибка при проверке подписки. Попробуйте позже.")
        except:
            pass

# Обработчик кнопок админ-панели
@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_buttons(call):
    try:
        user_id = call.from_user.id
        logger.info(f"Обработка кнопки админ-панели: {call.data} от пользователя {user_id}")
        
        if user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "У вас нет доступа к этой функции")
            return
            
        # Проверяем, что call.message не None
        if not call.message:
            logger.error(f"call.message is None при обработке {call.data}")
            bot.answer_callback_query(call.id, "Ошибка: сообщение не найдено")
            return
            
        # Проверяем данные колбэка
        if call.data == "admin_suggestions":
            show_suggestions(call.message)
        elif call.data == "admin_delete":
            show_participants_for_deletion(call.message)
        elif call.data == "admin_stats":
            show_statistics(call.message)
        elif call.data == "admin_tournament_settings":
            show_tournament_settings(call.message)
        elif call.data == "admin_view_all":
            show_all_participants(call.message)
        elif call.data == "admin_export":
            export_database(call.message)
        elif call.data == "admin_restart":
            confirm_restart_bot(call.message)
        elif call.data == "admin_back_to_main":
            # Возвращаем пользователя в основное меню
            markup = create_admin_markup() if user_id == ADMIN_ID else create_user_markup()
            bot.send_message(
                call.message.chat.id,
                "Вы вернулись в основное меню",
                reply_markup=markup
            )
        elif call.data.startswith('admin_header'):
            # Заголовки не обрабатываем
            bot.answer_callback_query(call.id, "Это заголовок раздела")
        else:
            logger.warning(f"Неизвестная команда админ-панели: {call.data}")
            bot.answer_callback_query(call.id, "Неизвестная команда")
            
        # Отвечаем на callback query, чтобы убрать часы загрузки
        bot.answer_callback_query(call.id)
            
    except Exception as e:
        logger.error(f"Ошибка в handle_admin_buttons: {e}", exc_info=True)
        try:
            bot.answer_callback_query(call.id, "Произошла ошибка при обработке команды")
        except:
            pass

# Функция для отображения всех участниц
def show_all_participants(message):
    conn = None
    try:
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Получаем всех одобренных участниц
        c.execute("""
            SELECT id, name, file_id, media_type, votes
            FROM photos
            WHERE approved = 1
            ORDER BY votes DESC
        """)
        
        participants = c.fetchall()
        
        if not participants:
            bot.send_message(message.chat.id, "📭 Нет участниц в турнире")
            return
            
        # Отправляем сообщение с количеством участниц
        bot.send_message(message.chat.id, f"📊 Всего участниц: {len(participants)}")
        
        # Отправляем каждую участницу с информацией
        sent_count = 0
        for participant in participants:
            try:
                if len(participant) < 5:
                    logger.error(f"Неверный формат данных участницы: {participant}")
                    continue
                    
                part_id, name, file_id, media_type, votes = participant
                
                if not file_id:
                    logger.error(f"Пустой file_id для участницы #{part_id}")
                    continue
                
                caption = f"👤 ID: {part_id}\n👤 Имя: {name}\n📊 Голосов: {votes}"
                
                try:
                    if media_type == 'photo':
                        bot.send_photo(message.chat.id, file_id, caption=caption)
                    else:
                        bot.send_video(message.chat.id, file_id, caption=caption)
                        
                    sent_count += 1
                    # Добавляем небольшую задержку, чтобы не превысить лимиты API
                    time.sleep(0.1)
                except telebot.apihelper.ApiException as api_err:
                    logger.error(f"Ошибка API при отправке участницы #{part_id}: {api_err}")
                    continue
                
            except Exception as e:
                logger.error(f"Ошибка при отправке участницы: {e}")
                continue
                
        if sent_count == 0 and participants:
            bot.reply_to(message, "❌ Не удалось отобразить участниц. Попробуйте позже.")
        
        # Добавляем кнопку возврата в админ-панель
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_back_to_admin")
        markup.add(back_btn)
        bot.send_message(message.chat.id, "Используйте кнопку ниже для возврата в админ-панель:", reply_markup=markup)
                
    except Exception as e:
        logger.error(f"Ошибка в show_all_participants: {e}", exc_info=True)
        bot.reply_to(message, "Произошла ошибка при показе участниц")
    finally:
        if conn:
            conn.close()

# Функция для экспорта данных из базы
def export_database(message):
    conn = None
    try:
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Создаем временный файл с отчетом
        report_file = "report.txt"
        with open(report_file, "w", encoding="utf-8") as f:
            # Заголовок отчета
            f.write("===== ОТЧЕТ ПО БАЗЕ ДАННЫХ ТУРНИРА =====\n\n")
            
            # Участницы
            c.execute("SELECT id, name, votes FROM photos WHERE approved = 1 ORDER BY votes DESC")
            participants = c.fetchall()
            f.write(f"УЧАСТНИЦЫ ({len(participants)}):\n")
            f.write("-" * 40 + "\n")
            for p in participants:
                f.write(f"ID: {p[0]}, Имя: {p[1]}, Голосов: {p[2]}\n")
            f.write("\n")
            
            # Голоса
            c.execute("SELECT COUNT(*) FROM user_votes")
            votes_count = c.fetchone()[0]
            c.execute("SELECT COUNT(DISTINCT user_id) FROM user_votes")
            voters_count = c.fetchone()[0]
            f.write(f"ГОЛОСА:\n")
            f.write("-" * 40 + "\n")
            f.write(f"Всего голосов: {votes_count}\n")
            f.write(f"Уникальных голосующих: {voters_count}\n\n")
            
            # Настройки турнира
            c.execute("SELECT required_votes, tournament_duration, is_active, current_tournament_start FROM tournament_settings ORDER BY id DESC LIMIT 1")
            settings = c.fetchone()
            if settings:
                f.write(f"НАСТРОЙКИ ТУРНИРА:\n")
                f.write("-" * 40 + "\n")
                f.write(f"Необходимо голосов: {settings[0]}\n")
                f.write(f"Длительность (часов): {settings[1]}\n")
                f.write(f"Активен: {'Да' if settings[2] else 'Нет'}\n")
                f.write(f"Дата начала: {settings[3]}\n\n")
            
            # Отчет сгенерирован
            f.write(f"Отчет сгенерирован: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Отправляем файл
        with open(report_file, "rb") as f:
            bot.send_document(message.chat.id, f, caption="📊 Экспорт данных из базы")
            
        # Удаляем временный файл
        try:
            os.remove(report_file)
        except:
            pass
            
        # Добавляем кнопку возврата в админ-панель
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_back_to_admin")
        markup.add(back_btn)
        bot.send_message(message.chat.id, "Используйте кнопку ниже для возврата в админ-панель:", reply_markup=markup)
            
    except Exception as e:
        logger.error(f"Ошибка в export_database: {e}", exc_info=True)
        bot.reply_to(message, "Произошла ошибка при экспорте данных")
    finally:
        if conn:
            conn.close()

# Функция для подтверждения перезапуска бота
def confirm_restart_bot(message):
    try:
        markup = types.InlineKeyboardMarkup()
        yes_btn = types.InlineKeyboardButton("✅ Да, перезапустить", callback_data="confirm_restart_yes")
        no_btn = types.InlineKeyboardButton("❌ Нет, отмена", callback_data="admin_back_to_admin")
        markup.row(yes_btn, no_btn)
        
        bot.send_message(
            message.chat.id,
            "⚠️ Вы уверены, что хотите перезапустить бота?\n\n"
            "Это действие остановит все текущие операции и может привести к временной недоступности бота.",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"Ошибка в confirm_restart_bot: {e}", exc_info=True)
        bot.reply_to(message, "Произошла ошибка при отображении подтверждения")

# Обработчик кнопки возврата в админ-панель
@bot.callback_query_handler(func=lambda call: call.data == "admin_back_to_admin")
def handle_back_to_admin(call):
    try:
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "У вас нет доступа к этой функции")
            return
            
        # Вызываем функцию админ-панели
        admin_command(call.message)
        
        # Отвечаем на callback query
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"Ошибка в handle_back_to_admin: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Произошла ошибка")

# Обработчик подтверждения перезапуска бота
@bot.callback_query_handler(func=lambda call: call.data == "confirm_restart_yes")
def handle_restart_bot(call):
    try:
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "У вас нет доступа к этой функции")
            return
            
        bot.send_message(call.message.chat.id, "🔄 Перезапуск бота...")
        
        # Логируем перезапуск
        logger.info(f"Перезапуск бота по команде администратора")
        
        # Выполняем безопасную остановку
        cleanup()
        
        # Отвечаем на callback query
        bot.answer_callback_query(call.id)
        
        # Перезапускаем бота
        python = sys.executable
        os.execl(python, python, "restart_bot.py")
        
    except Exception as e:
        logger.error(f"Ошибка в handle_restart_bot: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Произошла ошибка при перезапуске")

# Механизм предотвращения запуска нескольких экземпляров бота
def is_bot_already_running():
    """Проверяет, запущен ли уже бот"""
    global socket_instance
    try:
        # Пытаемся создать сокет на локальном порту
        bot_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Устанавливаем параметр переиспользования адреса
        bot_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bot_socket.bind(('localhost', 45678))
        bot_socket.listen(1)
        
        # Регистрируем функцию закрытия сокета при завершении
        def cleanup():
            try:
                bot_socket.close()
                logger.info("Сокет успешно закрыт при завершении")
            except Exception as e:
                logger.error(f"Ошибка при закрытии сокета: {e}")
        
        atexit.register(cleanup)
        socket_instance = bot_socket
        
        logger.info("Сокет успешно создан. Бот запущен как единственный экземпляр.")
        return False, bot_socket
    except socket.error as e:
        logger.error(f"Невозможно создать сокет, вероятно бот уже запущен: {e}")
        return True, None

# Проверяем, запущен ли уже бот
is_running, socket_instance = is_bot_already_running()
if is_running:
    logger.error("Бот уже запущен! Завершение работы...")
    print("ОШИБКА: Бот уже запущен в другом процессе!")
    print("Закройте все запущенные экземпляры бота и попробуйте снова.")
    sys.exit(1)

# Инициализация базы данных при запуске
init_db()

# Добавляем обработчик ошибок Telegram API
@bot.middleware_handler(update_types=['message', 'callback_query', 'inline_query'])
def global_error_handler(bot_instance, update):
    """Глобальный обработчик всех типов сообщений"""
    try:
        # Для callback_query добавляем дополнительную обработку
        if update.callback_query:
            logger.info(f"Обрабатываем callback_query: {update.callback_query.data} от пользователя {update.callback_query.from_user.id}")
            
        return update
    except Exception as e:
        logger.error(f"Ошибка в middleware: {e}")
        # Продолжаем обработку, чтобы не блокировать запросы
        return update

# Переопределяем метод обработки исключений
old_process_new_updates = bot.process_new_updates

def safe_process_new_updates(updates):
    """Безопасная обработка обновлений с обработкой ошибок"""
    try:
        old_process_new_updates(updates)
        return True
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"Критическая ошибка при обработке обновлений: {e}\n{error_details}", exc_info=True)
        
        # Отправляем уведомление администратору о критической ошибке
        try:
            bot.send_message(ADMIN_ID, f"⚠️ Критическая ошибка в боте:\n{str(e)[:200]}...")
            
            # Если это callback_query, пытаемся отправить уведомление пользователю о проблеме
            for update in updates:
                if hasattr(update, 'callback_query') and update.callback_query:
                    try:
                        bot.answer_callback_query(
                            update.callback_query.id, 
                            "Извините, произошла ошибка. Пожалуйста, попробуйте ещё раз."
                        )
                    except:
                        pass
        except:
            pass
        return False

def safe_answer_callback(callback_id, text, show_alert=False):
    """Безопасный ответ на callback-запрос с обработкой ошибок"""
    try:
        bot.answer_callback_query(callback_id, text, show_alert=show_alert)
        return True
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback {callback_id}: {e}")
        return False

bot.process_new_updates = safe_process_new_updates

# Функция для безопасной отправки сообщений
def safe_send_message(chat_id, text, **kwargs):
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except telebot.apihelper.ApiException as e:
        logger.error(f"Ошибка API при отправке сообщения: {e}")
        # Пробуем отправить сообщение без особых параметров
        try:
            return bot.send_message(chat_id, text)
        except:
            logger.error("Не удалось отправить сообщение даже в базовом формате")
            return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при отправке сообщения: {e}")
        return None

# Функция для отображения предложенных участниц
def show_suggestions(message):
    conn = None
    try:
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Получаем все ожидающие предложения
        c.execute("""
            SELECT id, name, file_id, media_type, suggested_by
            FROM suggestions
            WHERE status = 'pending'
            ORDER BY created_at DESC
        """)
        
        suggestions = c.fetchall()
        
        if not suggestions:
            bot.send_message(message.chat.id, "📭 Нет новых предложений")
            
            # Добавляем кнопку возврата в админ-панель
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_back_to_admin")
            markup.add(back_btn)
            bot.send_message(message.chat.id, "Используйте кнопку ниже для возврата в админ-панель:", reply_markup=markup)
            return
            
        # Отправляем каждое предложение с кнопками принять/отклонить
        sent_count = 0
        for suggestion in suggestions:
            try:
                if len(suggestion) < 5:
                    logger.error(f"Неверный формат данных предложения: {suggestion}")
                    continue
                    
                suggestion_id, name, file_id, media_type, suggested_by = suggestion
                
                if not file_id:
                    logger.error(f"Пустой file_id для предложения #{suggestion_id}")
                    continue
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                accept_btn = types.InlineKeyboardButton("✅ Принять", callback_data=f"accept_suggestion_{suggestion_id}")
                reject_btn = types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_suggestion_{suggestion_id}")
                markup.add(accept_btn, reject_btn)
                
                caption = f"📝 Предложение #{suggestion_id}\n\n👤 Имя: {name}\n👤 От пользователя: {suggested_by}"
                
                try:
                    if media_type == 'photo':
                        bot.send_photo(message.chat.id, file_id, caption=caption, reply_markup=markup)
                    else:
                        bot.send_video(message.chat.id, file_id, caption=caption, reply_markup=markup)
                        
                    sent_count += 1
                    # Добавляем небольшую задержку, чтобы не превысить лимиты API
                    time.sleep(0.1)
                except telebot.apihelper.ApiException as api_err:
                    logger.error(f"Ошибка API при отправке предложения #{suggestion_id}: {api_err}")
                    continue
                
            except Exception as e:
                logger.error(f"Ошибка при отправке предложения: {e}")
                continue
                
        if sent_count == 0 and suggestions:
            bot.reply_to(message, "❌ Не удалось отобразить предложения. Попробуйте позже.")
        elif sent_count > 0:
            # Добавляем кнопку возврата в админ-панель
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_back_to_admin")
            markup.add(back_btn)
            bot.send_message(message.chat.id, f"📬 Показано предложений: {sent_count}\n\nИспользуйте кнопку ниже для возврата в админ-панель:", reply_markup=markup)
            
    except sqlite3.Error as db_err:
        logger.error(f"Ошибка базы данных в show_suggestions: {db_err}")
        bot.reply_to(message, "Произошла ошибка при доступе к базе данных")
    except Exception as e:
        logger.error(f"Ошибка в show_suggestions: {e}", exc_info=True)
        bot.reply_to(message, "Произошла ошибка при показе предложений")
    finally:
        if conn:
            conn.close()

# Функция для показа участниц для удаления
def show_participants_for_deletion(message):
    conn = None
    try:
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Получаем всех одобренных участниц
        c.execute("""
            SELECT id, name, file_id, media_type, votes
            FROM photos
            WHERE approved = 1
            ORDER BY name
        """)
        
        participants = c.fetchall()
        
        if not participants:
            bot.send_message(message.chat.id, "📭 Нет участниц в турнире")
            
            # Добавляем кнопку возврата в админ-панель
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_back_to_admin")
            markup.add(back_btn)
            bot.send_message(message.chat.id, "Используйте кнопку ниже для возврата в админ-панель:", reply_markup=markup)
            return
            
        # Отправляем сообщение с количеством участниц
        bot.send_message(message.chat.id, f"📊 Всего участниц для удаления: {len(participants)}")
        
        # Отправляем каждую участницу с кнопкой удаления
        sent_count = 0
        for participant in participants:
            try:
                if len(participant) < 5:
                    logger.error(f"Неверный формат данных участницы: {participant}")
                    continue
                    
                part_id, name, file_id, media_type, votes = participant
                
                if not file_id:
                    logger.error(f"Пустой file_id для участницы #{part_id}")
                    continue
                
                markup = types.InlineKeyboardMarkup()
                delete_btn = types.InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_participant_{part_id}")
                markup.add(delete_btn)
                
                caption = f"👤 ID: {part_id}\n👤 Имя: {name}\n📊 Голосов: {votes}"
                
                try:
                    if media_type == 'photo':
                        bot.send_photo(message.chat.id, file_id, caption=caption, reply_markup=markup)
                    else:
                        bot.send_video(message.chat.id, file_id, caption=caption, reply_markup=markup)
                        
                    sent_count += 1
                    # Добавляем небольшую задержку, чтобы не превысить лимиты API
                    time.sleep(0.1)
                except telebot.apihelper.ApiException as api_err:
                    logger.error(f"Ошибка API при отправке участницы #{part_id}: {api_err}")
                    continue
                
            except Exception as e:
                logger.error(f"Ошибка при отправке участницы: {e}")
                continue
                
        if sent_count == 0 and participants:
            bot.reply_to(message, "❌ Не удалось отобразить участниц. Попробуйте позже.")
        
        # Добавляем кнопку возврата в админ-панель
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_back_to_admin")
        markup.add(back_btn)
        bot.send_message(message.chat.id, "Используйте кнопку ниже для возврата в админ-панель:", reply_markup=markup)
                
    except Exception as e:
        logger.error(f"Ошибка в show_participants_for_deletion: {e}", exc_info=True)
        bot.reply_to(message, "Произошла ошибка при показе участниц")
    finally:
        if conn:
            conn.close()

# Функция для показа статистики
def show_statistics(message):
    try:
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Получаем статистику
        c.execute("SELECT COUNT(*) FROM photos WHERE approved = 1")
        total_participants = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM suggestions WHERE status = 'pending'")
        pending_suggestions = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM user_votes")
        total_votes = c.fetchone()[0]
        
        c.execute("SELECT COUNT(DISTINCT user_id) FROM user_votes")
        unique_voters = c.fetchone()[0]
        
        # Получаем топ-3 участниц
        c.execute("""
            SELECT name, votes FROM photos 
            WHERE approved = 1 
            ORDER BY votes DESC 
            LIMIT 3
        """)
        top_participants = c.fetchall()
        
        conn.close()
        
        # Формируем сообщение со статистикой
        stats = (f"📊 **Статистика турнира:**\n\n"
                f"👥 Участниц: {total_participants}\n"
                f"📝 Ожидают одобрения: {pending_suggestions}\n"
                f"🗳 Всего голосов: {total_votes}\n"
                f"👤 Уникальных голосующих: {unique_voters}\n\n")
                
        if top_participants:
            stats += "🏆 **Топ участницы:**\n"
            for i, (name, votes) in enumerate(top_participants, 1):
                stats += f"{i}. {name} - {votes} голосов\n"
        
        # Создаем кнопку возврата
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_back_to_admin")
        markup.add(back_btn)
        
        bot.send_message(message.chat.id, stats, parse_mode="Markdown", reply_markup=markup)
        
    except Exception as e:
        logger.error(f"Ошибка в show_statistics: {e}")
        bot.reply_to(message, "Произошла ошибка при показе статистики")

# Функция для показа настроек турнира
def show_tournament_settings(message):
    try:
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Получаем текущие настройки активного турнира
        c.execute("""
            SELECT required_votes, tournament_duration, is_active
            FROM tournament_settings
            WHERE is_active = 1
        """)
        
        settings = c.fetchone()
        
        if not settings:
            # Если нет активного турнира, получаем последние настройки
            c.execute("""
                SELECT required_votes, tournament_duration, is_active
                FROM tournament_settings
                ORDER BY id DESC
                LIMIT 1
            """)
            settings = c.fetchone()
            
        if not settings:
            # Если нет никаких настроек, используем значения по умолчанию
            required_votes = 15  # Изменено с 100 на 15
            duration = 24
            is_active = False
        else:
            required_votes, duration, is_active = settings
            
        conn.close()
            
        markup = types.InlineKeyboardMarkup(row_width=2)
        votes_btn = types.InlineKeyboardButton("🗳 Изменить кол-во голосов", callback_data="set_votes")
        time_btn = types.InlineKeyboardButton("⏱ Изменить длительность", callback_data="set_time")
        
        if is_active:
            status_btn = types.InlineKeyboardButton("🛑 Остановить турнир", callback_data="stop_tournament")
        else:
            status_btn = types.InlineKeyboardButton("▶️ Запустить турнир", callback_data="start_tournament")
        
        back_btn = types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_back_to_admin")
            
        markup.add(votes_btn, time_btn)
        markup.add(status_btn)
        markup.add(back_btn)
        
        settings_text = (f"⚙️ Настройки турнира:\n\n"
                        f"🗳 Необходимо голосов: {required_votes}\n"
                        f"⏱ Длительность: {duration} часов\n"
                        f"📊 Статус: {'Активен' if is_active else 'Не активен'}")
                        
        bot.send_message(message.chat.id, settings_text, reply_markup=markup)
        
    except Exception as e:
        logger.error(f"Ошибка в show_tournament_settings: {e}")
        bot.reply_to(message, "Произошла ошибка при показе настроек турнира")

# Восстанавливаем обработчик удаления участниц
@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_participant_'))
def handle_participant_deletion(call):
    conn = None
    try:
        user_id = call.from_user.id
        
        if user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "У вас нет доступа к этой функции")
            return
            
        participant_id = int(call.data.split('_')[2])
        
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Получаем информацию об участнице перед удалением
        c.execute("SELECT name FROM photos WHERE id = ?", (participant_id,))
        participant = c.fetchone()
        
        if not participant:
            bot.answer_callback_query(call.id, "Участница не найдена")
            return
            
        participant_name = participant[0]
        
        # Удаляем участницу и связанные голоса
        c.execute("DELETE FROM user_votes WHERE photo_id = ?", (participant_id,))
        c.execute("DELETE FROM photos WHERE id = ?", (participant_id,))
        conn.commit()
        
        # Пробуем удалить сообщение
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение при удалении участницы: {e}")
        
        bot.send_message(call.message.chat.id, f"✅ Участница {participant_name} успешно удалена!")
        bot.answer_callback_query(call.id, f"Участница удалена")
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка базы данных при удалении участницы: {e}")
        bot.answer_callback_query(call.id, "Ошибка при удалении участницы")
        if conn:
            conn.rollback()
    except Exception as e:
        logger.error(f"Ошибка в handle_participant_deletion: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# Восстанавливаем обработчики настроек турнира
@bot.callback_query_handler(func=lambda call: call.data in ['set_votes', 'set_time', 'start_tournament', 'stop_tournament'])
def handle_tournament_settings(call):
    try:
        user_id = call.from_user.id
        
        if user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "У вас нет доступа к этой функции")
            return
            
        if call.data == 'set_votes':
            set_user_state(user_id, UserStates.WAITING_VOTES_COUNT)
            bot.send_message(call.message.chat.id, "Введите необходимое количество голосов:")
            
        elif call.data == 'set_time':
            set_user_state(user_id, UserStates.WAITING_TOURNAMENT_TIME)
            bot.send_message(call.message.chat.id, "Введите длительность турнира в часах:")
            
        elif call.data == 'start_tournament':
            start_new_tournament(call.message)
            
        elif call.data == 'stop_tournament':
            stop_tournament(call.message)
            
    except Exception as e:
        logger.error(f"Ошибка в handle_tournament_settings: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка")

# Восстанавливаем функцию запуска турнира
def start_new_tournament(message):
    conn = None
    try:
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Проверяем, есть ли активный турнир
        c.execute("SELECT id FROM tournament_settings WHERE is_active = 1")
        if c.fetchone():
            bot.reply_to(message, "🚫 Уже есть активный турнир")
            return
            
        # Проверяем, есть ли участницы для турнира
        c.execute("SELECT COUNT(*) FROM photos WHERE approved = 1")
        participants_count = c.fetchone()[0]
        
        if participants_count < 2:
            bot.reply_to(message, "❌ Для начала турнира необходимо минимум 2 участницы")
            return
            
        # Создаем новый турнир
        c.execute("""
            INSERT INTO tournament_settings (required_votes, tournament_duration, is_active, current_tournament_start)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP)
        """, (15, 24))  # Устанавливаем 15 голосов по умолчанию
        
        conn.commit()
        bot.reply_to(message, f"✅ Новый турнир запущен!\n👥 Участниц: {participants_count}\n🗳 Необходимо голосов для победы: 15")
        
        # Добавляем кнопку возврата в админ-панель
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_back_to_admin")
        markup.add(back_btn)
        bot.send_message(message.chat.id, "Используйте кнопку ниже для возврата в админ-панель:", reply_markup=markup)
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка базы данных в start_new_tournament: {e}")
        bot.reply_to(message, "Произошла ошибка при запуске турнира")
        if conn:
            conn.rollback()
    except Exception as e:
        logger.error(f"Ошибка в start_new_tournament: {e}")
        bot.reply_to(message, "Произошла ошибка при запуске турнира")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# Восстанавливаем функцию остановки турнира
def stop_tournament(message):
    conn = None
    try:
        conn = sqlite3.connect('facemash.db')
        c = conn.cursor()
        
        # Получаем информацию о турнире перед остановкой
        c.execute("""
            SELECT t.id, t.required_votes,
                   (SELECT COUNT(*) FROM photos p WHERE p.approved = 1) as total_participants,
                   (SELECT COUNT(*) FROM user_votes) as total_votes
            FROM tournament_settings t
            WHERE t.is_active = 1
        """)
        
        tournament_info = c.fetchone()
        
        if not tournament_info:
            bot.reply_to(message, "🚫 Нет активного турнира")
            return
            
        tournament_id, required_votes, total_participants, total_votes = tournament_info
        
        # Останавливаем турнир
        c.execute("UPDATE tournament_settings SET is_active = 0 WHERE id = ?", (tournament_id,))
        conn.commit()
        
        # Отправляем статистику турнира
        stats = (f"🏁 Турнир завершен!\n\n"
                f"📊 Статистика:\n"
                f"👥 Всего участниц: {total_participants}\n"
                f"🗳 Всего голосов: {total_votes}\n"
                f"⭐ Необходимо было голосов: {required_votes}")
                
        bot.reply_to(message, stats)
        
        # Добавляем кнопку возврата в админ-панель
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_back_to_admin")
        markup.add(back_btn)
        bot.send_message(message.chat.id, "Используйте кнопку ниже для возврата в админ-панель:", reply_markup=markup)
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка базы данных в stop_tournament: {e}")
        bot.reply_to(message, "Произошла ошибка при остановке турнира")
        if conn:
            conn.rollback()
    except Exception as e:
        logger.error(f"Ошибка в stop_tournament: {e}")
        bot.reply_to(message, "Произошла ошибка при остановке турнира")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def handle_user_state(message):
    """Обрабатывает сообщения пользователя в зависимости от его текущего состояния"""
    try:
        user_id = message.from_user.id
        current_state = get_user_state(user_id)
        
        logger.info(f"Обработка сообщения в состоянии {current_state} от пользователя {user_id}")
        
        if current_state == UserStates.WAITING_NAME:
            handle_name(message)
        elif current_state == UserStates.WAITING_VOTES_COUNT:
            # Обработка ввода количества голосов для турнира
            try:
                votes = int(message.text.strip())
                if votes < 1 or votes > 1000:
                    bot.send_message(message.chat.id, "Количество голосов должно быть от 1 до 1000.")
                    return
                    
                user_data[user_id]['votes_count'] = votes
                set_user_state(user_id, UserStates.WAITING_TOURNAMENT_TIME)
                
                bot.send_message(
                    message.chat.id, 
                    "Теперь введите продолжительность турнира в часах (от 1 до 168):"
                )
            except ValueError:
                bot.send_message(message.chat.id, "Пожалуйста, введите число.")
        elif current_state == UserStates.WAITING_TOURNAMENT_TIME:
            # Обработка ввода продолжительности турнира
            try:
                hours = int(message.text.strip())
                if hours < 1 or hours > 168:
                    bot.send_message(message.chat.id, "Продолжительность должна быть от 1 до 168 часов.")
                    return
                    
                # Сохраняем настройки турнира
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                
                # Обновляем настройки турнира
                cursor.execute(
                    "UPDATE tournament_settings SET required_votes = ?, duration_hours = ? WHERE active = 1",
                    (user_data[user_id]['votes_count'], hours)
                )
                conn.commit()
                conn.close()
                
                # Сбрасываем состояние
                set_user_state(user_id, UserStates.START)
                
                bot.send_message(
                    message.chat.id, 
                    f"✅ Настройки турнира обновлены:\n"
                    f"• Требуемое количество голосов: {user_data[user_id]['votes_count']}\n"
                    f"• Продолжительность турнира: {hours} часов",
                    reply_markup=create_admin_markup()
                )
            except ValueError:
                bot.send_message(message.chat.id, "Пожалуйста, введите число.")
        else:
            # Неизвестное состояние
            logger.warning(f"Неизвестное состояние пользователя: {current_state}")
            set_user_state(user_id, UserStates.START)
            bot.send_message(message.chat.id, "Используйте кнопки для навигации по боту.")
    except Exception as e:
        logger.error(f"Ошибка в handle_user_state: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при обработке вашего сообщения.")

# Обработчик сигналов для корректного завершения бота
def signal_handler(signal, frame):
    logger.info("Получен сигнал прерывания, завершаю работу...")
    try:
        # Удаляем вебхук при выходе
        bot.remove_webhook()
        logger.info("Вебхук удален")
    except Exception as e:
        logger.error(f"Ошибка при удалении вебхука: {e}")
    
    # Выход из программы
    sys.exit(0)

# Регистрация обработчика сигналов
signal.signal(signal.SIGINT, signal_handler)

def setup_webhook(url, retry_count=0, max_retries=5):
    try:
        # Проверяем текущий вебхук перед установкой нового
        try:
            info = bot.get_webhook_info()
            current_url = info.url
            
            # Если вебхук уже установлен на нужный URL, не переустанавливаем его
            if current_url == url:
                logger.info(f"Вебхук уже установлен на {url}")
                return
        except Exception as e:
            logger.warning(f"Не удалось получить информацию о текущем вебхуке: {e}")
            
        # Только если URL изменился или не удалось получить информацию
        bot.remove_webhook()
        time.sleep(1)  # Ждем 1 секунду перед установкой
        bot.set_webhook(url=url)
        logger.info("Вебхук успешно установлен")
    except Exception as e:
        if "Too Many Requests" in str(e) and retry_count < max_retries:
            retry_after = 1
            # Извлекаем значение retry_after из сообщения об ошибке, если оно есть
            if "retry after" in str(e):
                try:
                    retry_after = int(str(e).split("retry after ")[1])
                except:
                    retry_after = (retry_count + 1) * 2  # Экспоненциальная задержка
            
            logger.info(f"Превышен лимит запросов, повторная попытка через {retry_after} секунд...")
            time.sleep(retry_after)
            setup_webhook(url, retry_count + 1, max_retries)
        else:
            logger.error(f"Ошибка при установке вебхука: {e}")
            logger.error(f"Используемый URL вебхука: {url}")

def check_and_restore_webhook():
    """Проверяет текущий статус вебхука и восстанавливает его, если он не установлен"""
    try:
        info = bot.get_webhook_info()
        logger.info(f"Текущий статус вебхука: URL={info.url}, pending_updates={info.pending_update_count}")
        
        # Если вебхук не установлен, устанавливаем его
        if not info.url:
            logger.warning("Вебхук не установлен, устанавливаю вручную...")
            # Получаем хост из переменных окружения
            host = os.environ.get('WEBHOOK_HOST', os.environ.get('RENDER_EXTERNAL_URL', ''))
            path = os.environ.get('WEBHOOK_PATH', f'/webhook/{bot.token}')
            if host:
                # Убираем trailing slash если есть
                if host.endswith('/'):
                    host = host[:-1]
                
                url = f"{host}{path}"
                logger.info(f"Попытка автоматической установки вебхука на URL: {url}")
                setup_webhook(url)
                return True
            else:
                logger.error("Не удалось восстановить вебхук: не найдена переменная WEBHOOK_HOST или RENDER_EXTERNAL_URL")
                return False
        return True
    except Exception as e:
        logger.error(f"Ошибка при проверке/восстановлении вебхука: {e}")
        return False

if __name__ == "__main__":
    try:
        # Инициализируем БД
        init_db()
        
        # Главные настройки
        mode = os.environ.get('MODE', 'polling').lower()  # по умолчанию polling
        
        # Настройка SSL
        USE_SSL = False  # По умолчанию отключено
        SSL_CERT = None
        SSL_KEY = None
        
        # Регистрируем обработчик для graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        logger.info("Бот запущен")
        
        # Инициализация keep-alive для Render, если мы в веб-режиме
        if mode == 'webhook' and os.environ.get('RENDER_EXTERNAL_URL'):
            from keep_alive import start_keep_alive_thread
            keep_alive_thread = start_keep_alive_thread()
            logger.info("Запущен keep-alive сервис для Render")
        
        # Определяем режим запуска
        if mode == 'webhook':
            # Режим webhook - для запуска на сервере
            from flask import Flask, request
            app = Flask(__name__)
            
            WEBHOOK_HOST = os.environ.get('WEBHOOK_HOST', '')
            WEBHOOK_PORT = int(os.environ.get('PORT', 5000))
            WEBHOOK_PATH = os.environ.get('WEBHOOK_PATH', f'/webhook/{bot.token}')
            
            # Формируем URL вебхука в зависимости от платформы
            if os.environ.get('RENDER_EXTERNAL_URL'):
                render_url = os.environ.get('RENDER_EXTERNAL_URL')
                # Убедимся, что URL начинается с https://
                if not render_url.startswith('http'):
                    render_url = f"https://{render_url}"
                
                WEBHOOK_URL = render_url + WEBHOOK_PATH
                logger.info(f"Используем URL Render: {WEBHOOK_URL}")
            elif os.environ.get('RAILWAY_PUBLIC_DOMAIN') or os.environ.get('RAILWAY_STATIC_URL'):
                # Для Railway также обрабатываем специальные переменные
                railway_url = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '') or os.environ.get('RAILWAY_STATIC_URL', '')
                if not railway_url.startswith('http'):
                    railway_url = f"https://{railway_url}"
                
                WEBHOOK_URL = railway_url + WEBHOOK_PATH
                logger.info(f"Используем URL Railway: {WEBHOOK_URL}")
            else:
                # Для локального тестирования или других платформ
                if not WEBHOOK_HOST:
                    logger.warning("WEBHOOK_HOST не определен, используем localhost для тестирования")
                    WEBHOOK_HOST = f"https://example.com"
                
                WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
                logger.info(f"Используем стандартный URL: {WEBHOOK_URL}")
            
            # Дополнительные проверки URL вебхука
            if not WEBHOOK_URL.startswith('https://'):
                logger.error(f"URL вебхука должен начинаться с https://: {WEBHOOK_URL}")
                WEBHOOK_URL = f"https://{WEBHOOK_URL.replace('http://', '')}"
                logger.info(f"Исправленный URL вебхука: {WEBHOOK_URL}")
            
            logger.info(f"Бот запущен в режиме webhook на {WEBHOOK_URL}")
            
            try:
                # Удаляем существующий вебхук
                bot.remove_webhook()
                time.sleep(0.2)  # Небольшая задержка для обработки запроса
                
                # Устанавливаем новый вебхук используя функцию с повторными попытками
                logger.info(f"Устанавливаем вебхук на URL: {WEBHOOK_URL}")
                setup_webhook(WEBHOOK_URL)
            except Exception as e:
                logger.error(f"Ошибка при установке вебхука: {e}")
                logger.error(f"Используемый URL вебхука: {WEBHOOK_URL}")
        
        # Проверяем, запущен ли бот на хостинге
        IS_HEROKU = os.environ.get('DYNO') is not None
        IS_PYTHONANYWHERE = 'PYTHONANYWHERE_DOMAIN' in os.environ
        IS_RAILWAY = 'RAILWAY_STATIC_URL' in os.environ
        IS_RENDER = 'RENDER_EXTERNAL_URL' in os.environ
        
        # Переменная окружения для определения режима (webhook/polling)
        USE_WEBHOOK = os.environ.get('USE_WEBHOOK', 'False').lower() in ('true', '1', 't')
        
        # Проверяем, нужно ли использовать webhook
        if USE_WEBHOOK or IS_HEROKU or IS_PYTHONANYWHERE or IS_RAILWAY or IS_RENDER:
            # Если на Render, запускаем поток keep-alive
            if IS_RENDER:
                keep_alive_thread = start_keep_alive_thread()
                logger.info("Запущен поток keep-alive для Render")
                
                # Проверяем и восстанавливаем вебхук, если он не установлен
                webhook_status = check_and_restore_webhook()
                if webhook_status:
                    logger.info("Проверка вебхука успешно выполнена")
                else:
                    logger.warning("Проверка вебхука выполнена с ошибками, продолжаем инициализацию")
            
            # Режим webhook - для хостинга
            import flask
            from flask import Flask, request
            app = Flask(__name__)
            
            # URL для webhook должен соответствовать URL вашего приложения
            if IS_RAILWAY:
                # Для Railway используем специфичную переменную окружения
                WEBHOOK_HOST = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
                if not WEBHOOK_HOST:
                    WEBHOOK_HOST = os.environ.get('RAILWAY_STATIC_URL', '')
                
                # Убедимся, что URL начинается с https://
                if WEBHOOK_HOST and not WEBHOOK_HOST.startswith('http'):
                    WEBHOOK_HOST = f"https://{WEBHOOK_HOST}"
                
                logger.info(f"Railway host: {WEBHOOK_HOST}")
            elif IS_RENDER:
                # Для Render используем переменную окружения RENDER_EXTERNAL_URL
                WEBHOOK_HOST = os.environ.get('RENDER_EXTERNAL_URL', '')
                logger.info(f"Render host: {WEBHOOK_HOST}")
            else:
                WEBHOOK_HOST = os.environ.get('WEBHOOK_HOST', 'https://your-app-name.herokuapp.com')
            
            WEBHOOK_PATH = os.environ.get('WEBHOOK_PATH', f'/webhook/{bot.token}')
            
            # Формируем полный URL вебхука
            if WEBHOOK_HOST:
                WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
                logger.info(f"Формируем URL вебхука: {WEBHOOK_URL}")
            else:
                logger.error("WEBHOOK_HOST не определен, вебхук не будет работать!")
                WEBHOOK_URL = f"https://example.com{WEBHOOK_PATH}"
            
            # Настройка webhook
            bot.remove_webhook()
            
            try:
                # Устанавливаем вебхук с подробными логами
                logger.info(f"Устанавливаем вебхук на URL: {WEBHOOK_URL}")
                setup_webhook(WEBHOOK_URL)
            except Exception as e:
                logger.error(f"Ошибка при установке вебхука: {e}")
                logger.error(f"Используемый URL вебхука: {WEBHOOK_URL}")
                # Продолжим выполнение, чтобы хотя бы сервер запустился
                pass
            
            @app.route(WEBHOOK_PATH, methods=['POST'])
            def webhook():
                logger.info("Получен webhook-запрос от Telegram")
                if request.headers.get('content-type') == 'application/json':
                    json_string = request.get_data().decode('utf-8')
                    logger.info(f"Содержимое webhook-запроса: {json_string[:100]}...")
                    try:
                        update = telebot.types.Update.de_json(json_string)
                        
                        # Дополнительное логирование типа обновления для отладки
                        if hasattr(update, 'callback_query') and update.callback_query:
                            logger.info(f"Получен callback_query с data: {update.callback_query.data}")
                        elif hasattr(update, 'message') and update.message:
                            logger.info(f"Получено сообщение типа: {update.message.content_type}")
                        
                        # Безопасная обработка обновлений
                        try:
                            bot.process_new_updates([update])
                            logger.info(f"Обработано обновление типа: {update.message.content_type if hasattr(update, 'message') and update.message else 'не сообщение'}")
                        except Exception as e:
                            logger.error(f"Ошибка при обработке обновления: {e}")
                            # Восстанавливаем middleware после ошибки
                            if hasattr(bot, 'middleware_handler'):
                                bot.middleware_handler.process_update([update])
                        
                        return ''
                    except Exception as e:
                        logger.error(f"Ошибка при обработке webhook-запроса: {e}")
                        return 'Ошибка при обработке: ' + str(e), 500
                else:
                    logger.warning(f"Получен webhook-запрос с неверным content-type: {request.headers.get('content-type')}")
                    return 'Ошибка: не JSON', 403
            
            @app.route('/')
            def index():
                return "Бот работает!"
            
            # Запуск Flask-сервера
            PORT = int(os.environ.get('PORT', 5000))
            app.run(host='0.0.0.0', port=PORT)
        else:
            # Режим polling - для локального запуска
            logger.info("Бот запущен в режиме polling")
            
            # Проверяем, запущен ли уже бот
            already_running, socket_instance = is_bot_already_running()
            if not already_running:
                # Сбрасываем вебхук для надежности
                bot.remove_webhook()
                # Запускаем бота в режиме polling
                logger.info("Запускаю бота в режиме polling...")
                bot.infinity_polling(timeout=10, long_polling_timeout=5, allowed_updates=None)
            else:
                logger.error("Бот уже запущен в другом процессе. Завершение работы.")
                print("ОШИБКА: Бот уже запущен в другом процессе!")
                print("Используйте restart_bot.py для перезапуска.")
                sys.exit(1)
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        traceback.print_exc()
   
