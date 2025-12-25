# services/thread_manager.py

# Словарь в памяти: {user_id: message_id_в_группе}
_threads = {}

def set_last_msg_id(user_id: int, msg_id: int):
    """Запоминаем ID последнего сообщения в переписке (от юзера или админа)"""
    _threads[user_id] = msg_id

def get_last_msg_id(user_id: int):
    """Получаем ID, на который нужно ответить"""
    return _threads.get(user_id)