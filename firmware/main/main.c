// Rezonating node firmware - entry point.
// Step 0: prove the board is the right variant (16 MB flash, 8 MB PSRAM).
// Next: ADS131M04 driver in components/acquire (see firmware/README.md).

#include <inttypes.h>
#include <stdio.h>

#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_system.h"

static const char *TAG = "rzn";

#define RZN_FW_VERSION "0.0.1"

void app_main(void)
{
    esp_chip_info_t chip;
    esp_chip_info(&chip);

    uint32_t flash_size = 0;
    esp_flash_get_size(NULL, &flash_size);

    size_t psram = heap_caps_get_total_size(MALLOC_CAP_SPIRAM);

    ESP_LOGI(TAG, "Rezonating node fw %s", RZN_FW_VERSION);
    ESP_LOGI(TAG, "cores=%d rev=%d flash=%" PRIu32 " MB psram=%u KB",
             chip.cores, chip.revision, flash_size / (1024 * 1024),
             (unsigned)(psram / 1024));

    if (psram < 4 * 1024 * 1024) {
        ESP_LOGE(TAG, "PSRAM missing or too small: wrong board variant? Need N16R8.");
    }
}
