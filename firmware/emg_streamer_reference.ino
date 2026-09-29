// Reference ESP32 firmware for the EMG dataset collector.
// This file is preserved as-is from the work order and must not be
// modified without explicit user request (pins, baud rate, and CSV
// column order are load-bearing for the PC-side parser).

const int ENV_PIN = 33;
const int RAW_PIN = 34;

// 우선 저장 테스트용 500 Hz
const unsigned long SAMPLE_INTERVAL_US = 2000;

unsigned long nextSample = 0;

void setup() {
  Serial.begin(460800);

  analogReadResolution(12);

  analogSetPinAttenuation(ENV_PIN, ADC_11db);
  analogSetPinAttenuation(RAW_PIN, ADC_11db);

  delay(1000);

  // CSV header
  Serial.println("time_us,env,raw");

  nextSample = micros();
}

void loop() {
  unsigned long now = micros();

  if ((long)(now - nextSample) >= 0) {
    nextSample += SAMPLE_INTERVAL_US;

    int envValue = analogRead(ENV_PIN);
    int rawValue = analogRead(RAW_PIN);

    Serial.print(now);
    Serial.print(",");
    Serial.print(envValue);
    Serial.print(",");
    Serial.println(rawValue);
  }
}
