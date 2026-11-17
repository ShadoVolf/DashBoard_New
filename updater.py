import ctypes
import os
import sys
import time
import requests
import hashlib
import shutil
import subprocess
from colorama import Fore, Style, init

# Инициализация цветного вывода
init(autoreset=True)


def print_color(text, color=Fore.WHITE, end='\n'):
    print(color + text + Style.RESET_ALL, end=end)


def check_write_access(file_path):
    """Проверка прав на запись в целевой файл/директорию"""
    if os.path.exists(file_path):
        return os.access(file_path, os.W_OK)
    return os.access(os.path.dirname(file_path), os.W_OK)


def download_file(url, file_path):
    try:
        response = requests.get(url, stream=True)
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        start_time = time.time()

        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Расчет прогресса и скорости
                    elapsed_time = time.time() - start_time
                    elapsed_time = elapsed_time or 0.001  # Защита от деления на ноль

                    progress = downloaded / total_size * 100 if total_size > 0 else 0
                    speed = downloaded / elapsed_time / 1024  # KB/s

                    # Отрисовка прогресс-бара
                    sys.stdout.write('\r')
                    sys.stdout.write(Fore.CYAN + "[Download] " + Fore.YELLOW + "[")
                    pos = int(50 * progress / 100)
                    sys.stdout.write(Fore.GREEN + "=" * pos)
                    sys.stdout.write(Fore.YELLOW + ">" + " " * (49 - pos) + "] ")
                    sys.stdout.write(Fore.WHITE + f"{progress:.1f}% ")
                    sys.stdout.write(Fore.MAGENTA + f"({downloaded / 1e6:.2f} MB / {total_size / 1e6:.2f} MB) ")
                    sys.stdout.write(Fore.BLUE + f"{speed:.2f} KB/s")
                    sys.stdout.flush()

        print()
        return True
    except Exception as e:
        print_color(f"\nDownload error: {e}", Fore.RED)
        return False


def verify_file(file_path, expected_md5):
    try:
        print_color("[Verify] Checking file integrity...", Fore.CYAN)
        md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                md5.update(chunk)
        return md5.hexdigest() == expected_md5
    except Exception as e:
        print_color(f"Verification error: {e}", Fore.RED)
        return False
def hide_console():
    """Скрыть консольное окно."""
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)  # 0 = SW_HIDE

def show_console():
    """Показать консольное окно."""
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 5)

def main():
    if len(sys.argv) != 4:
        print_color("Usage: updater.exe <target_exe> <url> <md5>", Fore.RED)
        return
    show_console()
    target_exe = os.path.abspath(sys.argv[1])
    download_url = sys.argv[2]
    expected_md5 = sys.argv[3]
    temp_file = os.path.join(os.environ['TEMP'], os.path.basename(target_exe) + ".tmp")

    try:
        # Проверка прав доступа
        if not check_write_access(target_exe):
            print_color("No write permissions for target location!", Fore.RED)
            return

        # Шаг 1: Скачивание
        print_color("[1/3] Starting download...", Fore.GREEN)
        if not download_file(download_url, temp_file):
            return

        # Шаг 2: Верификация
        print_color("[2/3] Verifying update...", Fore.GREEN)
        if not verify_file(temp_file, expected_md5):
            print_color("File verification failed!", Fore.RED)
            return

        # Шаг 3: Применение обновления
        print_color("[3/3] Applying update...", Fore.GREEN)
        for attempt in range(5):
            try:
                # Удаление старой версии
                if os.path.exists(target_exe):
                    os.remove(target_exe)

                # Копирование новой версии
                shutil.copy2(temp_file, target_exe)
                os.remove(temp_file)

                # Запуск обновленного приложения
                print_color("Update successful! Launching...", Fore.GREEN)
                subprocess.Popen([target_exe])
                return
            except (PermissionError, IOError, OSError) as e:
                print_color(f"Retrying... ({attempt + 1}/5) Error: {e}", Fore.YELLOW)
                time.sleep(2)

        print_color("Failed to apply update after 5 attempts", Fore.RED)
    except Exception as e:
        print_color(f"Critical error: {e}", Fore.RED)
    finally:
        # Очистка временных файлов
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception as e:
                print_color(f"Failed to clean temp file: {e}", Fore.RED)


if __name__ == "__main__":
    main()
