/* MIT License
 *
 * Copyright (c) 2021 Valve Corporation
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 *
 * Author: Martin Peres <martin.peres@mupuf.org>
 */

#include <string.h>

#define POWER_BUTTON_PIN A0
#define POWER_BUTTON_PRESS_TIME 100
#define POWER_BUTTON_PRESS_VALUE 0
#define POWER_BUTTON_DEPRESS_VALUE 1

#define POWER_STATE_PIN A1
#define POWER_STATE_UNKNOWN -1
#define POWER_STATE_OFF 1
#define POWER_STATE_ON 0
#define POWER_STATE_DEBOUNCE_TIME 20

#define PRESS_TO_STATE_ON_DELAY 250
#define SUCCESSFULL_BOOT_DELAY 10000
#define LOOP_DELAY 1

#define DEBUG 0

const char *state_to_string(int power_state)
{
  switch(power_state) {
    case POWER_STATE_ON:
      return "ON";
    case POWER_STATE_OFF:
      return "OFF";
    case POWER_STATE_UNKNOWN:
      return "UNK";
    default:
      return "BAD";
  }
}

void setup() {
  if (DEBUG)
    Serial.begin(115200);
  
  pinMode(POWER_BUTTON_PIN, OUTPUT);
  pinMode(POWER_STATE_PIN, INPUT);
  pinMode(LED_BUILTIN, OUTPUT);

  digitalWrite(POWER_BUTTON_PIN, POWER_BUTTON_DEPRESS_VALUE);
}

int debounced_power_state = POWER_STATE_UNKNOWN;
int last_power_state = POWER_STATE_UNKNOWN;
bool boot_complete = false;
unsigned long last_state_change = 0, last_boot_attempt = 0;
char msg[255];
void loop() {
  int power_state = digitalRead(POWER_STATE_PIN);
  digitalWrite(LED_BUILTIN, power_state == POWER_STATE_ON);

  if (power_state != last_power_state) {
    last_power_state = power_state;
    last_state_change = millis();
  } else if (millis() - last_state_change > POWER_STATE_DEBOUNCE_TIME) {
    debounced_power_state = power_state;
  }

  if (DEBUG) {
    sprintf(msg, "Power state: raw=%s, debounced=%s, last_change=%lu ms; Last boot attempt=%lu\r\n",
            state_to_string(power_state), state_to_string(debounced_power_state),
            millis() - last_state_change, millis() - last_boot_attempt);
    Serial.write(msg);
  }
  
  if (boot_complete == false && debounced_power_state == POWER_STATE_OFF && millis() - last_boot_attempt > PRESS_TO_STATE_ON_DELAY) {
    digitalWrite(POWER_BUTTON_PIN, POWER_BUTTON_PRESS_VALUE);
    delay(POWER_BUTTON_PRESS_TIME);
    digitalWrite(POWER_BUTTON_PIN, POWER_BUTTON_DEPRESS_VALUE);
    
    // Reset the state
    last_boot_attempt = millis();
  } else if (debounced_power_state == POWER_STATE_ON && millis() - last_boot_attempt > SUCCESSFULL_BOOT_DELAY) {
    boot_complete = true;
    if (DEBUG)
      Serial.write("Boot on AC complete\n");
  }
  
  delay(LOOP_DELAY);
}
