# The sources live in the classic bring-up project; rig.h picks the ESP32-S3 pins, link transport and streams.
set(src "${CMAKE_CURRENT_LIST_DIR}/../../bringup-esp32/main")
idf_component_register(SRCS "${src}/bringup_main.c" "${src}/link_mode.c" "${src}/rz_link.c" "${src}/rz_decim.c"
                            "${src}/rz_drdy.c"
                       INCLUDE_DIRS "${src}"
                       PRIV_REQUIRES esp_driver_spi esp_driver_gpio esp_driver_usb_serial_jtag esp_timer spi_flash
                                     esp_hw_support esp_rom esp_system heap log)
# D-016 FIR: no fused multiply-add, so adc_dec matches rezonating_ml (ml/src/rezonating_ml/dsp.py, "Build requirement")
set_source_files_properties("${src}/rz_decim.c" PROPERTIES COMPILE_OPTIONS "-ffp-contract=off")
