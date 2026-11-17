import pandas as pd
from sqlalchemy import create_engine
from Options import get_connection_string
from Update import get_current_version, get_update_date


# Получает список логинов пользователей и сохраняет таблицу ползователей в переменную LoginUser
def get_login_list():
    sql = get_connection_string()
    engine = create_engine(sql)
    sql = ("Select `Name`,`Password`,`Access`,`Fname`,`PName`,`NName`, `BarCodeData`,`eKey`,`Role`,`Допуск` from "
           "`пользователи`")
    df = pd.read_sql_query(sql, engine)
    LoginUser.LoginList = df
    return df['Name']


# Заполняет комбо бокс значениями из списка
def fill_list(dpg, cmb):
    list_1 = get_login_list().tolist()
    dpg.configure_item(cmb, items=list_1)


# Возвращает значение True если пароль совпадает с паролем в БД
def is_login_user(login, password):
    if login is not None and password is not None:
        temp = LoginUser.LoginList[LoginUser.LoginList['Name'] == login]
        print(temp['Name'].to_string(index=False))
        if len(temp) > 0:
            if temp['Password'].to_string(index=False) == password:
                LoginUser.login.append(temp['Name'].to_string(index=False))
                LoginUser.login.append(temp['Допуск'].to_string(index=False))
                LoginUser.login.append(temp['Role'].to_string(index=False))
                LoginUser.login.append(temp['Fname'].to_string(index=False))
                LoginUser.login.append(temp['PName'].to_string(index=False))
                LoginUser.login.append(temp['NName'].to_string(index=False))
                print("Login TRUE")
                return True
            else:
                return False
        else:
            return False


# Возвращает True если личный  идентификатор находится в базе данных
def is_barCode_exist(barcode):
    temp = LoginUser.LoginList[LoginUser.LoginList['BarCodeData'] == barcode]
    print(temp)
    if len(temp) > 0:
        print(temp['Name'].to_string(index=False))
        LoginUser.login.append(temp['Name'].to_string(index=False))
        LoginUser.login.append(temp['Допуск'].to_string(index=False))
        LoginUser.login.append(temp['Role'].to_string(index=False))
        LoginUser.login.append(temp['Fname'].to_string(index=False))
        LoginUser.login.append(temp['PName'].to_string(index=False))
        LoginUser.login.append(temp['NName'].to_string(index=False))
        print("Login TRUE")
        return True
    else:
        return False


# Добавляет окно с именем пользователя
def add_login_window(dpg):
    screen_width = dpg.get_viewport_width()
    # Вычисление позиций для центрирования окна
    pos_x = (screen_width - 400)
    with dpg.window(label='Пользователь', tag="user_login", width=350, height=15, pos=[pos_x, 30]):
        dpg.add_text(str(LoginUser.login[3]) + " " + str(LoginUser.login[5]) + " " + str(LoginUser.login[1]))
        dpg.add_text(f'Версия {get_current_version()} Дата обновления {get_update_date()}')


class LoginUser:
    LoginList = None
    login = []
