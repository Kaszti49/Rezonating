idf_component_register(SRCS "bringup_main.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_spi esp_driver_gpio esp_timer spi_flash esp_hw_support esp_rom)
