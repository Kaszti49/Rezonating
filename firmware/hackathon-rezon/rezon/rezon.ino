/*
  REZON fall detector - firmware for the ESP32-S3-DevKitC-1 (jumper build, see Rezon_Wiring_Guide_Jumpers.html)
  ---------------------------------------------------------------------------------------------------------------
  Arduino IDE: board "ESP32S3 Dev Module", esp32 core 3.x by Espressif. No extra libraries.
  USB: use the DevKit's "UART" USB-C port. Serial runs at 460800 baud (same as the practice sketch).

  Pins:   SPI SCK 12, MISO 13, MOSI 14, ADC CS 11, clock-chip CS 9, DRDY 10, ADC reset 8      (MikroE ADC 15 Click)
          I2S BCK 4, LCK 5, DIN 6 (PCM5102A -> ZK-502M -> speaker)     button 7 (internal pull-up, low = pressed)
          LED data 15 (one WS2812B)     modem PWRKEY 16, TX 17 -> SIM RXD, RX 18 <- SIM TXD (SIM868, 115200)

  Tasks:  sampling (highest priority): waits for DRDY, reads the ADC, runs the detection core. Nothing else runs in it.
          audio and modem: their own tasks, so a clip or an AT command can never stall the sampling.
          loop(): serial output and commands, alarm sequence, button, LED.

  Serial protocol: src/core/rezon_proto.h. Pages: firmware/ui/train.html (tuning, recording) and live.html (stage).
  Commands (end with newline):
    G<0..7>            ADC gain 1x..128x (default 2 = 4x)        R            restart the ADC
    !get               print all settings as P,<name>,<value>    !set <name> <value>     !save  (store in flash)
    !profile stage|home                                          !stream 0|1  raw D lines off / on
    !test              run the alarm sequence now (it DIALS)     !reset       back to watching, hang up
    !modem             SIM, signal, registration                 !at <cmd>    raw AT command to the modem
    !pwr               pulse the modem's PWRKEY now (switches it on, or OFF if it was on)
    !pwrhold [s]       hold GPIO16 (PWRKEY) high for s seconds (default 15) to measure it; reports the pin's own level
    !play q|c          play the question / calling sound (no alarm, no call)
    !tone [Hz] [s]     steady test tone (default 440 Hz, 3 s)       !stop        stop the sound
    !cal               floor calibration (phase 4, not written yet)
*/
#include <SPI.h>
#include <Preferences.h>
#include <ESP_I2S.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <driver/gpio.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include "src/core/rezon_core.h"
#include "src/core/rezon_proto.h"
#include "src/core/rezon_alarm.h"
#if __has_include("secrets.h")
#include "secrets.h"            // #define REZON_PHONE "+36..."   This file is git-ignored: the number never goes into git.
#else
#define REZON_PHONE ""          // no secrets.h: copy secrets.example.h to secrets.h and put the number in. Until then: no call.
#endif

using namespace rezon;

// ---------------------------------------------------------------- pins
#define PIN_SCK 12
#define PIN_MISO 13
#define PIN_MOSI 14
#define PIN_CS 11
#define PIN_CS2 9
#define PIN_DRDY 10
#define PIN_RST 8
#define PIN_BCK 4
#define PIN_LCK 5
#define PIN_DIN 6
#define PIN_BTN 7
#define PIN_LED 15
#define PIN_PWRKEY 16
#define PIN_SIM_TX 17
#define PIN_SIM_RX 18
#define BAUD 460800
#define SIM_BAUD 115200
// ADC input the SM-24 is screwed into. The wiring guide says CH1, but the CH1 terminal on our Click is missing a screw,
// so the geophone sits on CH2 (2026-11-14). D lines are "D,<geophone>,<other channel>" either way.
#define GEO_CH 2

// ---------------------------------------------------------------- shared state
static Detector det;                      // only the sampling task touches it, others go through detMux
static Alarm alarmSeq;                    // only loop() touches it
static SemaphoreHandle_t detMux, drdySem;
static QueueHandle_t noteQ, audioQ, modemQ, modemResQ;
static Preferences prefs;
static volatile bool adcRunning = false, streamOn = true, reqClearFall = false;
static volatile uint32_t sampleCount = 0, crcErrors = 0, dropped = 0;
static uint8_t gainCode = 2;
static int volumePct = 10;                // voice level, % of full scale. Start low: the amp has its own volume knob.
static int chimeOn = 1;                   // play the question sound once at power-up ("I'm on"; also a speaker test on battery)

