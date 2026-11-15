/*
  GEOPHONE TEST - SM-24 geophone -> MikroE ADC 15 Click (ADS131M02) -> classic ESP32 DevKit V1 (30-pin)
  -----------------------------------------------------------------------------------------------
  Board:    "ESP32 Dev Module" (Arduino IDE, esp32 core by Espressif). No extra libraries.
  Wiring:   see Geophone_Test_Wiring.pdf (Click pin -> ESP32 pin)
              3.3V -> 3V3    GND -> GND
              SCK  -> D18    MISO -> D19    MOSI -> D23
              CS   -> D5     (ADS131M02 chip select)
              PWM  -> TX2 / GPIO17   (CS2: chip select of the LTC6903 clock chip on the Click)
              INT  -> D4     (DRDY, LOW = new sample ready)
              RST  -> RX2 / GPIO16

  What it does:
    1. Programs the Click's LTC6903 oscillator to 8.192 MHz (the ADC has no clock without it).
    2. Resets the ADS131M02, checks its ID, sets 1000 samples/s and gain 4 (±300 mV, about ±14 mm/s) on both channels.
       (Gain 32 clipped at ±1.8 mm/s in our first recording; stomps reached 6.6 mm/s.)
    3. Streams every sample over USB at 460800 baud for the web page (practice/geo_viz/index.html).

  Serial output (460800 baud):
    D,<ch1>,<ch2>      every sample, raw signed 24-bit counts. Volts = counts * 1.2 / gain / 8388608
    S,<sps>,<crcErr>,<gain>   once per second: measured sample rate, CRC errors in that second, current gain
    # ...              human-readable lines (start-up, errors)
  Serial input (from the web page or Serial Monitor, end with newline):
    G<0..7>   set gain on both channels: 0=1x 1=2x 2=4x 3=8x 4=16x 5=32x 6=64x 7=128x
    R         re-run the whole start-up

  Arduino Serial Monitor works too (set 460800 baud), but it will scroll very fast. Close it before
  using the web page: only one program can hold the COM port.
*/
#include <SPI.h>

#define PIN_SCK   18
#define PIN_MISO  19
#define PIN_MOSI  23
#define PIN_CS    5    // ADS131M02
#define PIN_CS2   17   // LTC6903 oscillator (mikroBUS "PWM" pin)
#define PIN_DRDY  4    // mikroBUS "INT"
#define PIN_RST   16   // mikroBUS "RST" (ADS131M02 SYNC/RESET, active LOW)
#define PIN_LED   2    // on-board blue LED: blinks with vibration

#define BAUD      460800

// ADS131M02 registers and commands
#define REG_ID    0x00
#define REG_STAT  0x01
#define REG_MODE  0x02
#define REG_CLOCK 0x03
#define REG_GAIN  0x04
#define CMD_NULL  0x0000
#define CMD_RESET 0x0011
#define CMD_RREG(a)  (0xA000 | ((a) << 7))
#define CMD_WREG(a)  (0x6000 | ((a) << 7))

// CLOCK = both channels on, OSR 4096 (-> 8.192 MHz / 2 / 4096 = 1000 samples/s), high-resolution power mode
#define CLOCK_1KSPS 0x0316

SPISettings adcSpi(2000000, MSBFIRST, SPI_MODE1);   // ADS131M02: CPOL 0, CPHA 1
SPISettings ltcSpi(1000000, MSBFIRST, SPI_MODE0);   // LTC6903: data latched on the rising edge

volatile bool drdyFlag = false;
void IRAM_ATTR onDrdy() { drdyFlag = true; }

uint8_t gainCode = 2;            // 2 = x4 (±300 mV)
uint32_t samples = 0, crcErr = 0, lastStat = 0;
int32_t ledPeak = 0;

// ---------------------------------------------------------------- low level
static uint16_t crc16(const uint8_t *d, int n) {          // CCITT, poly 0x1021, init 0xFFFF
  uint16_t c = 0xFFFF;
  for (int i = 0; i < n; i++) { c ^= (uint16_t)d[i] << 8; for (int b = 0; b < 8; b++) c = (c & 0x8000) ? (c << 1) ^ 0x1021 : c << 1; }
  return c;
}
static int32_t s24(const uint8_t *p) { int32_t v = ((int32_t)p[0] << 16) | (p[1] << 8) | p[2]; return (v & 0x800000) ? v - 0x1000000 : v; }

// One full frame = 4 words x 3 bytes: [command/response][ch1][ch2][crc]
static void frame(uint16_t cmd, uint16_t data, uint8_t *rx) {
  uint8_t tx[12] = { (uint8_t)(cmd >> 8), (uint8_t)cmd, 0, (uint8_t)(data >> 8), (uint8_t)data, 0, 0, 0, 0, 0, 0, 0 };
  SPI.beginTransaction(adcSpi);
  digitalWrite(PIN_CS, LOW);
  for (int i = 0; i < 12; i++) rx[i] = SPI.transfer(tx[i]);
  digitalWrite(PIN_CS, HIGH);
  SPI.endTransaction();
}
static uint16_t readReg(uint8_t a) {      // the answer arrives in the NEXT frame
  uint8_t rx[12];
  frame(CMD_RREG(a), 0, rx); frame(CMD_NULL, 0, rx);
  return (rx[0] << 8) | rx[1];
}
static void writeReg(uint8_t a, uint16_t v) { uint8_t rx[12]; frame(CMD_WREG(a), v, rx); frame(CMD_NULL, 0, rx); }

