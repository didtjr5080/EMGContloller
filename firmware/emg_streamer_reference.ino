// =====================================================
// ESP32 + MyoWare 2.0 x 2
//
// EMG 1 = 이두근
// EMG 2 = 상완요골근
//
// ENV + RAW 동시 측정
// Sampling Rate = 500 Hz
// =====================================================
//
// Reference ESP32 firmware for the EMG dataset collector. This file is
// preserved as-is and must not be modified without an explicit request,
// since the parser and dataset schema depend on these pins/columns.
//
// Supersedes the earlier single-sensor (time_us,env,raw) version: the
// real hardware now reads two MyoWare 2.0 sensors (biceps,
// brachioradialis) over 4 ADC pins and streams 5 CSV columns.


// -------------------------
// 근전도 센서 1 : 이두근
// -------------------------

const int BICEPS_ENV_PIN = 33;
const int BICEPS_RAW_PIN = 34;


// -------------------------
// 근전도 센서 2 : 상완요골근
// -------------------------

const int BRACHIO_ENV_PIN = 32;
const int BRACHIO_RAW_PIN = 35;


// -------------------------
// Sampling 설정
// -------------------------

// 500 Hz
// 1초 = 1,000,000 us
// 1,000,000 / 500 = 2,000 us

const unsigned long SAMPLE_INTERVAL_US = 2000;

unsigned long nextSample = 0;


// =====================================================
// SETUP
// =====================================================

void setup() {

  // PC Serial 통신
  Serial.begin(460800);


  // ESP32 ADC
  // 12 bit → 0 ~ 4095
  analogReadResolution(12);


  // 이두근 센서
  analogSetPinAttenuation(
    BICEPS_ENV_PIN,
    ADC_11db
  );

  analogSetPinAttenuation(
    BICEPS_RAW_PIN,
    ADC_11db
  );


  // 상완요골근 센서
  analogSetPinAttenuation(
    BRACHIO_ENV_PIN,
    ADC_11db
  );

  analogSetPinAttenuation(
    BRACHIO_RAW_PIN,
    ADC_11db
  );


  // 센서 안정화
  delay(1000);


  // CSV Header
  Serial.println(
    "time_us,biceps_env,biceps_raw,brachio_env,brachio_raw"
  );


  nextSample = micros();
}


// =====================================================
// LOOP
// =====================================================

void loop() {

  unsigned long now = micros();


  // 2000 us마다 측정
  if ((long)(now - nextSample) >= 0) {

    nextSample += SAMPLE_INTERVAL_US;


    // ---------------------------------
    // 1. 이두근 측정
    // ---------------------------------

    int bicepsEnv =
      analogRead(BICEPS_ENV_PIN);

    int bicepsRaw =
      analogRead(BICEPS_RAW_PIN);


    // ---------------------------------
    // 2. 상완요골근 측정
    // ---------------------------------

    int brachioEnv =
      analogRead(BRACHIO_ENV_PIN);

    int brachioRaw =
      analogRead(BRACHIO_RAW_PIN);


    // ---------------------------------
    // CSV 형태로 PC 전송
    // ---------------------------------

    Serial.print(now);
    Serial.print(",");


    // 이두근

    Serial.print(bicepsEnv);
    Serial.print(",");

    Serial.print(bicepsRaw);
    Serial.print(",");


    // 상완요골근

    Serial.print(brachioEnv);
    Serial.print(",");

    Serial.println(brachioRaw);
  }
}
