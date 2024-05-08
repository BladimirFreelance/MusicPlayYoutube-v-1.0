import sys, os, vlc, sqlite3, logging, ctypes, requests, time, threading
from PyQt5 import QtWidgets, QtGui, QtCore
from yt_dlp import YoutubeDL
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QPushButton, QSlider, QLabel
from PyQt5.QtCore import Qt, QObject, pyqtSignal, QTimer, QThread, QPoint
from channels_window import Ui_ChannelsWindow

from pynput.keyboard import Key, Listener


#Генерация абсолютного пути к ресурсу для работы с файлами внутри скомпилированного приложения
def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

# Глобальный метод сбора ошибок в файл
# Настройка логгера

LOG_FILE_PATH = 'error.log'

def setup_logger():
    logger = logging.getLogger('MusicPlayYouTube')
    logger.setLevel(logging.ERROR)
    handler = logging.FileHandler('error.log')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

# Глобальный обработчик исключений
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger = setup_logger()
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

# Настройка перехватчика
logger = setup_logger()
sys.excepthook = handle_exception


# Создание и инициализация базы данных SQLite для хранения информации о каналах
def create_database():
    # Подключаемся к базе данных (она будет создана, если еще не существует)
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()

    # Создаем таблицу каналов
    c.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL
            )
        ''')

    # Проверяем, есть ли уже записи в таблице
    c.execute('SELECT COUNT(*) FROM channels')
    if c.fetchone()[0] == 0:
        # Добавляем начальную запись, если таблица пуста
        c.execute('INSERT INTO channels (name, url) VALUES (?, ?)',
                  ("Rick Astley", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&ab_channel=RickAstley"))

    # Закрываем подключение к базе данных
    conn.commit()
    conn.close()


create_database()


# Функция для получения списка каналов из базы данных
def get_channels():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('SELECT * FROM channels')
    channels = c.fetchall()
    conn.close()
    return channels


# Класс для проверки наличия интернет-соединения в отдельном потоке
class InternetCheckTask(QtCore.QThread):

    internet_status_signal = QtCore.pyqtSignal(bool)

    def run(self):
        def check_connection():
            while True:
                try:
                    requests.get('http://www.google.com', timeout=3)
                    print("Интернет соединение есть")
                    self.internet_status_signal.emit(True)  # Сигнал о наличии интернета
                    return
                except requests.exceptions.RequestException:
                    print("Интернет соединение отсутствует")
                    self.internet_status_signal.emit(False)  # Сигнал об отсутствии интернета
                    time.sleep(3)

        thread = threading.Thread(target=check_connection)
        thread.start()


# Окно логотипа при запуске
class LoadWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()  # Опционально, делает программу "осведомленной" о DPI, что актуально для Windows
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)  # Фон виджета делаем прозрачным
        self.label = QtWidgets.QLabel(self)
        pixmap = QtGui.QPixmap("design.png")  # Убедитесь, что файл design.png находится в нужной директории
        self.label.setPixmap(pixmap)
        self.label.setScaledContents(True)

        # Получение размеров экрана
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)

        print(f"Разрешение экрана: {width} x {height}")
        print("адаптация логтипа под разрешение")
        self.label.setFixedSize(int(width * 0.1883), int(height * 0.3347))  # Устанавливаем размер label в соответствии с размером изображения
        print("Разрешение логотипа: ", int(width * 0.1883), int(height * 0.3347))

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.label)
        self.setLayout(layout)
        self.show()
        QtCore.QTimer.singleShot(4000, self.close)


# Класс для управления воспроизведением музыки
class Player(QtCore.QObject):
    state_changed = QtCore.pyqtSignal(str)  # Добавляем сигнал для изменения состояния
    signal_error = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        self.reload_channels()

        self.connect_internet_signal = InternetCheckTask()
        self.connect_internet_signal.internet_status_signal.connect(self.handler_status)

        self.attempt_count = 0  # Счётчик попыток воспроизведения

    # Метод для обновления состояния интернет-соединения
    def handler_status(self, signal_status):
        if not signal_status:  # Если нет соединения
            self.update_state("NoConnect")
        elif signal_status:  # Если есть соединение
            self.stop_All()
            self.instance = vlc.Instance()
            self.player = self.instance.media_player_new()
            self.reload_channels()
            self.run()

    def reload_channels(self):
        self.channels = get_channels()  # Загрузка каналов из базы данных
        if self.channels:
            self.current_channel_index = 0
            self.current_channel = self.channels[self.current_channel_index]  #  извлекает элемент из списка self.channels
        else:
            print("Нет каналов elase ")
            create_database()  # Создание базы данных

    def update_state(self, state):  # Метод для обновления состояния
        self.current_state = state
        self.state_changed.emit(state)

    def stop_All(self):  # Метод для остановки
        self.player.stop()
        self.player.get_media().release()
        self.player.release()
        del self.player
        return

    def stop(self):  # Метод для остановки
        self.player.stop()
        self.update_state("Stopped")

    def run_reserve(self):
        try:
            with YoutubeDL({'format': 'bestaudio'}) as ydl:
                info_dict = ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ&ab_channel=RickAstley", download=False)
                audio_url = info_dict.get('url', None)
            if audio_url:
                self.player.set_media(vlc.Media(audio_url))
                self.player.play()
                self.update_state("NoChannel")
        except Exception as e:
            print("Error playing run_reserve:", e)

    def run(self):   # Метод для воспроизведения
        name = self.current_channel[1]
        url = self.current_channel[2]  # Get the URL from the current channel
        print("name - ", name)
        try:
            with YoutubeDL({'format': 'bestaudio'}) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                audio_url = info_dict.get('url', None)
            if audio_url:
                self.player.set_mrl(audio_url)
                self.player.play()
                self.update_state("Playing")
        except Exception as e:
            print("Error playing:", e)
            self.handler_error_play(str(e))

    def handler_error_play(self, error):
        if "Failed to extract any player response" in str(error):
            print("Найдено сообщение я принял из обработчика - ", str(error))
            self.connect_internet_signal.start()  # Запускаем код для проверки интернет соединения
        elif "is not a valid URL" in str(error):
            print("Найдено сообщение я принял из обработчика - ", str(error))
            self.signal_error.emit(str("URL-адресc некорректен"))
            self.next_channel()
        elif "This live stream recording is not available" in str(error):
            print("Найдено сообщение я принял из обработчика - ", str(error))
            self.signal_error.emit(str("Эта трансляция недоступна"))
            self.update_state("stream_not_available")
        elif "Video unavailable" in str(error):
            print("Найдено сообщение я принял из обработчика - ", str(error))
            self.signal_error.emit(str("Ссылка неверна или эта трансляция недоступна"))
            self.update_state("video_unavailable")
        elif "Unable to download webpage" in str(error):
            print("Найдено сообщение я принял из обработчика - ", str(error))
            self.signal_error.emit(str("Ссылка неверна или эта трансляция недоступна"))
            self.update_state("video_unavailable")
        elif "[youtube:truncated_id]" in str(error):
            print("Найдено сообщение я принял из обработчика - ", str(error))
            self.signal_error.emit(str("Ссылка неверна или эта трансляция недоступна"))
            self.update_state("video_unavailable")
        elif "[youtube:truncated_url]" in str(error):
            print("Найдено сообщение я принял из обработчика - ", str(error))
            self.signal_error.emit(str("Ссылка неверна или эта трансляция недоступна"))
            self.update_state("video_unavailable")
        elif "Private video" in str(error):
            print("Найдено сообщение я принял из обработчика - ", str(error))
            self.signal_error.emit(str("Ссылка неверна или эта трансляция недоступна"))
            self.update_state("video_unavailable")


    def next_channel(self):
        if self.channels:
            # Переходим к следующему каналу, сбрасывая счётчик если достигли конца списка
            self.current_channel_index = (self.current_channel_index + 1) % len(self.channels)
            if self.current_channel_index == 0:
                self.attempt_count += 1  # Увеличиваем счётчик циклов по списку

            if self.attempt_count < 10:  # Позволяем пройти список каналов два раза
                self.current_channel_index = (self.current_channel_index + 1) % len(self.channels)
                self.current_channel = self.channels[self.current_channel_index]
                print("Переключено на канал:", self.current_channel)
                self.run()
            else:
                print("Доступных для переключения каналов больше нет.")
                self.signal_error.emit("Не найдено рабочих URL-адресов")
                self.run_reserve()
        else:
            print("Каналы отсутствуют.")
            self.run_reserve()


# Класс главного потока для создания и управления приложением в системном трее
class SystemTrayApp(QtWidgets.QWidget):

    def __init__(self):
        super().__init__()
        # Инициализация основного виджета приложения и загрузка компонентов интерфейса
        self.control_window = QtWidgets.QWidget()  # Создание виджета для контрольной панели
        self.control_window.setWindowTitle("Control Panel")  # Установка заголовка окна
        layout = QVBoxLayout()  # Контейнер для кнопок

        self.player = Player()  # Создаем экземпляр Player
        self.player.state_changed.connect(self.update_tray_tooltip)  # Подключаем обработку изменения состояния
        self.player.signal_error.connect(self.show_toast)

        # Установка стиля для SystemTrayApp
        self.createTrayIcon()  # Создание иконки в системном трее
        # self.control_window.hide()  # Установить Control Panel как скрытое по умолчанию

        # Создание кнопок управления
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()  # Опционально, делает программу "осведомленной" о DPI, что актуально для Windows

        # Получение размеров экрана
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)

        # Создание кнопок управления
        buttons_layout = QHBoxLayout()  # Контейнер для кнопок
        button_size = QtCore.QSize(int(width * 0.01954), int(height * 0.01737))  # Размер кнопок
        print("Размер кнопок: ", int(width * 0.01954), int(height * 0.01737))

        # Стиль для кнопок
        buttons_css = """
                   QPushButton {
                       background-color: rgba(255, 255, 255, 0);
                       border: none;
                   }
                   QPushButton:hover {
                       background-color: rgba(255, 255, 255, 50);
                   }
               """

        # Создание метки для отображения названия канала
        self.channel_label = QLabel("" + self.player.current_channel[1])  # Название текущего канала
        self.channel_label.setAlignment(Qt.AlignCenter)  # Центрирование текста

        self.font_size = int(height * 0.010)  # примерно 1.4% от высоты экрана
        self.padding = int(height * 0.003)  # примерно 0.5% от высоты экрана
        self.border_radius = int(height * 0.0070)  # примерно 0.75% от высоты экрана

        self.channel_label.setStyleSheet(f"""
                           QLabel {{
                               font-size: {self.font_size}pt;
                               color: white;
                               background-color: rgba(0, 0, 0, 150);
                               padding: {self.padding}px;
                               border-radius: {self.border_radius}px;
                           }}
                       """)
        layout.addWidget(self.channel_label)

        # Создание кнопок
        self.previous_button = QPushButton()
        self.previous_button.setIcon(QtGui.QIcon(resource_path("left.png")))
        self.previous_button.setIconSize(button_size)
        self.previous_button.setMinimumSize(button_size)
        self.previous_button.clicked.connect(self.play_previous_channel)
        self.previous_button.setStyleSheet(buttons_css)

        self.play_button = QPushButton()
        self.play_button.setIcon(QtGui.QIcon(resource_path("play.png")))
        self.play_button.setIconSize(button_size)
        self.play_button.setMinimumSize(button_size)
        self.play_button.clicked.connect(self.player.run)
        self.play_button.setStyleSheet(buttons_css)

        self.stop_button = QPushButton()
        self.stop_button.setIcon(QtGui.QIcon(resource_path("stop.png")))
        self.stop_button.setIconSize(button_size)
        self.stop_button.setMinimumSize(button_size)
        self.stop_button.clicked.connect(self.player.stop)
        self.stop_button.setStyleSheet(buttons_css)

        self.next_button = QPushButton()
        self.next_button.setIcon(QtGui.QIcon(resource_path("right.png")))
        self.next_button.setIconSize(button_size)
        self.next_button.setMinimumSize(button_size)
        self.next_button.clicked.connect(self.play_next_channel)
        self.next_button.setStyleSheet(buttons_css)

        # Добавление кнопок в горизонтальный макет
        buttons_layout.addWidget(self.previous_button)
        buttons_layout.addWidget(self.play_button)
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addWidget(self.next_button)

        # Создание слайдера громкости
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(self.player.player.audio_get_volume())
        self.volume_slider.valueChanged.connect(self.player.player.audio_set_volume)
        layout.addLayout(buttons_layout)
        layout.addWidget(self.volume_slider)
        self.control_window.setLayout(layout)
        self.control_window.setWindowFlags(QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint | QtCore.Qt.NoDropShadowWindowHint)
        self.control_window.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        self.check_log_file_size()
        self.start_listener()

        if not self.player.channels:  # Если нет каналов
            self.show_channels_window()  # Открыть окно управления каналами
        elif self.player.channels:  # Если каналы есть
            self.player.run()  # Начать воспроизведение

        self.control_window.show()
        self.control_window.hide()

    # Создание иконки в системном трее и метод обработки нажатия на иконку
    def createTrayIcon(self):
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        icon_path = resource_path("design.png")  # Убедитесь, что файл действительно существует по этому пути
        self.tray_icon.setIcon(QtGui.QIcon(icon_path))
        self.tray_icon.setToolTip("Stopped")  # надпись над иконкой

        tray_menu = QtWidgets.QMenu()  # Создание контекстного меню для иконки в трее
        quit_action = QtWidgets.QAction("Exit", self)
        quit_action.triggered.connect(QtWidgets.qApp.quit)

        channels_action = tray_menu.addAction("Каналы")
        channels_action.triggered.connect(self.show_channels_window)  # Подключение сигнала к слоту

        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)

        self.tray_icon.activated.connect(self.tray_icon_activated)  # Включаем обработку клика по иконке

        self.tray_icon.show()  # Показываем иконку

    def show_channels_window(self):
        self.channels_window = QtWidgets.QDialog()  # Создаем экземпляр QDialog
        self.ui_channels = Ui_ChannelsWindow(self.channels_window)  # Передаем этот экземпляр в Ui_ChannelsWindow
        self.ui_channels.actionTriggered.connect(self.onActionTriggered)
        self.channels_window.show()  # Показываем окно

    def tray_icon_activated(self, reason):  # Метод для обработки события нажатия на иконку
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            pos = QtGui.QCursor.pos()
            self.control_window.move(pos.x() - self.control_window.width() // 2, pos.y() - self.control_window.height())
            self.control_window.show()

    def play_previous_channel(self):  # Метод для обработки события нажатия на кнопку, переключение на предыдущий канал в списке
        self.player.current_channel_index = (self.player.current_channel_index - 1) % len(self.player.channels)
        self.player.current_channel = self.player.channels[self.player.current_channel_index]
        self.channel_label.setText("<font color='yellow'>◄   </font>" + self.player.current_channel[1])

    def play_next_channel(self):  # Метод для обработки события нажатия на кнопку, переключение на следующий канал в списке
        self.player.current_channel_index = (self.player.current_channel_index + 1) % len(self.player.channels)
        self.player.current_channel = self.player.channels[self.player.current_channel_index]
        self.channel_label.setText(self.player.current_channel[1] + "<font color='yellow'>   ►</font>")

    def onActionTriggered(self):  # Код, который выполняется при нажатии на Apply или Ok
        self.player.reload_channels()
        self.play_next_channel()

    # Метод проверки изменения файла error.log
    def show_error_dialog(self):  # Показать всплывающее окно с предложением отправить файл ошибки
        msg = QtWidgets.QMessageBox()
        msg.setText("При предыдущем использовании программы - произошла ошибка.")
        msg.setInformativeText(
            "Пожалуйста, если Вам не трудно, найдите файл 'error.log' в директории программы, отправьте его на "
            "easydiagnostik@gmail.com для анализа ошибок и удалите файл. Спасибо за содействие")
        msg.setStyleSheet("font-size: 12pt;")
        msg.setWindowTitle("Ошибка")
        msg.exec_()

    def check_log_file_size(self):
        try:
            current_size = os.path.getsize(LOG_FILE_PATH)
            previous_size = self.read_previous_size()
            if previous_size is not None and current_size != previous_size:
                self.show_error_dialog()
            self.save_current_size(current_size)
        except FileNotFoundError:
            # Если файл не найден, сохраняем текущий размер как 0
            self.save_current_size(0)

    def read_previous_size(self):
        try:
            with open('size', 'r') as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return None

    def save_current_size(self, size):
        with open('size', 'w') as f:
            f.write(str(size))

    def update_tray_tooltip(self, state):  # Обновление подсказки иконки в системном трее в зависимости от состояния плеера
        print("Вызвано обновление иконки с состоянием:", state)
        if state == "Playing":
            icon_path = resource_path("green_circle.png")
            self.tray_icon.setToolTip("Playing online")
            self.tray_icon.setIcon(QtGui.QIcon(icon_path))
            self.channel_label.setText(self.player.current_channel[1] + "<font color='green'>   ✔</font>")

        elif state == "Stopped":
            icon_path = resource_path("red_circle.png")
            self.tray_icon.setToolTip("Stopped online")
            self.tray_icon.setIcon(QtGui.QIcon(icon_path))
            self.channel_label.setText(self.player.current_channel[1] + "<font color='red'>   ■</font>")

        elif state == "NoChannel":
            icon_path = resource_path("red_circle.png")
            self.tray_icon.setToolTip("Канал который Вы выбрали не работает или у Вас нет ни одного рабочего канала, измените список каналов")
            self.tray_icon.setIcon(QtGui.QIcon(icon_path))

        elif state == "NoConnect":
            icon_path = resource_path("noconnect.png")
            self.tray_icon.setToolTip("Нет интернет соединения")
            self.tray_icon.setIcon(QtGui.QIcon(icon_path))
            self.channel_label.setText("<font color='red'>НЕТ ИНТЕРНЕТ СОЕДИНЕНИЯ</font>")

        elif state == "stream_not_available":
            icon_path = resource_path("red_circle.png")
            self.tray_icon.setToolTip("Эта трансляция недоступна")
            self.tray_icon.setIcon(QtGui.QIcon(icon_path))

        elif state == "video_unavailable":
            icon_path = resource_path("red_circle.png")
            self.tray_icon.setToolTip("Ссылка неверна или эта трансляция недоступна")
            self.tray_icon.setIcon(QtGui.QIcon(icon_path))
        elif state == "Started":
            self.channel_label.setText(self.player.current_channel[1] + "<font color='green'>   ⌛</font>")

    def show_toast(self, message, duration=5000):  # Метод для отображения всплывающего уведомления с сообщением
        if not hasattr(self, 'toast_label'):
            self.toast_label = QLabel(self.control_window)
            self.toast_label.setStyleSheet(f"""
                   background-color: rgba(0, 0, 0, 180);
                   color: white;
                   padding: {self.padding}px;
                   border-radius: {self.border_radius}px;
                   font-size: {self.font_size}pt;
               """)
            self.toast_label.setAlignment(Qt.AlignCenter)
            self.toast_label.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        self.toast_label.setText(message)
        self.toast_label.adjustSize()  # Adjust size to fit the text
        self.toast_label.move(self.control_window.geometry().center() - self.toast_label.rect().center() - QPoint(0,
                                                                                                                  self.control_window.height() // 2))
        self.toast_label.show()
        QtCore.QTimer.singleShot(duration, self.toast_label.hide)

    def show_control_window_temporarily(self):  # Показываем окно
        x, y = self.pos_cursor()
        self.control_window.move(x - 150, y -150)
        self.control_window.show()

    def on_press(self, key):
        # Список клавиш, которые мы хотим отслеживать
        monitored_keys = [
            Key.media_play_pause, Key.media_next, Key.media_previous,
            Key.media_volume_up, Key.media_volume_down  # Добавляем 'j' как медиа клавишу стоп
        ]

        if key in monitored_keys:
           print(f'Специальная клавиша {key} нажата')
           self.handle_media_key(key)  # Обработка медиа-клавиш

    def handle_media_key(self, key):
        if key == Key.media_play_pause:
            print("Управление медиа: Воспроизведение/Пауза")
            self.show_control_window_temporarily()
            if self.player.current_state in ["Stopped", "Paused", "Next"]:
                self.player.run()  # Corrected, no arguments passed
            else:
                self.player.player.pause()
                self.player.update_state("Paused")
                self.channel_label.setText(self.player.current_channel[1] + "<font color='yellow'>   ||</font>")

        elif key == Key.media_next:
            print("Управление медиа: Следующий трек")
            self.show_control_window_temporarily()
            self.player.update_state("Next")
            self.play_next_channel()
        elif key == Key.media_previous:
            print("Управление медиа: Предыдущий трек")
            self.show_control_window_temporarily()
            self.player.update_state("Next")
            self.play_previous_channel()
        elif key == Key.media_volume_up:
            print("Управление громкостью: Увеличить")
            self.show_control_window_temporarily()
            current_volume = self.volume_slider.value()
            new_volume = min(current_volume + 2, 100)  # Увеличиваем на 5, но не выше 100
            self.volume_slider.setValue(new_volume)
        elif key == Key.media_volume_down:
            print("Управление громкостью: Уменьшить")
            self.show_control_window_temporarily()
            current_volume = self.volume_slider.value()
            new_volume = max(current_volume - 2, 0)  # Уменьшаем на 5, но не ниже 0
            self.volume_slider.setValue(new_volume)

    def start_listener(self):
        def run_listener():
            with Listener(on_press=self.on_press) as listener:
                listener.join()

        # Запуск слушателя в отдельном потоке
        listener_thread = threading.Thread(target=run_listener)
        listener_thread.daemon = True  # Установка потока как "демона" позволяет Python завершить программу, не дожидаясь завершения потока
        listener_thread.start()

    def pos_cursor(self):
        cursor_position = QtGui.QCursor.pos()
        return cursor_position.x(), cursor_position.y()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)  # Создание экземпляра приложения PyQt5

    loading_window = LoadWindow()  # запуск окна логотипа
    loading_window.show()

    app.setQuitOnLastWindowClosed(False)  # Это предотвратит закрытие приложения при закрытии всех окон
    w = SystemTrayApp()  # Создание экземпляра главного виджета приложения.
    sys.exit(app.exec_())  # Запуск цикла обработки событий приложения и выход по завершению.