// ---------------------------------------------------------------- Bluetooth LE link (Nordic UART service), the pages' wireless alternative to USB
// Every text line goes to USB and, while a BLE client is connected, into bleBuf; loop() sends bleBuf in MTU-sized notifications.
// Raw samples are too many for BLE as D lines: they travel as "B,<base64>" lines, 20 geophone samples (3 bytes each, big-endian) per line.
#define NUS_SVC "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_RX  "6e400002-b5a3-f393-e0a9-e50e24dcca9e"    // page -> Rezon (write)
#define NUS_TX  "6e400003-b5a3-f393-e0a9-e50e24dcca9e"    // Rezon -> page (notify)
static BLECharacteristic *bleTx = nullptr; static BLEServer *bleSrv = nullptr;
static volatile bool bleConn = false; static volatile uint16_t bleMtu = 23; static volatile uint32_t bleDropped = 0;
static portMUX_TYPE bleMux = portMUX_INITIALIZER_UNLOCKED;
static uint8_t bleBuf[12288]; static volatile uint16_t bleHead = 0, bleTail = 0;            // text out (ring)
static char bleIn[256]; static volatile uint16_t bleInHead = 0, bleInTail = 0;              // commands in (ring)
static void bleQueue(const uint8_t *d, size_t n) {
  if (!bleConn || !n) return;
  portENTER_CRITICAL(&bleMux);
  const uint16_t used = (uint16_t)((bleHead - bleTail + sizeof bleBuf) % sizeof bleBuf);
  if (used + n >= sizeof bleBuf - 1) bleDropped += n;                                          // whole write dropped, never half a line
  else for (size_t i = 0; i < n; i++) { bleBuf[bleHead] = d[i]; bleHead = (bleHead + 1) % sizeof bleBuf; }
  portEXIT_CRITICAL(&bleMux);
}
class Tee : public Print {                                                                     // USB + BLE
 public:
  size_t write(uint8_t c) override { Serial.write(c); bleQueue(&c, 1); return 1; }
  size_t write(const uint8_t *b, size_t n) override { Serial.write(b, n); bleQueue(b, n); return n; }
};
static Tee out;
class BleSrvCb : public BLEServerCallbacks {
  void onConnect(BLEServer *) override { portENTER_CRITICAL(&bleMux); bleHead = bleTail = 0; portEXIT_CRITICAL(&bleMux); bleMtu = 23; bleConn = true; }
  void onDisconnect(BLEServer *s) override { bleConn = false; s->startAdvertising(); }
};
class BleRxCb : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    auto v = c->getValue();
    for (size_t i = 0; i < v.length(); i++) { const uint16_t nx = (bleInHead + 1) % sizeof bleIn; if (nx == bleInTail) break; bleIn[bleInHead] = v[i]; bleInHead = nx; }
  }
};
static void bleStart() {
  BLEDevice::init("REZON"); BLEDevice::setMTU(247);
  bleSrv = BLEDevice::createServer(); bleSrv->setCallbacks(new BleSrvCb());
  BLEService *s = bleSrv->createService(NUS_SVC);
  bleTx = s->createCharacteristic(NUS_TX, BLECharacteristic::PROPERTY_NOTIFY); bleTx->addDescriptor(new BLE2902());
  BLECharacteristic *rx = s->createCharacteristic(NUS_RX, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  rx->setCallbacks(new BleRxCb());
  s->start();
  BLEAdvertising *a = BLEDevice::getAdvertising(); a->addServiceUUID(NUS_SVC); a->setScanResponse(true); BLEDevice::startAdvertising();
}
static void bleSend(uint32_t now) {                                                            // from loop(): paced notifications
  static uint32_t last = 0;
  if (!bleConn || !bleTx || now - last < 8) return;
  last = now;
  { const uint16_t m = bleSrv->getPeerMTU(bleSrv->getConnId()); if (m >= 23) bleMtu = m; }
  const int chunk = bleMtu > 23 ? (bleMtu - 3 > 244 ? 244 : bleMtu - 3) : 20;
  for (int k = 0; k < 4; k++) {
    uint8_t tmp[244]; int n = 0;
    portENTER_CRITICAL(&bleMux);
    while (n < chunk && bleTail != bleHead) { tmp[n++] = bleBuf[bleTail]; bleTail = (bleTail + 1) % sizeof bleBuf; }
    const uint16_t left = (uint16_t)((bleHead - bleTail + sizeof bleBuf) % sizeof bleBuf);
    portEXIT_CRITICAL(&bleMux);
    if (!n) break;
    bleTx->setValue(tmp, n); bleTx->notify();
    if (left < 1024) break;                                                                    // more than one per tick only to catch up
  }
}
static void blePackSample(int32_t c) {                                                         // 20 samples -> one B line
  static uint8_t blk[60]; static int k = 0;
  if (!bleConn) { k = 0; return; }
  blk[3 * k] = (uint8_t)(c >> 16); blk[3 * k + 1] = (uint8_t)(c >> 8); blk[3 * k + 2] = (uint8_t)c;
  if (++k < 20) return;
  k = 0;
  static const char *A = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  char line[2 + 80 + 2]; int j = 0; line[j++] = 'B'; line[j++] = ',';
  for (int i = 0; i < 60; i += 3) { const uint32_t v = (blk[i] << 16) | (blk[i + 1] << 8) | blk[i + 2]; line[j++] = A[v >> 18]; line[j++] = A[(v >> 12) & 63]; line[j++] = A[(v >> 6) & 63]; line[j++] = A[v & 63]; }
  line[j++] = '\n';
  bleQueue((const uint8_t *)line, j);
}

// raw samples for the D lines: written by the sampling task, read by loop()
static int32_t ring[2048][2]; static volatile uint16_t ringHead = 0, ringTail = 0;

// ---------------------------------------------------------------- ADC (ADS131M02 + LTC6903 clock), from practice/geophone_test
#define REG_ID 0x00
#define REG_CLOCK 0x03
#define REG_GAIN 0x04
#define CMD_RREG(a) (0xA000 | ((a) << 7))
#define CMD_WREG(a) (0x6000 | ((a) << 7))
#define CLOCK_1KSPS 0x0316                // both channels on, OSR 4096 -> 8.192 MHz / 2 / 4096 = 1000 samples/s, high resolution
static SPISettings adcSpi(2000000, MSBFIRST, SPI_MODE1), ltcSpi(1000000, MSBFIRST, SPI_MODE0);

static uint16_t crc16(const uint8_t *d, int n) {            // CCITT, poly 0x1021, init 0xFFFF
  uint16_t c = 0xFFFF;
  for (int i = 0; i < n; i++) { c ^= (uint16_t)d[i] << 8; for (int b = 0; b < 8; b++) c = (c & 0x8000) ? (c << 1) ^ 0x1021 : c << 1; }
  return c;
}
static int32_t s24(const uint8_t *p) { int32_t v = ((int32_t)p[0] << 16) | (p[1] << 8) | p[2]; return (v & 0x800000) ? v - 0x1000000 : v; }
static void frame(uint16_t cmd, uint16_t data, uint8_t *rx) {   // 4 words x 3 bytes: [command/response][ch1][ch2][crc]
  uint8_t tx[12] = { (uint8_t)(cmd >> 8), (uint8_t)cmd, 0, (uint8_t)(data >> 8), (uint8_t)data, 0, 0, 0, 0, 0, 0, 0 };
  SPI.beginTransaction(adcSpi); digitalWrite(PIN_CS, LOW);
  SPI.transferBytes(tx, rx, 12);
  digitalWrite(PIN_CS, HIGH); SPI.endTransaction();
}
static uint16_t readReg(uint8_t a) { uint8_t rx[12]; frame(CMD_RREG(a), 0, rx); frame(0, 0, rx); return (rx[0] << 8) | rx[1]; }
static void writeReg(uint8_t a, uint16_t v) { uint8_t rx[12]; frame(CMD_WREG(a), v, rx); frame(0, 0, rx); }
static void setGain(uint8_t g) {
  gainCode = g & 7; writeReg(REG_GAIN, (gainCode << 4) | gainCode);
  xSemaphoreTake(detMux, portMAX_DELAY); det.cfg.gain = 1 << gainCode; xSemaphoreGive(detMux);
  out.printf("# gain x%d (full scale +-%.1f mm/s)\n", 1 << gainCode, 1200.0 / (1 << gainCode) / 20.9);
}
static bool startAdc() {
  adcRunning = false; delay(5);
  digitalWrite(PIN_CS, HIGH); digitalWrite(PIN_CS2, HIGH);
  SPI.beginTransaction(ltcSpi); digitalWrite(PIN_CS2, LOW); SPI.transfer16((12 << 12) | (984 << 2) | 2); digitalWrite(PIN_CS2, HIGH); SPI.endTransaction();   // LTC6903 -> 8.192 MHz
  delay(5);
  digitalWrite(PIN_RST, LOW); delay(2); digitalWrite(PIN_RST, HIGH); delay(10);
  uint16_t id = readReg(REG_ID);
  out.printf("# ADS131M02 ID = 0x%04X (expect 0x22xx)\n", id);
  if ((id & 0xFF00) != 0x2200) { out.println("# ERROR: no ADC answer. Check 3V3/GND, SCK 12, MISO 13, MOSI 14, CS 11, CS2 9 (clock), RST 8."); return false; }
  writeReg(REG_CLOCK, CLOCK_1KSPS);
  setGain(gainCode);
  xSemaphoreTake(detMux, portMAX_DELAY); det.reset(); xSemaphoreGive(detMux);
  adcRunning = true;
  return true;
}
static void IRAM_ATTR onDrdy() { BaseType_t w = pdFALSE; xSemaphoreGiveFromISR(drdySem, &w); if (w) portYIELD_FROM_ISR(); }

static void samplingTask(void *) {
  uint8_t rx[12]; Note o;
  esp_task_wdt_add(nullptr);              // if this task ever hangs (e.g. inside the detector), the board restarts and says "WATCHDOG"
  for (;;) {
    esp_task_wdt_reset();
    if (xSemaphoreTake(drdySem, pdMS_TO_TICKS(20)) != pdTRUE && digitalRead(PIN_DRDY) != LOW) continue;
    if (!adcRunning) continue;
    frame(0, 0, rx);
    if (crc16(rx, 9) != (uint16_t)((rx[9] << 8) | rx[10])) { crcErrors++; continue; }      // a glitch never reaches the detector
    // c1 is always the GEOPHONE channel: the detector, the D lines, the pages and the replay tools all read it.
    const int32_t a1 = s24(rx + 3), a2 = s24(rx + 6);
    const int32_t c1 = GEO_CH == 2 ? a2 : a1, c2 = GEO_CH == 2 ? a1 : a2;
    const uint16_t h = ringHead, nx = (h + 1) & 2047;
    if (nx != ringTail) { ring[h][0] = c1; ring[h][1] = c2; ringHead = nx; } else dropped++;
    xSemaphoreTake(detMux, portMAX_DELAY);
    if (reqClearFall) { reqClearFall = false; det.clearFall(); }
    if (det.push(c1)) while (det.poll(o)) xQueueSend(noteQ, &o, 0);
    xSemaphoreGive(detMux);
    sampleCount++;
  }
}

// ---------------------------------------------------------------- audio (I2S -> PCM5102A). Placeholder tones until the voice clips arrive.
// Real clips: 16 kHz, 16-bit mono arrays in clips.h (CLIP_QUESTION / CLIP_CALLING), see NOTES.md.
#if __has_include("clips.h")
#include "clips.h"
#define HAVE_CLIPS 1
#else
#define HAVE_CLIPS 0
#endif
#define AUDIO_RATE 16000
static I2SClass i2s;
static volatile bool audioStop = false, audioOk = false;
static volatile float toneHz = 440.f; static volatile int toneMs = 3000;   // !tone
static void playSamples(const int16_t *pcm, uint32_t n) {
  int16_t out[256 * 2];
  for (uint32_t i = 0; i < n && !audioStop;) {
    int k = 0;
    for (; k < 256 && i < n; k++, i++) { const int16_t s = (int16_t)((int32_t)pcm[i] * volumePct / 100); out[2 * k] = s; out[2 * k + 1] = s; }   // same on left and right
    i2s.write((uint8_t *)out, k * 4);
  }
}
static void playTone(float hz, int ms, float decayMs) {
  int16_t out[256 * 2]; const int total = AUDIO_RATE * ms / 1000;
  for (int i = 0; i < total && !audioStop;) {
    int k = 0;
    for (; k < 256 && i < total; k++, i++) { const float a = expf(-(float)i / (decayMs * AUDIO_RATE / 1000.f)) * 32000.f * volumePct / 100.f; const int16_t s = (int16_t)(a * sinf(6.2831853f * hz * i / AUDIO_RATE)); out[2 * k] = s; out[2 * k + 1] = s; }
    i2s.write((uint8_t *)out, k * 4);
  }
}
static void audioTask(void *) {
  uint8_t clip;
  for (;;) {
    if (xQueueReceive(audioQ, &clip, portMAX_DELAY) != pdTRUE || !audioOk) continue;
    audioStop = false;
    if (clip == 4) {                                                                         // start-up chime: always two short neutral notes, never the voice
      playTone(659.26f, 160, 90); playTone(987.77f, 260, 140);
      int16_t z[64] = { 0 }; for (int i = 0; i < 20; i++) i2s.write((uint8_t *)z, sizeof z);
      continue;
    }
    if (clip == 3) {                                                                         // !tone: steady test tone
      playTone(toneHz, toneMs, 1e9f);
      int16_t z[64] = { 0 }; for (int i = 0; i < 20; i++) i2s.write((uint8_t *)z, sizeof z);
      continue;
    }
#if HAVE_CLIPS
    if (clip == 1) playSamples(CLIP_QUESTION, sizeof(CLIP_QUESTION) / 2); else playSamples(CLIP_CALLING, sizeof(CLIP_CALLING) / 2);
#else
    if (clip == 1) { playTone(659.26f, 450, 160); playTone(880.f, 700, 260); }              // question: E5 then A5
    else { for (int i = 0; i < 3; i++) { playTone(880.f, 180, 400); playTone(0, 120, 100); } }   // calling: three beeps
#endif
    int16_t z[64] = { 0 }; for (int i = 0; i < 20; i++) i2s.write((uint8_t *)z, sizeof z);   // flush with silence
  }
}

// ---------------------------------------------------------------- modem (SIM868), from practice/sim868_call_test
enum ModemCmd : uint8_t { MC_DIAL = 1, MC_HANGUP, MC_STATUS, MC_RAW, MC_PWR };
enum ModemRes : uint8_t { MR_DIAL_OK = 1, MR_DIAL_FAIL, MR_CALL_ENDED };
static volatile bool modemReady = false; static char rawAt[64];
static void mlog(const char *s) { out.printf("M,%s\n", s); }
static String atCmd(const char *cmd, uint32_t ms = 1000) {
  while (Serial1.available()) Serial1.read();
  Serial1.print(cmd); Serial1.print("\r");
  String rx; uint32_t t0 = millis();
  while (millis() - t0 < ms) {
    while (Serial1.available()) rx += (char)Serial1.read();
    if (rx.indexOf("OK\r") >= 0 || rx.indexOf("ERROR") >= 0) break;
    vTaskDelay(pdMS_TO_TICKS(10));
  }
  return rx;
}
static bool atOk(const char *cmd, uint32_t ms = 1000) { return atCmd(cmd, ms).indexOf("OK") >= 0; }
static bool modemAlive() { for (int i = 0; i < 4; i++) if (atOk("AT", 500)) return true; return false; }
static void modemStatus() {
  String s = atCmd("AT+CPIN?"); s.trim(); s.replace("\r\n", " "); mlog(s.c_str());       // READY = SIM ok. "SIM PIN": switch the PIN off in a phone.
  s = atCmd("AT+CSQ"); s.trim(); s.replace("\r\n", " "); mlog(s.c_str());                // signal 0..31, want >= 10
  s = atCmd("AT+CREG?"); s.trim(); s.replace("\r\n", " "); mlog(s.c_str());              // ,1 home  ,5 roaming  ,2 searching
  s = atCmd("AT+CBC"); s.trim(); s.replace("\r\n", " "); mlog(s.c_str());                // supply: about 4000 mV from the step-down
}
static bool registered() { String r = atCmd("AT+CREG?"); return r.indexOf(",1") >= 0 || r.indexOf(",5") >= 0; }
// Switch the modem on if it does not answer. A PWRKEY pulse TOGGLES its power, so it is only sent when AT gets no answer.
static bool modemPowerUp() {
  if (modemAlive()) return true;
  mlog("no answer, switching the modem on (PWRKEY 1.5 s)");
  digitalWrite(PIN_PWRKEY, HIGH); vTaskDelay(pdMS_TO_TICKS(1500)); digitalWrite(PIN_PWRKEY, LOW);
  vTaskDelay(pdMS_TO_TICKS(4000));
  uint32_t t0 = millis();
  while (millis() - t0 < 15000) if (modemAlive()) return true;
  mlog("STILL NO ANSWER: check 4.0 V at the PH2.0 plug (power bank + rocker on), board switch, TX 17 -> pin 1, RX 18 <- pin 2, GND, pin 36 = 3V3");
  return false;
}
// The SIM still has its PIN on. With REZON_SIM_PIN in secrets.h it is entered ONCE per boot: three wrong tries would lock the SIM (PUK).
static bool pinTried = false;
static void unlockSim() {
  String s = atCmd("AT+CPIN?", 3000);
  if (s.indexOf("READY") >= 0) { mlog("SIM ready"); return; }
  if (s.indexOf("SIM PIN") >= 0) {
#ifdef REZON_SIM_PIN
    if (pinTried) { mlog("SIM still asks for its PIN: not trying again (check REZON_SIM_PIN, then restart)"); return; }
    pinTried = true;
    const String c = String("AT+CPIN=\"") + REZON_SIM_PIN + "\"";
    mlog(atOk(c.c_str(), 5000) ? "SIM unlocked with the PIN from secrets.h" : "SIM PIN REJECTED: check REZON_SIM_PIN before the next restart (3 wrong = locked)");
#else
    mlog("SIM asks for its PIN: switch the PIN off in a phone, or put REZON_SIM_PIN in secrets.h");
#endif
    return;
  }
  s.trim(); s.replace("\r\n", " "); mlog((String("SIM: ") + s).c_str());              // e.g. no SIM inserted
}
static void modemSetup() { atOk("ATE0"); atOk("AT+CMEE=2"); atOk("AT+CLVL=90"); unlockSim(); }
static void modemTask(void *) {
  Serial1.begin(SIM_BAUD, SERIAL_8N1, PIN_SIM_RX, PIN_SIM_TX);
  vTaskDelay(pdMS_TO_TICKS(500));
  bool alive = modemPowerUp();
  if (alive) modemSetup();
  uint32_t lastCheck = millis(), lastPower = millis(); bool inCall = false; String urc;
  for (;;) {
    uint8_t cmd;
    if (xQueueReceive(modemQ, &cmd, pdMS_TO_TICKS(100)) == pdTRUE) {
      uint8_t res = 0;
      if (cmd == MC_DIAL) {
        if (!strlen(REZON_PHONE)) { mlog("no phone number: copy secrets.example.h to secrets.h"); res = MR_DIAL_FAIL; }
        else { String d = String("ATD") + REZON_PHONE + ";"; bool ok = atOk(d.c_str(), 8000); mlog(ok ? "dialling" : "dial failed"); res = ok ? MR_DIAL_OK : MR_DIAL_FAIL; inCall = ok; urc = ""; }
        xQueueSend(modemResQ, &res, 0);
      } else if (cmd == MC_HANGUP) { atOk("ATH", 3000); inCall = false; mlog("hung up"); }
      else if (cmd == MC_STATUS) modemStatus();
      else if (cmd == MC_PWR) {                                                              // on request: pulse PWRKEY now (toggles: on -> off too)
        mlog(modemAlive() ? "modem answers already: the pulse will switch it OFF" : "modem silent: pulsing PWRKEY to switch it on");
        digitalWrite(PIN_PWRKEY, HIGH); vTaskDelay(pdMS_TO_TICKS(1500)); digitalWrite(PIN_PWRKEY, LOW);
        mlog("PWRKEY pulse done (GPIO16 high 1.5 s), waiting up to 15 s for AT");
        vTaskDelay(pdMS_TO_TICKS(3000)); uint32_t t0 = millis(); bool ok = false;
        while (!ok && millis() - t0 < 12000) ok = modemAlive();
        alive = ok; mlog(ok ? "modem answers AT" : "no answer after the pulse: modem has no power (board switch?) or the pulse does not reach PWR (GPIO16 jumper)");
        if (ok) modemSetup();
      }
      else if (cmd == MC_RAW) { String s = atCmd(rawAt, 3000); s.trim(); s.replace("\r\n", " "); mlog(s.c_str()); }
    }
    while (Serial1.available()) urc += (char)Serial1.read();                               // unasked lines: NO CARRIER, BUSY, NO ANSWER, RING
    if (inCall && (urc.indexOf("NO CARRIER") >= 0 || urc.indexOf("BUSY") >= 0 || urc.indexOf("NO ANSWER") >= 0)) {
      inCall = false; mlog("call ended"); uint8_t res = MR_CALL_ENDED; xQueueSend(modemResQ, &res, 0);
    }
    if (urc.length() > 200) urc = urc.substring(urc.length() - 40);
    if (!inCall && millis() - lastCheck > 10000) {                                         // keep it ready: check every 10 s
      lastCheck = millis();
      if (!modemAlive()) {
        if (alive) { alive = false; mlog("modem stopped answering (power?)"); }
        if (modemReady) { modemReady = false; mlog("NOT ready to call"); }
        // got power later (rocker switched on after boot)? Try to switch it on, at most once a minute
        if (millis() - lastPower > 60000) { lastPower = millis(); if ((alive = modemPowerUp())) modemSetup(); }
        lastCheck = millis(); continue;
      }
      if (!alive) { alive = true; modemSetup(); }
      const bool r = registered();
      if (r != modemReady) { modemReady = r; mlog(r ? "registered, ready to call" : "NOT registered: check SIM (PIN), GSM antenna, signal"); if (!r) unlockSim(); }
    }
  }
}

// ---------------------------------------------------------------- settings
struct Param { const char *name; float *f; int *i; };
static Param params[] = {
  { "stepMin", &det.cfg.stepMin, nullptr }, { "impactMin", &det.cfg.impactMin, nullptr }, { "kOn", &det.cfg.kOn, nullptr }, { "kOff", &det.cfg.kOff, nullptr },
  { "scoreMin", &det.cfg.scoreMin, nullptr }, { "walkerMargin", &det.cfg.walkerMargin, nullptr }, { "stepRef", &det.cfg.stepRef, nullptr },
  { "simMin", &det.cfg.simMin, nullptr }, { "segMode", nullptr, &det.cfg.segMode }, { "ringMs", nullptr, &det.cfg.ringMs },
  { "impactWinMs", nullptr, &det.cfg.impactWinMs }, { "getUpSteps", nullptr, &det.cfg.getUpSteps }, { "volume", nullptr, &volumePct },
  { "rule", nullptr, &det.cfg.rule }, { "relMin", &det.cfg.relMin, nullptr }, { "holdMin", &det.cfg.holdMin, nullptr },
  { "holdFrac", &det.cfg.holdFrac, nullptr }, { "levelMs", nullptr, &det.cfg.levelMs }, { "levelGapMs", nullptr, &det.cfg.levelGapMs },
  { "chime", nullptr, &chimeOn },
};
static void printParams() {
  for (auto &p : params) { if (p.f) out.printf("P,%s,%.4g\n", p.name, *p.f); else out.printf("P,%s,%d\n", p.name, *p.i); }
  out.printf("P,profile,%s\n", alarmSeq.prof.name);
}
static bool setParam(const char *name, float v) {
  for (auto &p : params) if (!strcmp(p.name, name)) {
    xSemaphoreTake(detMux, portMAX_DELAY); if (p.f) *p.f = v; else *p.i = (int)lroundf(v); xSemaphoreGive(detMux);
    return true;
  }
  return false;
}
static void loadSettings() {
  prefs.begin("rezon", true);
  for (auto &p : params) { if (p.f) *p.f = prefs.getFloat(p.name, *p.f); else *p.i = prefs.getInt(p.name, *p.i); }
  gainCode = prefs.getUChar("gain", gainCode);
  if (prefs.getString("profile", "stage") == "home") alarmSeq.prof = PROFILE_HOME;
  prefs.end();
}
static void saveSettings() {
  prefs.begin("rezon", false);
  for (auto &p : params) { if (p.f) prefs.putFloat(p.name, *p.f); else prefs.putInt(p.name, *p.i); }
  prefs.putUChar("gain", gainCode); prefs.putString("profile", alarmSeq.prof.name);
  prefs.end(); out.println("# settings stored in flash");
}

// ---------------------------------------------------------------- LED and button
static void led(uint8_t r, uint8_t g, uint8_t b) { rgbLedWrite(PIN_LED, r, g, b); }
static void showLed(uint32_t now) {
  const bool blink = (now / 400) & 1;
  switch (alarmSeq.state()) {
    case A_WATCH: if (!adcRunning) led(blink ? 30 : 0, 0, blink ? 30 : 0);                 // magenta blink: ADC not running
                  else if (!modemReady) led(0, blink ? 24 : 6, blink ? 0 : 18);            // green / blue alternating: watching, modem not ready
                  else led(0, 24, 0); break;                                               // green: watching
    case A_GETUP: case A_ASK: case A_WAIT: led(40, 22, 0); break;                          // amber: asking
    case A_ANNOUNCE: case A_CALL: case A_INCALL: led(blink ? 50 : 14, 0, 0); break;        // red: calling
    case A_OK: case A_DONE: led(0, 40, 10); break;
    case A_FAIL: led(blink ? 50 : 0, 0, blink ? 0 : 30); break;                            // red / blue: the call failed
  }
}
static void pollButton(uint32_t now) {
  static bool stable = false, last = false; static uint32_t tChange = 0;
  const bool raw = digitalRead(PIN_BTN) == LOW;
  if (raw != last) { last = raw; tChange = now; }
  if (raw != stable && now - tChange >= 30) { stable = raw; alarmSeq.button(stable, now); if (stable) out.println("# button"); }   // 30 ms debounce
}

// ---------------------------------------------------------------- commands
// PWRKEY check: hold GPIO16 high for a while so it can be measured, and read the pad back (input stays enabled on this pin).
static uint32_t pwrHoldUntil = 0, pwrHoldNext = 0;
static void pwrHold(uint32_t now, int sec) {
  digitalWrite(PIN_PWRKEY, HIGH); pwrHoldUntil = now + sec * 1000UL; pwrHoldNext = now + 300;
  out.printf("# GPIO16 (PWRKEY) held HIGH for %d s: measure the ESP32 pin 16 and the SIM board PWR pin against GND now\n", sec);
}
static void pwrHoldTick(uint32_t now) {
  if (!pwrHoldUntil) return;
  if ((int32_t)(now - pwrHoldUntil) >= 0) { digitalWrite(PIN_PWRKEY, LOW); pwrHoldUntil = 0; out.println("# GPIO16 back LOW"); return; }
  if ((int32_t)(now - pwrHoldNext) >= 0) { pwrHoldNext = now + 2000; out.printf("# GPIO16 set HIGH, the pin itself reads %s\n", gpio_get_level((gpio_num_t)PIN_PWRKEY) ? "HIGH (ok)" : "LOW: something pulls it down (short to GND, or a load without resistor)"); }
}
static void handleLine(char *s, uint32_t now) {      // now = loop()'s clock: a fresh millis() here can be 1 ms ahead and make tick() skip a state
  if (s[0] == 'G' && s[1] >= '0' && s[1] <= '7' && !s[2]) { if (adcRunning) setGain(s[1] - '0'); return; }
  if (!strcmp(s, "R")) { startAdc(); return; }
  if (s[0] != '!') return;
  char *arg = strchr(s, ' '); if (arg) *arg++ = 0;
  if (!strcmp(s, "!get")) printParams();
  else if (!strcmp(s, "!set") && arg) { char *v = strchr(arg, ' '); if (v) { *v++ = 0; if (setParam(arg, atof(v))) printParams(); else out.printf("# unknown setting %s\n", arg); } }
  else if (!strcmp(s, "!save")) saveSettings();
  else if (!strcmp(s, "!profile") && arg) { alarmSeq.prof = !strcmp(arg, "home") ? PROFILE_HOME : PROFILE_STAGE; out.printf("P,profile,%s\n", alarmSeq.prof.name); }
  else if (!strcmp(s, "!stream") && arg) streamOn = atoi(arg) != 0;
  else if (!strcmp(s, "!test")) alarmSeq.test(now);
  else if (!strcmp(s, "!reset")) alarmSeq.reset(now);
  else if (!strcmp(s, "!modem")) { uint8_t c = MC_STATUS; xQueueSend(modemQ, &c, 0); }
  else if (!strcmp(s, "!pwr")) { uint8_t c = MC_PWR; xQueueSend(modemQ, &c, 0); }
  else if (!strcmp(s, "!pwrhold")) pwrHold(now, arg ? atoi(arg) : 15);
  // speaker test, no alarm and no call
  else if (!strcmp(s, "!play")) {
    uint8_t c = (arg && arg[0] == 'c') ? 2 : 1;
    if (!audioOk) out.println("# I2S did not start at boot: no sound possible");
    else { xQueueSend(audioQ, &c, 0); out.printf("# playing the %s sound, volume %d %%\n", c == 1 ? "question" : "calling", volumePct); }
  }
  else if (!strcmp(s, "!tone")) {
    float hz = 440.f, sec = 3.f;
    if (arg) { hz = atof(arg); const char *b = strchr(arg, ' '); if (b) sec = atof(b + 1); }
    toneHz = hz < 50.f ? 50.f : (hz > 8000.f ? 8000.f : hz); toneMs = (int)(constrain(sec, 0.2f, 30.f) * 1000);
    uint8_t c = 3;
    if (!audioOk) out.println("# I2S did not start at boot: no sound possible");
    else { audioStop = true; xQueueSend(audioQ, &c, 0); out.printf("# tone %.0f Hz for %.1f s, volume %d %%\n", (double)toneHz, toneMs / 1000.0, volumePct); }
  }
  else if (!strcmp(s, "!stop")) { audioStop = true; out.println("# sound stopped"); }
  else if (!strcmp(s, "!at") && arg) { strlcpy(rawAt, arg, sizeof rawAt); uint8_t c = MC_RAW; xQueueSend(modemQ, &c, 0); }
  else if (!strcmp(s, "!cal")) out.println("# calibration is phase 4: not written yet. Set stepMin / impactMin / stepRef by hand for now.");
  else out.printf("# unknown command %s\n", s);
}
static void pollSerial(uint32_t now) {
  static char buf[80]; static uint8_t n = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') { buf[n] = 0; if (n) handleLine(buf, now); n = 0; }
    else if (n < sizeof(buf) - 1) buf[n++] = c;
  }
  static char bbuf[80]; static uint8_t bn = 0;                                                  // the same commands over Bluetooth
  while (bleInTail != bleInHead) {
    const char c = bleIn[bleInTail]; bleInTail = (bleInTail + 1) % sizeof bleIn;
    if (c == '\n' || c == '\r') { bbuf[bn] = 0; if (bn) handleLine(bbuf, now); bn = 0; }
    else if (bn < sizeof(bbuf) - 1) bbuf[bn++] = c;
  }
}

