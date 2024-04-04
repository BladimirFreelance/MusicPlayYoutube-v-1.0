import time
import vlc
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import QCoreApplication
from yt_dlp import YoutubeDL
import sys
import os


# Функция для определения текущего пути к ресурсам
def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

class SystemTrayApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.initTrayIcon()

    def initTrayIcon(self):
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        self.tray_icon.setIcon(QtGui.QIcon(resource_path("Design.png")))

        quit_action = QtWidgets.QAction("Exit", self)
        quit_action.triggered.connect(QCoreApplication.instance().quit)

        tray_menu = QtWidgets.QMenu()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def play_youtube_live(self, url):
        ydl_opts = {
            'format': 'bestaudio',
            'quiet': True,
            'no_warnings': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            audio_url = info_dict.get('url', None)
            if audio_url:
                player = vlc.MediaPlayer(audio_url)
                player.play()
                while player.is_playing():
                    time.sleep(1)  # Пауза между проверками состояния проигрывателя
            else:
                print("Ошибка: не удалось получить URL потока.")

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    # Создание экземпляра приложения, не показывая окно
    w = SystemTrayApp()
    w.hide()
    # Пример URL трансляции; замените на актуальный
    youtube_live_url = "https://www.youtube.com/live/zYFel2Ch4YI?si=_4ATIavgG2tK06XB"
    w.play_youtube_live(youtube_live_url)
    sys.exit(app.exec_())