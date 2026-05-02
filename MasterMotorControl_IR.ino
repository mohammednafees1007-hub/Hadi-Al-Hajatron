// ======================================================
// MASTER MOTOR CONTROL CODE + IR REQUEST SUPPORT
// F/f -> Forward by FORWARD_DISTANCE_CM
// R/r -> Right 90 degree
// L/l -> Left 90 degree
// S/s -> Emergency stop + clear queue
// I/i -> Send IR readings as F,L,R where 0=obstacle, 1=free
// Supports combined commands: frllrfff
// ======================================================

// ---------- MOTOR DRIVER PINS ----------
const int L_RPWM = 5;
const int L_LPWM = 6;
const int R_RPWM = 10;
const int R_LPWM = 11;

// ---------- ENCODER PINS ----------
const int ENC_L_A = 2;
const int ENC_L_B = 4;
const int ENC_R_A = 3;
const int ENC_R_B = 7;

// ---------- IR SENSOR PINS ----------
const int IR_FRONT_PIN = 9;
const int IR_LEFT_PIN = 8;
const int IR_RIGHT_PIN = 12;
const bool IR_USE_ANALOG = false;
const bool IR_OBSTACLE_IS_LOW = true;
const int IR_OBSTACLE_THRESHOLD = 500;

// ---------- USER DISTANCE SETTING ----------
const float FORWARD_DISTANCE_CM = 60.0;   // CHANGE ONLY THIS VALUE

// ---------- CALIBRATION COUNTS ----------
const long LEFT_TARGET_60CM  = 2232;
const long RIGHT_TARGET_60CM = 2175;

const long LEFT_TARGET_CM  = (LEFT_TARGET_60CM * FORWARD_DISTANCE_CM) / 60.0;
const long RIGHT_TARGET_CM = (RIGHT_TARGET_60CM * FORWARD_DISTANCE_CM) / 60.0;

// ---------- 90 DEGREE TURN COUNTS ----------
const long LEFT_TURN_90  = 734;
const long RIGHT_TURN_90 = 719;

// ---------- SPEED SETTINGS ----------
const int PWM_FAST = 110;
const int PWM_MED  = 80;
const int PWM_SLOW = 55;
const int TURN_PWM = 85;

// ---------- STRAIGHT CORRECTION ----------
const float KP = 6.0;

// ---------- PRINT ----------
unsigned long lastPrint = 0;

// ---------- ENCODER COUNTS ----------
volatile long leftCount = 0;
volatile long rightCount = 0;

// ---------- COMMAND QUEUE ----------
#define QUEUE_SIZE 50
char commandQueue[QUEUE_SIZE];
int queueHead = 0;
int queueTail = 0;

// ---------- ROBOT STATE ----------
enum RobotState {
  IDLE,
  MOVING_FORWARD,
  TURNING_RIGHT_90,
  TURNING_LEFT_90
};

RobotState state = IDLE;

// ======================================================
// ENCODER ISR
// ======================================================
void leftEncoderISR() {
  bool A = digitalRead(ENC_L_A);
  bool B = digitalRead(ENC_L_B);

  if (A == B) leftCount++;
  else        leftCount--;
}

void rightEncoderISR() {
  bool A = digitalRead(ENC_R_A);
  bool B = digitalRead(ENC_R_B);

  if (A == B) rightCount--;
  else        rightCount++;
}

// ======================================================
// MOTOR FUNCTIONS
// ======================================================
void stopLeftMotor() {
  analogWrite(L_RPWM, 0);
  analogWrite(L_LPWM, 0);
}

void stopRightMotor() {
  analogWrite(R_RPWM, 0);
  analogWrite(R_LPWM, 0);
}

void stopAll() {
  stopLeftMotor();
  stopRightMotor();
}

void runLeftForward(int pwm) {
  analogWrite(L_RPWM, 0);
  analogWrite(L_LPWM, pwm);
}

void runRightForward(int pwm) {
  analogWrite(R_RPWM, pwm);
  analogWrite(R_LPWM, 0);
}

void runLeftBackward(int pwm) {
  analogWrite(L_RPWM, pwm);
  analogWrite(L_LPWM, 0);
}

void runRightBackward(int pwm) {
  analogWrite(R_RPWM, 0);
  analogWrite(R_LPWM, pwm);
}

// ======================================================
// IR FUNCTIONS
// ======================================================
int readIrSensor(int pin) {
  bool obstacle;

  if (IR_USE_ANALOG) {
    int raw = analogRead(pin);
    obstacle = IR_OBSTACLE_IS_LOW ? raw < IR_OBSTACLE_THRESHOLD : raw > IR_OBSTACLE_THRESHOLD;
  }
  else {
    int raw = digitalRead(pin);
    obstacle = IR_OBSTACLE_IS_LOW ? raw == LOW : raw == HIGH;
  }

  return obstacle ? 0 : 1;
}

