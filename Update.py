# main.py (основная программа)
import sys
import os
import hashlib
import mysql.connector
import requests
import subprocess
from packaging import version

from Options import parse_connection_string

version_ = '1.9.3'
update_date = '25.11.2026'


@staticmethod
def get_current_version():
    """
    Возвращает текущую версию
    :return:
    """
    return version_  # Текущая версия приложения

# Возвращает
@staticmethod
def get_update_date():
    """
    Возвращает дату обновления ПО
    :return:
    """
    return update_date


def get_current_md5():
    exe_path = sys.executable
    with open(exe_path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def check_for_updates():
    try:
        params = parse_connection_string()
        conn = mysql.connector.connect(**params)
        cursor = conn.cursor()
        cursor.execute("SELECT `Version`, `MD5`, URL FROM `softversion` where `Name`='Measure' LIMIT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            db_version, db_md5, db_url = result
            current_version = get_current_version()

            if (version.parse(db_version) > version.parse(current_version) or
                    get_current_md5() != db_md5):
                return db_url, db_md5
        return None
    except Exception as e:
        print(f"Error checking updates: {e}")
        return None


def download_update(url):
    try:
        response = requests.get(url, stream=True)
        temp_path = os.path.join(os.environ['TEMP'], 'update_temp.exe')
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return temp_path
    except Exception as e:
        print(f"Download failed: {e}")
        return None


def verify_update(file_path, expected_md5):
    with open(file_path, 'rb') as f:
        file_hash = hashlib.md5(f.read()).hexdigest()
    return file_hash == expected_md5


def start_updater_1(new_file_path):
    # Путь к updater.exe в той же директории
    updater_exe = os.path.join(os.path.dirname(sys.executable), "Updater.exe")
    print(updater_exe)

    if not os.path.exists(updater_exe):
        print("Error: Updater.exe not found!")
        return

    try:
        subprocess.Popen([updater_exe, sys.executable, new_file_path])
        sys.exit()
    except Exception as e:
        print(f"Failed to start updater: {e}")


def start_updater(url, expected_md5):
    updater_exe = os.path.join(os.path.dirname(sys.executable), "updater.exe")
    print(updater_exe)
    target_exe = sys.executable
    print(target_exe)

    if not os.path.exists(updater_exe):
        print("Error: updater.exe not found!")
        return

    try:
        subprocess.Popen([updater_exe, target_exe, url, expected_md5])
        sys.exit()
    except Exception as e:
        print(f"Failed to start updater: {e}")
