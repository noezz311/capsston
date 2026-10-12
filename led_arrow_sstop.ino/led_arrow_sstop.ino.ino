#include <SoftwareSerial.h>
#include <Servo.h>

// Bluetooth:
// Bluetooth TX -> UNO D10
// Bluetooth RX -> UNO D11
SoftwareSerial BT(10, 11); // RX, TX

Servo doorServo;

const int SERVO_PIN = 9;
String cmd = "";

void setup() {
  Serial.begin(9600);
  BT.begin(9600);

  doorServo.attach(SERVO_PIN);

  // эхлэх үед хаалттай байрлал
  doorServo.write(180);
  delay(300);

  Serial.println("Bluetooth Ready");
  BT.println("Bluetooth Ready");
}

void loop() {
  readFromBluetooth();
  readFromSerial();
}

void readFromBluetooth() {
  while (BT.available()) {
    char c = BT.read();
    readCommand(c);
  }
}

void readFromSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    readCommand(c);
  }
}

void readCommand(char c) {
  if (c == '\n' || c == '\r') {
    processCommand(cmd);
    cmd = "";
    return;
  }

  cmd += c;
  cmd.trim();

  String temp = cmd;
  temp.toUpperCase();

  // newline байхгүй байсан ч OPEN/CLOSE ирвэл шууд ажиллана
  if (temp == "OPEN" || temp == "CLOSE") {
    processCommand(temp);
    cmd = "";
  }

  // хэт урт буруу command ирвэл reset
  if (cmd.length() > 20) {
    Serial.print("Unknown command: ");
    Serial.println(cmd);

    BT.print("Unknown command: ");
    BT.println(cmd);

    cmd = "";
  }
}

void processCommand(String command) {
  command.trim();
  command.toUpperCase();

  if (command.length() == 0) {
    return;
  }

  if (command == "OPEN") {
    doorServo.write(90);

    Serial.println("Servo: OPEN (90)");
    BT.println("Servo: OPEN (90)");
  }
  else if (command == "CLOSE") {
    doorServo.write(180);

    Serial.println("Servo: CLOSE (180)");
    BT.println("Servo: CLOSE (180)");
  }
  else {
    Serial.print("Unknown command: ");
    Serial.println(command);

    BT.print("Unknown command: ");
    BT.println(command);
  }
}