// ---------------------------------------------------------------- Arduino
void setup() {
  Serial.setTxBufferSize(16384);
  Serial.begin(BAUD);
  pinMode(PIN_CS, OUTPUT); pinMode(PIN_CS2, OUTPUT); pinMode(PIN_RST, OUTPUT); pinMode(PIN_PWRKEY, OUTPUT);
  gpio_set_direction((gpio_num_t)PIN_PWRKEY, GPIO_MODE_INPUT_OUTPUT); gpio_set_drive_capability((gpio_num_t)PIN_PWRKEY, GPIO_DRIVE_CAP_3);   // read-back + full drive
  digitalWrite(PIN_CS, HIGH); digitalWrite(PIN_CS2, HIGH); digitalWrite(PIN_RST, HIGH); digitalWrite(PIN_PWRKEY, LOW);
  pinMode(PIN_DRDY, INPUT_PULLUP); pinMode(PIN_BTN, INPUT_PULLUP);
  led(10, 10, 10);
  detMux = xSemaphoreCreateMutex(); drdySem = xSemaphoreCreateBinary();
  noteQ = xQueueCreate(16, sizeof(Note)); audioQ = xQueueCreate(4, 1); modemQ = xQueueCreate(4, 1); modemResQ = xQueueCreate(4, 1);
  loadSettings();
  delay(300);
  out.println("\n# REZON fall detector");
  {
    const esp_reset_reason_t r = esp_reset_reason();
    const char *why = r == ESP_RST_POWERON ? "power-on" : r == ESP_RST_BROWNOUT ? "BROWNOUT: the supply dipped (power, loose wire, amp)"
                    : r == ESP_RST_PANIC ? "CRASH (panic)" : (r == ESP_RST_TASK_WDT || r == ESP_RST_INT_WDT || r == ESP_RST_WDT) ? "WATCHDOG: a task hung"
                    : r == ESP_RST_SW ? "software restart" : r == ESP_RST_EXT ? "reset pin" : r == ESP_RST_USB ? "USB (port opened / upload)" : "other";
    out.printf("# restart reason: %s (%d)\n", why, (int)r);
  }
  out.printf("# profile %s, phone number %s\n", alarmSeq.prof.name, strlen(REZON_PHONE) ? "set" : "NOT SET (no secrets.h)");
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI);
  startAdc();
  attachInterrupt(digitalPinToInterrupt(PIN_DRDY), onDrdy, FALLING);
  i2s.setPins(PIN_BCK, PIN_LCK, PIN_DIN);
  audioOk = i2s.begin(I2S_MODE_STD, AUDIO_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  if (!audioOk) out.println("# ERROR: I2S did not start");
  bleStart();
  out.println("# Bluetooth: advertising as REZON");
#if HAVE_CLIPS
  alarmSeq.questionMs = sizeof(CLIP_QUESTION) / 2 * 1000UL / AUDIO_RATE + 150; alarmSeq.callingMs = sizeof(CLIP_CALLING) / 2 * 1000UL / AUDIO_RATE + 150;
#else
  out.println("# no clips.h: playing placeholder tones instead of the voice");
  alarmSeq.questionMs = 1300; alarmSeq.callingMs = 1100;
#endif
  xTaskCreatePinnedToCore(samplingTask, "sample", 8192, nullptr, configMAX_PRIORITIES - 2, nullptr, 1);
  xTaskCreatePinnedToCore(audioTask, "audio", 4096, nullptr, 3, nullptr, 0);
  xTaskCreatePinnedToCore(modemTask, "modem", 6144, nullptr, 2, nullptr, 0);
  // start-up chime, ~1.5 s after power-on so the amp (powered at the same moment) is awake
  if (chimeOn && audioOk) { delay(1500); uint8_t c = 4; xQueueSend(audioQ, &c, 0); out.printf("# start-up chime, volume %d %%\n", volumePct); }
}

