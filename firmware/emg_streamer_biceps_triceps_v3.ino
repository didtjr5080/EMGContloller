// PILOT profile: one arm, sensor 1 biceps, sensor 2 triceps.
// Legacy emg_streamer_reference.ino is preserved. Verify actual attachment.
// 500 Hz does not establish RAW analog bandwidth / anti-alias validity.
const int BICEPS_ENV_PIN = 33;
const int BICEPS_RAW_PIN = 34;
const int TRICEPS_ENV_PIN = 32;
const int TRICEPS_RAW_PIN = 35;
const unsigned long SAMPLE_INTERVAL_US = 2000;
unsigned long nextSample = 0;

void setup() {
  Serial.begin(460800);
  analogReadResolution(12);
  analogSetPinAttenuation(BICEPS_ENV_PIN, ADC_11db);
  analogSetPinAttenuation(BICEPS_RAW_PIN, ADC_11db);
  analogSetPinAttenuation(TRICEPS_ENV_PIN, ADC_11db);
  analogSetPinAttenuation(TRICEPS_RAW_PIN, ADC_11db);
  delay(1000);
  Serial.println("time_us,biceps_env,biceps_raw,triceps_env,triceps_raw");
  nextSample = micros();
}

void loop() {
  unsigned long now = micros();
  if ((long)(now - nextSample) >= 0) {
    nextSample += SAMPLE_INTERVAL_US;
    int bicepsEnv = analogRead(BICEPS_ENV_PIN);
    int bicepsRaw = analogRead(BICEPS_RAW_PIN);
    int tricepsEnv = analogRead(TRICEPS_ENV_PIN);
    int tricepsRaw = analogRead(TRICEPS_RAW_PIN);
    Serial.print(now); Serial.print(",");
    Serial.print(bicepsEnv); Serial.print(",");
    Serial.print(bicepsRaw); Serial.print(",");
    Serial.print(tricepsEnv); Serial.print(",");
    Serial.println(tricepsRaw);
  }
}