void sendIrReadings() {
  int front = readIrSensor(IR_FRONT_PIN);
  int left = readIrSensor(IR_LEFT_PIN);
  int right = readIrSensor(IR_RIGHT_PIN);

  Serial.print(front);
  Serial.print(",");
  Serial.print(left);
  Serial.print(",");
  Serial.println(right);
}

// ======================================================
// QUEUE FUNCTIONS
// ======================================================
void clearQueue() {
  queueHead = 0;
  queueTail = 0;
}

bool queueIsEmpty() {
  return queueHead == queueTail;
}

bool queueIsFull() {
  return ((queueTail + 1) % QUEUE_SIZE) == queueHead;
}

void enqueueCommand(char cmd) {
  if (queueIsFull()) {
    Serial.println("QUEUE FULL! Command lost.");
    return;
  }

  commandQueue[queueTail] = cmd;
  queueTail = (queueTail + 1) % QUEUE_SIZE;

  Serial.print("Queued: ");
  Serial.println(cmd);
}

char dequeueCommand() {
  if (queueIsEmpty()) return '\0';

  char cmd = commandQueue[queueHead];
  queueHead = (queueHead + 1) % QUEUE_SIZE;
  return cmd;
}

// ======================================================
// HELPER FUNCTIONS
// ======================================================
void resetCounts() {
  noInterrupts();
  leftCount = 0;
  rightCount = 0;
  interrupts();
}

void getAbsCounts(long &absL, long &absR) {
  noInterrupts();
  absL = abs(leftCount);
  absR = abs(rightCount);
  interrupts();
}

float getLeftDistanceCm(long absL) {
  return (FORWARD_DISTANCE_CM * absL) / LEFT_TARGET_CM;
}

float getRightDistanceCm(long absR) {
  return (FORWARD_DISTANCE_CM * absR) / RIGHT_TARGET_CM;
}

float getBotDistanceCm(long absL, long absR) {
  return (getLeftDistanceCm(absL) + getRightDistanceCm(absR)) / 2.0;
}

int getBasePWM(float avgProgress) {
  if (avgProgress < 0.80) return PWM_FAST;
  if (avgProgress < 0.95) return PWM_MED;
  return PWM_SLOW;
}

// ======================================================
// SERIAL COMMAND READING
// ======================================================
void readSerialCommands() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c >= 'a' && c <= 'z') {
      c = c - 32;
    }

    if (c == 'I') {
      if (state == IDLE) {
        sendIrReadings();
      }
      else {
        Serial.println("BUSY");
      }
    }
    else if (c == 'F' || c == 'R' || c == 'L') {
      enqueueCommand(c);
    }
    else if (c == 'S') {
      stopAll();
      clearQueue();
      resetCounts();
      state = IDLE;
      Serial.println("EMERGENCY STOP: Queue cleared.");
    }
  }
}

// ======================================================
// PRINT STATUS
// ======================================================
void printMoveStatus(const char* label, long absL, long absR) {
  Serial.print(label);

  Serial.print(" | L: ");
  Serial.print(absL);
  Serial.print("/");
  Serial.print(LEFT_TARGET_CM);

  Serial.print(" R: ");
  Serial.print(absR);
  Serial.print("/");
  Serial.print(RIGHT_TARGET_CM);

  Serial.print(" Bot cm: ");
  Serial.println(getBotDistanceCm(absL, absR), 2);
}

void printTurnStatus(const char* label, long absL, long absR) {
  Serial.print(label);

  Serial.print(" | L: ");
  Serial.print(absL);
  Serial.print("/");
  Serial.print(LEFT_TURN_90);

  Serial.print(" R: ");
  Serial.print(absR);
  Serial.print("/");
  Serial.println(RIGHT_TURN_90);
}

// ======================================================
// START ACTIONS
// ======================================================
void startForward() {
  resetCounts();
  state = MOVING_FORWARD;

  Serial.print("START: Forward ");
  Serial.print(FORWARD_DISTANCE_CM);
  Serial.println(" cm");
}

void startRight90() {
  resetCounts();
  state = TURNING_RIGHT_90;
  Serial.println("START: Right 90 degree");
}

void startLeft90() {
  resetCounts();
  state = TURNING_LEFT_90;
  Serial.println("START: Left 90 degree");
}

