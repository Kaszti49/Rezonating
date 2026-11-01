idf_component_register(SRCS "bringup_main.c" "link_mode.c" "rz_link.c" "rz_decim.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_spi esp_driver_gpio esp_driver_uart esp_timer spi_flash
                                     esp_hw_support esp_rom esp_system heap log)
# D-016 FIR: no fused multiply-add, so adc_dec matches rezonating_ml (ml/src/rezonating_ml/dsp.py, "Build requirement")
set_source_files_properties(rz_decim.c PROPERTIES COMPILE_OPTIONS "-ffp-contract=off")
