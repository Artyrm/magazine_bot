# create_qr.py
import qrcode

# Данные из вашего конфига
name = "Ассоциация участников технологических кружков"
personal_acc = "40703810038000006991"
bank_name = "ПАО Сбербанк"
bic = "044525225"
corresp_acc = "30101810400000000225" # К/с Сбербанка (стандартный для этого БИК)
payee_inn = "7714997200"
purpose = "Пожертвование"

# Формируем строку по стандарту ST0001
# Кодировка windows-1251 обычно лучше воспринимается старыми банкоматами, 
# но UTF-8 (по умолчанию) сейчас работает везде.
qr_data = (
    f"ST00012|Name={name}|"
    f"PersonalAcc={personal_acc}|"
    f"BankName={bank_name}|"
    f"BIC={bic}|"
    f"CorrespAcc={corresp_acc}|"
    f"PayeeINN={payee_inn}|"
    f"Purpose={purpose}"
)

# Создаем картинку
qr = qrcode.QRCode(
    version=1,
    error_correction=qrcode.constants.ERROR_CORRECT_M,
    box_size=10,
    border=4,
)
qr.add_data(qr_data)
qr.make(fit=True)

img = qr.make_image(fill_color="black", back_color="white")
img.save("payment_qr.png")

print("✅ Файл payment_qr.png успешно создан!")