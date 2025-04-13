import os
import time
import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def create_and_host_meet():
    """
    Создает встречу в Google Meet и автоматически принимает всех участников.
    """
    print("🚀 Запуск Google Meet с автоматическим подтверждением участников...")
    
    # Настройка Chrome
    chrome_options = Options()
    
    # Используем существующий профиль Chrome для сохранения авторизации
    user_data_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Google', 'Chrome', 'User Data')
    if os.path.exists(user_data_dir):
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        chrome_options.add_argument("--profile-directory=Default")
        print(f"✅ Используем существующий профиль Chrome: {user_data_dir}")
    
    # Дополнительные опции для стабильности
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--use-fake-ui-for-media-stream")  # Автоматически разрешать доступ к камере/микрофону
    
    # Путь к ChromeDriver - если он в PATH, можно оставить пустым
    chrome_driver_path = ""  # Укажите путь к chromedriver, если он установлен не в PATH
    
    # Инициализация драйвера
    try:
        if chrome_driver_path:
            service = Service(chrome_driver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            driver = webdriver.Chrome(options=chrome_options)
        
        # Максимизируем окно для лучшей видимости элементов
        driver.maximize_window()
        
        # Открываем Google Meet
        print("🌐 Открываем Google Meet...")
        driver.get("https://meet.google.com/new")
        time.sleep(3)
        
        # Проверяем, нужно ли выбрать профиль
        try:
            profile_buttons = driver.find_elements(By.XPATH, "//div[contains(text(), 'Продолжить как')]")
            if profile_buttons and len(profile_buttons) > 0:
                profile_buttons[0].click()
                print("👤 Выбран сохраненный профиль")
                time.sleep(2)
        except Exception as e:
            print(f"ℹ️ Информация: {e}")
        
        # Ожидаем загрузки страницы Meet
        print("⏳ Ожидаем создания встречи...")
        
        # Пропускаем запрос на доступ к камере/микрофону
        try:
            skip_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Продолжить без')]"))
            )
            skip_button.click()
            print("🎥 Пропущен запрос разрешений камеры/микрофона")
            time.sleep(2)
        except Exception as e:
            try:
                # Пробуем на английском
                skip_en_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Continue without')]"))
                )
                skip_en_button.click()
                print("🎥 Skipped camera/microphone permissions")
                time.sleep(2)
            except:
                print("ℹ️ Запрос разрешений не найден или уже обработан")
        
        # Ждем, пока URL обновится и будет содержать код встречи
        WebDriverWait(driver, 20).until(
            lambda d: len(d.current_url.split("/")) > 3 and "new" not in d.current_url
        )
        
        # Получаем URL встречи
        meet_url = driver.current_url
        print(f"\n✅ Встреча создана успешно!")
        print(f"🔗 Ссылка на встречу: {meet_url}")
        print("📢 Отправьте эту ссылку участникам. Они будут автоматически приняты.")
        
        # Режим автоматического принятия участников
        print("\n⚠️ Не закрывайте это окно! ⚠️")
        print("👥 Автоматическое принятие участников активировано...")
        print("🔄 Скрипт будет работать, пока вы не закроете это окно или не нажмете Ctrl+C")
        
        # Функция для проверки и принятия новых участников
        def check_and_admit_participants():
            try:
                # Проверяем, есть ли кнопки "Принять"
                admit_buttons = driver.find_elements(By.XPATH, "//span[contains(text(), 'Принять')]")
                if admit_buttons and len(admit_buttons) > 0:
                    for button in admit_buttons:
                        try:
                            button.click()
                            print("👋 Участник автоматически принят!")
                            time.sleep(0.5)
                        except:
                            pass
                
                # Проверяем на английском
                admit_buttons_en = driver.find_elements(By.XPATH, "//span[contains(text(), 'Admit')]")
                if admit_buttons_en and len(admit_buttons_en) > 0:
                    for button in admit_buttons_en:
                        try:
                            button.click()
                            print("👋 Participant automatically admitted!")
                            time.sleep(0.5)
                        except:
                            pass
            except Exception as e:
                # Игнорируем ошибки при проверке на новые запросы
                pass
        
        # Бесконечный цикл проверки новых участников
        counter = 0
        try:
            while True:
                check_and_admit_participants()
                time.sleep(1)
                counter += 1
                
                # Каждые 60 секунд показываем что скрипт работает
                if counter % 60 == 0:
                    print(f"⏱️ Работаем уже {counter // 60} минут... Ожидаем участников.")
        except KeyboardInterrupt:
            print("\n⛔ Скрипт остановлен пользователем")
        
        return meet_url
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None
    
    finally:
        # Не закрываем браузер, чтобы встреча продолжалась
        pass

if __name__ == "__main__":
    print("🤖 Google Meet Auto Host - Автоматическое принятие участников")
    print("------------------------------------------------------------")
    
    meet_link = create_and_host_meet()
    
    if not meet_link:
        print("\n❌ Не удалось создать встречу. Проверьте подключение и наличие ChromeDriver.")
        print("   Для работы скрипта установите библиотеку selenium: pip install selenium") 