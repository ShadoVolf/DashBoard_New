from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Control_Manual import create_control_panel_rt_manual_window
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Control_Panel import create_control_panel_rt_window
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Control_panel_regim import create_control_panel_rt_manual__regime_window
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Freq_Window import create_rt_measure_freq_window
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Measure_Window import create_rt_measure_power_window
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Select_Numbers import create_numbers_rt_window
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Select_msk_window import create_nom_rt_window
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Specification_Window import create_spc_rt_window
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Test_Window import create_start_test_rt_window
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_View_Status import LampController


def create_rt_windows(dpg):
    lamp_controller = LampController(dpg)
    lamp_controller.create_window()
    create_rt_measure_power_window(dpg)
    create_nom_rt_window(dpg)
    create_numbers_rt_window(dpg)
    create_spc_rt_window(dpg,0)
    create_rt_measure_freq_window(dpg)
    create_control_panel_rt_window(dpg)
    create_control_panel_rt_manual_window(dpg)
    create_control_panel_rt_manual__regime_window(dpg)
    create_start_test_rt_window(dpg)