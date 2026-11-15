/*
  SIM868 CALL TEST - Waveshare Pico-SIM868 board (Pico H removed) -> classic ESP32 DevKit V1 (30-pin)
  -----------------------------------------------------------------------------------------------
  Board:    "ESP32 Dev Module" (Arduino IDE, esp32 core by Espressif). No extra libraries.
  Wiring (SIM868 board pins = the Pico socket numbers, pin 1 = GP0 at the end where the Pico USB sat):
              ESP32 D25 (TX)  -> SIM868 board pin 1  (GP0 = SIM RXD)
              ESP32 D26 (RX)  <- SIM868 board pin 2  (GP1 = SIM TXD)
              ESP32 GND       -  SIM868 board pin 3  (GND)
              ESP32 D27       -> SIM868 board pin 19 (GP14 = PWR_EN, HIGH 1.5 s toggles the modem on/off)
              ESP32 3V3       -> SIM868 board pin 36 (3V3 OUT = supply of the board's level shifter)
            SIM868 power: the 600 mAh Li-po from the box in the board's battery socket, board switch on battery.
            D25/D26/D27 are not used by the geophone test, so the ADC 15 Click wiring can stay in place.

  Serial Monitor: 115200 baud, line ending "Both NL & CR" (or "Newline").
    CALL +36xxxxxxxxx   dial a number (voice call)
    HANG                hang up
    STATUS              SIM, signal, registration, operator, battery voltage
    PWR                 pulse PWRKEY (toggles the modem on/off)
    anything else       sent to the modem as a raw AT command, e.g. AT+CSQ
*/

#define PIN_SIM_TX   25   // ESP32 TX -> SIM RXD
#define PIN_SIM_RX   26   // ESP32 RX <- SIM TXD
#define PIN_PWRKEY   27   // -> board GP14 (NPN on SIM868 PWRKEY)
#define SIM_BAUD     115200

String line;

// Send a command and echo everything the modem says for `ms` milliseconds. Returns true if "OK" came back.
bool at(const String &cmd, uint32_t ms = 1000) {
  while (Serial2.available()) Serial2.read();
  Serial.print(F(">> ")); Serial.println(cmd);
  Serial2.print(cmd); Serial2.print("\r");
  String rx; uint32_t t0 = millis();
  while (millis() - t0 < ms) {
    while (Serial2.available()) { char c = Serial2.read(); rx += c; Serial.write(c); }
    if (rx.indexOf("OK\r") >= 0 || rx.indexOf("ERROR") >= 0) break;
  }
  return rx.indexOf("OK") >= 0;
}

void pulsePwrkey() {
  Serial.println(F("# PWRKEY pulse (1.5 s)"));
  digitalWrite(PIN_PWRKEY, HIGH); delay(1500); digitalWrite(PIN_PWRKEY, LOW);
}

bool modemAlive() {                       // a few plain ATs also let the modem lock its auto-baud
  for (int i = 0; i < 4; i++) if (at("AT", 500)) return true;
  return false;
}

void status() {
  at("AT+CPIN?");                         // READY = SIM ok, SIM PIN = disable the PIN in a phone first
  at("AT+CSQ");                           // signal 0..31 (99 = unknown); want >= 10
  at("AT+CREG?");                         // ,1 = registered home  ,5 = roaming  ,2 = searching  ,3 = denied
  at("AT+COPS?", 3000);                   // operator name
  at("AT+CBC");                           // battery: ...,<mV>   want > 3600 mV
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_PWRKEY, OUTPUT); digitalWrite(PIN_PWRKEY, LOW);
  Serial2.begin(SIM_BAUD, SERIAL_8N1, PIN_SIM_RX, PIN_SIM_TX);
  delay(500);
  Serial.println(F("\n# SIM868 call test"));

  if (!modemAlive()) {
    Serial.println(F("# no answer, switching the modem on"));
    pulsePwrkey();
    delay(4000);
    uint32_t t0 = millis(); bool ok = false;
    while (!ok && millis() - t0 < 15000) ok = modemAlive();
    if (!ok) { Serial.println(F("# STILL NO ANSWER: check TX/RX not swapped, GND, pin 36 = 3V3, battery, board switch")); return; }
  }
  Serial.println(F("# modem answers"));
  at("ATE0");                             // no command echo (this sketch prints the commands itself)
  at("AT+CMEE=2");                        // readable error texts
  at("AT+CLVL=90");                       // speaker volume for the call
  Serial.println(F("# waiting up to 60 s for the network (NET LED: fast blink = searching, every ~3 s = registered)"));
  uint32_t t0 = millis();
  while (millis() - t0 < 60000) {
    Serial2.print("AT+CREG?\r"); delay(300);
    String r; while (Serial2.available()) r += (char)Serial2.read();
    if (r.indexOf(",1") >= 0 || r.indexOf(",5") >= 0) { Serial.println(F("# registered")); break; }
    delay(2000);
  }
  status();
  Serial.println(F("# ready: type  CALL +36xxxxxxxxx"));
}

void loop() {
  while (Serial2.available()) Serial.write(Serial2.read());   // RING, NO CARRIER, BUSY, etc.

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c != '\n') { line += c; continue; }
    line.trim();
    if (line.length() == 0) continue;
    String up = line; up.toUpperCase();
    if (up.startsWith("CALL ")) {
      String num = line.substring(5); num.trim();
      at("ATD" + num + ";", 5000);        // OK here = dialling started, your phone should ring in a few seconds
    } else if (up == "HANG") at("ATH");
    else if (up == "STATUS") status();
    else if (up == "PWR") pulsePwrkey();
    else at(line, 3000);
    line = "";
  }
}
