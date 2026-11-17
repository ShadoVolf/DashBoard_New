from Pribory.Network_Analyzer.VNA import VNA
from Pribory.Network_Analyzer.VNA_Data import VNA_DATA
from RT.RT_TECH_Parameters.RT_Data import RT_DATA


def vna_test(data):
    for index, row in data.iterrows():
        if row['Type'] == 'Векторный анализатор цепей':
            print(row['Name'])
            vna = VNA(vna_type=row['Name'])
            status, serial = vna.test()
            data.loc[index, 'Status'] = status
            data.loc[index, 'SerialN'] = serial
            VNA_DATA.set_vna(row['Name'], serial, status)
    return data


def start_vna():
    vna = VNA(vna_type='OBZOR 304')

