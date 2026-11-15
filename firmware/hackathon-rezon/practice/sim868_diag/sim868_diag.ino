/*
  SIM868 DIAG - same wiring as sim868_call_test (D25 -> pin 1, D26 <- pin 2, D27 -> pin 19, 3V3 -> pin 36, GND -> pin 3).
  Tries both TX/RX orders and several baud rates, reports idle line levels, and pulses PWRKEY only if nothing answers.
  115200 baud on USB.
*/
const int A = 25, B = 26, PWR = 27;
const long bauds[] = {115200, 9600, 57600, 38400, 19200};

void levels() {
  pinMode(A, INPUT_PULLDOWN); pinMode(B, INPUT_PULLDOWN); delay(20);
  Serial.printf("# idle with pull-down: D25=%d D26=%d   (pull-up) ", digitalRead(A), digitalRead(B));
  pinMode(A, INPUT_PULLUP); pinMode(B, INPUT_PULLUP); delay(20);
  Serial.printf("D25=%d D26=%d\n", digitalRead(A), digitalRead(B));
}

bool tryAll() {
  for (int order = 0; order < 2; order++) {
    int rx = order ? A : B, tx = order ? B : A;
    for (long bd : bauds) {
      Serial2.end(); Serial2.begin(bd, SERIAL_8N1, rx, tx); delay(50);
      while (Serial2.available()) Serial2.read();
      String r;
      for (int i = 0; i < 3; i++) {
        Serial2.print("AT\r");
        uint32_t t = millis(); while (millis() - t < 300) while (Serial2.available()) r += (char)Serial2.read();
      }
      Serial.printf("# TX=D%d RX=D%d %6ld baud: %d bytes", tx, rx, bd, r.length());
      if (r.length()) { Serial.print("  ["); for (char c : r) Serial.printf("%02X ", (uint8_t)c); Serial.print("]"); }
      Serial.println();
      if (r.indexOf("OK") >= 0) { Serial.printf("# FOUND: TX=D%d RX=D%d %ld baud\n", tx, rx, bd); return true; }
    }
  }
  return false;
}

void setup() {
  Serial.begin(115200); delay(300);
  pinMode(PWR, OUTPUT); digitalWrite(PWR, LOW);
  Serial.println("\n# SIM868 diag");
  levels();
  if (tryAll()) { Serial.println("# DONE"); return; }
  pinMode(B, INPUT_PULLDOWN); delay(20);
  if (digitalRead(B)) {                    // SIM TXD held high = modem already on: a pulse would switch it OFF
    Serial.println("# SIM TXD is high (modem on), no PWRKEY pulse. Modem is on but does not hear us: check the D25 -> pin 1 jumper");
    Serial.println("# DONE"); return;
  }
  Serial.println("# nothing answered, PWRKEY pulse");
  digitalWrite(PWR, HIGH); delay(1500); digitalWrite(PWR, LOW); delay(6000);
  levels();
  if (tryAll()) { Serial.println("# DONE"); return; }
  Serial.println("# nothing answered after the pulse either");
  Serial.println("# DONE");
}
void loop() {}