// LTC6903: f = 2^OCT * 2078 / (2 - DAC/1024). 8.192 MHz -> OCT 12, DAC 984, CNF 2 (same as MikroE's driver) -> 0xCF62
static void setClock8M() {
  uint16_t w = (12 << 12) | (984 << 2) | 2;
  SPI.beginTransaction(ltcSpi);
  digitalWrite(PIN_CS2, LOW);
  SPI.transfer16(w);
  digitalWrite(PIN_CS2, HIGH);
  SPI.endTransaction();
}

static void setGain(uint8_t g) {
  gainCode = g & 7;
  writeReg(REG_GAIN, (gainCode << 4) | gainCode);
  Serial.printf("# gain x%d on both channels (full scale ±%.2f mV)\n", 1 << gainCode, 1200.0 / (1 << gainCode));
}

static bool startAdc() {
  digitalWrite(PIN_CS, HIGH); digitalWrite(PIN_CS2, HIGH);
  setClock8M();
  delay(5);                                            // let the oscillator settle
  digitalWrite(PIN_RST, LOW); delay(2); digitalWrite(PIN_RST, HIGH); delay(10);
  uint16_t id = readReg(REG_ID);
  Serial.printf("# ADS131M02 ID = 0x%04X (expect 0x22xx)\n", id);
  if ((id & 0xFF00) != 0x2200) {
    Serial.println("# ERROR: no ADS131M02 answer. Check 3.3V/GND, SCK D18, MISO D19, MOSI D23, CS D5, PWM->GPIO17 (clock), RST->GPIO16.");
    return false;
  }
  writeReg(REG_CLOCK, CLOCK_1KSPS);
  setGain(gainCode);
  Serial.printf("# MODE 0x%04X  CLOCK 0x%04X  GAIN 0x%04X\n", readReg(REG_MODE), readReg(REG_CLOCK), readReg(REG_GAIN));
  Serial.println("# streaming: D,<ch1>,<ch2> at 1000 samples/s");
  return true;
}

// ---------------------------------------------------------------- Arduino
bool running = false;

void setup() {
  Serial.begin(BAUD);
  pinMode(PIN_CS, OUTPUT); pinMode(PIN_CS2, OUTPUT); pinMode(PIN_RST, OUTPUT); pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_CS, HIGH); digitalWrite(PIN_CS2, HIGH); digitalWrite(PIN_RST, HIGH);
  pinMode(PIN_DRDY, INPUT_PULLUP);
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI);
  delay(300);
  Serial.println("\n# REZON geophone test - SM-24 + ADC 15 Click + ESP32");
  running = startAdc();
  attachInterrupt(digitalPinToInterrupt(PIN_DRDY), onDrdy, FALLING);
  lastStat = millis();
}

void handleInput() {
  static char buf[16]; static uint8_t n = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      buf[n] = 0;
      if (n >= 2 && buf[0] == 'G') { if (running) setGain(buf[1] - '0'); }
      else if (n >= 1 && buf[0] == 'R') running = startAdc();
      n = 0;
    } else if (n < sizeof(buf) - 1) buf[n++] = c;
  }
}

void loop() {
  handleInput();
  if (!running) { if (millis() - lastStat > 3000) { lastStat = millis(); Serial.println("# ADC not running. Fix the wiring, then send R (or press EN)."); } return; }

  if (drdyFlag || digitalRead(PIN_DRDY) == LOW) {
    drdyFlag = false;
    uint8_t rx[12];
    frame(CMD_NULL, 0, rx);
    if (crc16(rx, 9) != ((rx[9] << 8) | rx[10])) crcErr++;
    int32_t ch1 = s24(rx + 3), ch2 = s24(rx + 6);
    Serial.printf("D,%ld,%ld\n", (long)ch1, (long)ch2);
    samples++;
    int32_t a = abs(ch1); if (a > ledPeak) ledPeak = a;
  }

  uint32_t now = millis();
  if (now - lastStat >= 1000) {
    Serial.printf("S,%lu,%lu,%d\n", (unsigned long)(samples * 1000UL / (now - lastStat)), (unsigned long)crcErr, 1 << gainCode);
    samples = 0; crcErr = 0; lastStat = now;
  }
  // LED: on while the signal is above ~1 % of full scale (about 0.14 mm/s at x4)
  static uint32_t ledT = 0;
  if (now - ledT >= 50) { ledT = now; digitalWrite(PIN_LED, ledPeak > 83886); ledPeak = 0; }
}