// ======================================================
// ACTION FUNCTIONS
// ======================================================
bool doMoveForward() {
  long absL, absR;
  getAbsCounts(absL, absR);

  float leftDist = getLeftDistanceCm(absL);
  float rightDist = getRightDistanceCm(absR);

  float leftProgress = (float)absL / LEFT_TARGET_CM;
  float rightProgress = (float)absR / RIGHT_TARGET_CM;
  float avgProgress = (leftProgress + rightProgress) / 2.0;

  int basePWM = getBasePWM(avgProgress);

  float distError = leftDist - rightDist;
  int correction = (int)(KP * distError);

  int leftPWM  = constrain(basePWM - correction, 0, 255);
  int rightPWM = constrain(basePWM + correction, 0, 255);

  if (absL < LEFT_TARGET_CM) runLeftForward(leftPWM);
  else stopLeftMotor();

  if (absR < RIGHT_TARGET_CM) runRightForward(rightPWM);
  else stopRightMotor();

  if (millis() - lastPrint >= 150) {
    lastPrint = millis();
    printMoveStatus("FORWARD", absL, absR);
  }

  if (absL >= LEFT_TARGET_CM && absR >= RIGHT_TARGET_CM) {
    stopAll();

    Serial.print("DONE: Forward ");
    Serial.print(FORWARD_DISTANCE_CM);
    Serial.println(" cm");

    return true;
  }

  return false;
}

bool doRightTurn90() {
  long absL, absR;
  getAbsCounts(absL, absR);

  if (absL < LEFT_TURN_90) runLeftForward(TURN_PWM);
  else stopLeftMotor();

  if (absR < RIGHT_TURN_90) runRightBackward(TURN_PWM);
  else stopRightMotor();

  if (millis() - lastPrint >= 150) {
    lastPrint = millis();
    printTurnStatus("RIGHT 90", absL, absR);
  }

  if (absL >= LEFT_TURN_90 && absR >= RIGHT_TURN_90) {
    stopAll();
    Serial.println("DONE: Right 90 degree");
    return true;
  }

  return false;
}

bool doLeftTurn90() {
  long absL, absR;
  getAbsCounts(absL, absR);

  if (absL < LEFT_TURN_90) runLeftBackward(TURN_PWM);
  else stopLeftMotor();

  if (absR < RIGHT_TURN_90) runRightForward(TURN_PWM);
  else stopRightMotor();

  if (millis() - lastPrint >= 150) {
    lastPrint = millis();
    printTurnStatus("LEFT 90", absL, absR);
  }

  if (absL >= LEFT_TURN_90 && absR >= RIGHT_TURN_90) {
    stopAll();
    Serial.println("DONE: Left 90 degree");
    return true;
  }

  return false;
}

// ======================================================
// SETUP
// ======================================================
void setup() {
  Serial.begin(115200);

  pinMode(L_RPWM, OUTPUT);
  pinMode(L_LPWM, OUTPUT);
  pinMode(R_RPWM, OUTPUT);
  pinMode(R_LPWM, OUTPUT);

  pinMode(ENC_L_A, INPUT_PULLUP);
  pinMode(ENC_L_B, INPUT_PULLUP);
  pinMode(ENC_R_A, INPUT_PULLUP);
  pinMode(ENC_R_B, INPUT_PULLUP);

  if (IR_USE_ANALOG) {
    pinMode(IR_FRONT_PIN, INPUT);
    pinMode(IR_LEFT_PIN, INPUT);
    pinMode(IR_RIGHT_PIN, INPUT);
  }
  else {
    pinMode(IR_FRONT_PIN, INPUT_PULLUP);
    pinMode(IR_LEFT_PIN, INPUT_PULLUP);
    pinMode(IR_RIGHT_PIN, INPUT_PULLUP);
  }

  attachInterrupt(digitalPinToInterrupt(ENC_L_A), leftEncoderISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_R_A), rightEncoderISR, CHANGE);

  stopAll();
  resetCounts();
  clearQueue();

  state = IDLE;

  Serial.println("MASTER MOTOR CONTROL READY");

  Serial.print("Forward distance = ");
  Serial.print(FORWARD_DISTANCE_CM);
  Serial.println(" cm");

  Serial.println("Commands:");
  Serial.println("F = Forward");
  Serial.println("R = Right 90 degree");
  Serial.println("L = Left 90 degree");
  Serial.println("S = Stop and clear queue");
  Serial.println("I = Send IR readings as F,L,R");
  Serial.println("Example: frllrfff");
}

// ======================================================
// LOOP
// ======================================================
void loop() {
  readSerialCommands();

  if (state == IDLE && !queueIsEmpty()) {
    char cmd = dequeueCommand();

    Serial.print("Executing: ");
    Serial.println(cmd);

    if (cmd == 'F') {
      startForward();
    }
    else if (cmd == 'R') {
      startRight90();
    }
    else if (cmd == 'L') {
      startLeft90();
    }
  }

  if (state == MOVING_FORWARD) {
    if (doMoveForward()) {
      state = IDLE;
    }
  }
  else if (state == TURNING_RIGHT_90) {
    if (doRightTurn90()) {
      state = IDLE;
    }
  }
  else if (state == TURNING_LEFT_90) {
    if (doLeftTurn90()) {
      state = IDLE;
    }
  }
}
