# get_token.py
import yadisk

# Вставьте сюда данные со страницы создания приложения
ID = "ad21e6ee49e74d5c81f095d38807a7c4"
SECRET = "b88b89f85b294cca9fcca8e41cf4138b"

y = yadisk.YaDisk(ID, SECRET)
url = y.get_code_url()

print("1. Перейдите по этой ссылке:", url)
print("2. Нажмите 'Разрешить', скопируйте код из браузера.")
code = input("3. Вставьте код сюда: ").strip()

try:
    response = y.get_token(code)
    token = response.access_token
    print("\n-------------------------")
    print("ВАШ НОВЫЙ ТОКЕН:")
    print(token)
    print("-------------------------")
    print("Скопируйте его в файл .env в поле YANDEX_TOKEN")
except Exception as e:
    print("Ошибка:", e)