void loop() {
  static char line[400]; static uint32_t lastStat = 0, lastSamples = 0;
  const uint32_t now = millis();
  pollSerial(now);

  // raw samples
  while (ringTail != ringHead) {
    const uint16_t t = ringTail;
    if (streamOn) Serial.printf("D,%ld,%ld\n", (long)ring[t][0], (long)ring[t][1]);   // USB only; BLE gets them packed
    blePackSample(ring[t][0]);
    ringTail = (t + 1) & 2047;
  }
  // detector notes
  Note o;
  while (xQueueReceive(noteQ, &o, 0) == pdTRUE) {
    fmtNote(line, sizeof line, o, det); out.println(line);
    if (o.kind == N_FALL) alarmSeq.fall(now);
    else if (o.kind == N_GOTUP) alarmSeq.gotUp(now);
  }
  // modem results
  uint8_t mr;
  while (xQueueReceive(modemResQ, &mr, 0) == pdTRUE) {
    if (mr == MR_DIAL_OK) alarmSeq.dialResult(true, now); else if (mr == MR_DIAL_FAIL) alarmSeq.dialResult(false, now); else alarmSeq.callEnded(now);
  }
  // alarm sequence
  pollButton(now);
  alarmSeq.tick(now);
  for (Action a; (a = alarmSeq.takeAction()) != ACT_NONE;) {
    uint8_t c;
    switch (a) {
      case ACT_PLAY_QUESTION: c = 1; xQueueSend(audioQ, &c, 0); break;
      case ACT_PLAY_CALLING: c = 2; xQueueSend(audioQ, &c, 0); break;
      case ACT_STOP_AUDIO: audioStop = true; break;
      case ACT_DIAL: c = MC_DIAL; xQueueSend(modemQ, &c, 0); break;
      case ACT_HANGUP: c = MC_HANGUP; xQueueSend(modemQ, &c, 0); break;
      case ACT_CLEAR_FALL: reqClearFall = true; break;
      default: break;
    }
  }
  if (alarmSeq.takeChange()) out.printf("A,%s,%lu\n", ASTATE_NAME[alarmSeq.state()], (unsigned long)alarmSeq.stateLen());
  showLed(now);
  pwrHoldTick(now);
  bleSend(now);
  { static bool was = false; if (bleConn != was) { was = bleConn; out.printf("# Bluetooth %s\n", was ? "connected" : "disconnected"); } }

  if (now - lastStat >= 1000) {
    const uint32_t sc = sampleCount, e = crcErrors; crcErrors = 0;
    out.printf("S,%lu,%lu,%d,%lu,%.4f,%.4f,%d,%.4f,%.4f\n", (unsigned long)((sc - lastSamples) * 1000UL / (now - lastStat)), (unsigned long)e, 1 << gainCode,
                  (unsigned long)det.nowMs(), det.background(), det.threshold(), det.walkers(), det.level(), det.impactThreshold());
    if (dropped) { out.printf("# %lu samples not streamed (serial too slow); detection is not affected\n", (unsigned long)dropped); dropped = 0; }
    if (bleDropped) { out.printf("# %lu bytes not sent over Bluetooth (link too slow); detection is not affected\n", (unsigned long)bleDropped); bleDropped = 0; }
    if (!adcRunning) out.println("# ADC not running. Fix the wiring, then send R.");
    lastSamples = sc; lastStat = now;
  }
  delay(1);
}
