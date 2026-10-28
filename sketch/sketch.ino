// Nishi Daak: the Nishi's eyes and planchette on the UNO Q LED matrix.
// Python calls spell(text), energy(0..7) and timing(fade_ms, hold_ms) over the Bridge. Callbacks only set state; loop() renders.

#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>

const int ROWS = 8, COLS = 13;
// Letter timing. Python sets fade/hold at startup via timing(); keep GAP_MS and SPACE_MS in sync with spell_seconds() in python/main.py.
unsigned long FADE_MS = 250, HOLD_MS = 400;
const unsigned long GAP_MS = 150, SPACE_MS = 700;

// On the UNO Q, LED_BUILTIN is the red channel of RGB LED3 (active-low).
#if defined(LED3_R)
#define NISHI_LED LED3_R
#elif defined(LED_BUILTIN)
#define NISHI_LED LED_BUILTIN
#endif

Arduino_LED_Matrix matrix;
uint8_t frame[ROWS * COLS];

// 5x7 font: 5 columns per glyph, bit 0 is the top row. Order matches GLYPHS.
const char GLYPHS[] = " !.?0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const uint8_t FONT[][5] = {
  {0x00, 0x00, 0x00, 0x00, 0x00}, {0x00, 0x00, 0x5F, 0x00, 0x00}, {0x00, 0x60, 0x60, 0x00, 0x00}, {0x02, 0x01, 0x51, 0x09, 0x06},
  {0x3E, 0x51, 0x49, 0x45, 0x3E}, {0x00, 0x42, 0x7F, 0x40, 0x00}, {0x42, 0x61, 0x51, 0x49, 0x46}, {0x21, 0x41, 0x45, 0x4B, 0x31},
  {0x18, 0x14, 0x12, 0x7F, 0x10}, {0x27, 0x45, 0x45, 0x45, 0x39}, {0x3C, 0x4A, 0x49, 0x49, 0x30}, {0x01, 0x71, 0x09, 0x05, 0x03},
  {0x36, 0x49, 0x49, 0x49, 0x36}, {0x06, 0x49, 0x49, 0x29, 0x1E},
  {0x7E, 0x11, 0x11, 0x11, 0x7E}, {0x7F, 0x49, 0x49, 0x49, 0x36}, {0x3E, 0x41, 0x41, 0x41, 0x22}, {0x7F, 0x41, 0x41, 0x22, 0x1C},
  {0x7F, 0x49, 0x49, 0x49, 0x41}, {0x7F, 0x09, 0x09, 0x09, 0x01}, {0x3E, 0x41, 0x49, 0x49, 0x7A}, {0x7F, 0x08, 0x08, 0x08, 0x7F},
  {0x00, 0x41, 0x7F, 0x41, 0x00}, {0x20, 0x40, 0x41, 0x3F, 0x01}, {0x7F, 0x08, 0x14, 0x22, 0x41}, {0x7F, 0x40, 0x40, 0x40, 0x40},
  {0x7F, 0x02, 0x0C, 0x02, 0x7F}, {0x7F, 0x04, 0x08, 0x10, 0x7F}, {0x3E, 0x41, 0x41, 0x41, 0x3E}, {0x7F, 0x09, 0x09, 0x09, 0x06},
  {0x3E, 0x41, 0x51, 0x21, 0x5E}, {0x7F, 0x09, 0x19, 0x29, 0x46}, {0x46, 0x49, 0x49, 0x49, 0x31}, {0x01, 0x01, 0x7F, 0x01, 0x01},
  {0x3F, 0x40, 0x40, 0x40, 0x3F}, {0x1F, 0x20, 0x40, 0x20, 0x1F}, {0x3F, 0x40, 0x38, 0x40, 0x3F}, {0x63, 0x14, 0x08, 0x14, 0x63},
  {0x07, 0x08, 0x70, 0x08, 0x07}, {0x61, 0x51, 0x49, 0x45, 0x43},
};

enum State { IDLE, SPELLING };
State state = IDLE;
String text;
unsigned int idx = 0;
unsigned long phaseStart = 0;
int energyLevel = 3;
unsigned long nextBlink = 0, blinkUntil = 0, flickerUntil = 0;
int flickerPixel = 0;

void redLed(bool on) {
#ifdef NISHI_LED
  digitalWrite(NISHI_LED, on ? LOW : HIGH);
#endif
}

// --- Bridge callbacks: set state only ---------------------------------------

void spell(String t) {
  t.toUpperCase();
  text = t;
  idx = 0;
  phaseStart = millis();
  state = SPELLING;
  redLed(true);
}

void energy(int e) {
  energyLevel = constrain(e, 0, 7);
}

void timing(int fade_ms, int hold_ms) {
  FADE_MS = constrain(fade_ms, 1, 2000);  // never 0: the fade math divides by it
  HOLD_MS = constrain(hold_ms, 0, 5000);
}

// --- Rendering --------------------------------------------------------------

void drawGlyph(char c, uint8_t level) {
  const char *p = c ? strchr(GLYPHS, c) : nullptr;
  int g = p ? p - GLYPHS : 0;  // unknown characters render as a blank
  for (int col = 0; col < 5; col++)
    for (int row = 0; row < 7; row++)
      if (FONT[g][col] >> row & 1) frame[row * COLS + 4 + col] = level;  // cols 4..8 are the center
}

void renderSpelling(unsigned long now) {
  if (idx >= text.length()) {
    state = IDLE;
    redLed(false);
    return;
  }
  char c = text[idx];
  unsigned long t = now - phaseStart;
  unsigned long dur = c == ' ' ? SPACE_MS : 2 * FADE_MS + HOLD_MS + GAP_MS;
  if (t >= dur) {
    idx++;
    phaseStart = now;
    return;
  }
  if (c == ' ') return;
  uint8_t level = 0;
  if (t < FADE_MS) level = t * 7 / FADE_MS;
  else if (t < FADE_MS + HOLD_MS) level = 7;
  else if (t < 2 * FADE_MS + HOLD_MS) level = (2 * FADE_MS + HOLD_MS - t) * 7 / FADE_MS;
  drawGlyph(c, level);
}

void renderIdle(unsigned long now) {
  if (energyLevel == 0) {  // no spirit energy: only a faint stray flicker now and then
    if (now >= flickerUntil && random(100) < 2) {
      flickerPixel = random(ROWS * COLS);
      flickerUntil = now + 80;
    }
    if (now < flickerUntil) frame[flickerPixel] = 1;
    return;
  }
  if (now >= nextBlink) {
    blinkUntil = now + 150;
    nextBlink = now + random(2000, 6000);
  }
  if (now < blinkUntil) return;
  uint8_t level = constrain(energyLevel - (random(10) == 0 ? 1 : 0), 1, 7);
  for (int r = 3; r <= 4; r++) {
    frame[r * COLS + 3] = frame[r * COLS + 4] = level;  // left eye
    frame[r * COLS + 8] = frame[r * COLS + 9] = level;  // right eye
  }
}

void setup() {
  matrix.begin();
  matrix.setGrayscaleBits(3);  // brightness values 0..7
  matrix.clear();
#ifdef NISHI_LED
  pinMode(NISHI_LED, OUTPUT);
#endif
  redLed(false);
  randomSeed(micros());

  Bridge.begin();
  // provide_safe runs callbacks in the loop thread, so they never race the renderer.
  Bridge.provide_safe("spell", spell);
  Bridge.provide_safe("energy", energy);
  Bridge.provide_safe("timing", timing);
}

void loop() {
  static unsigned long lastFrame = 0;
  unsigned long now = millis();
  if (now - lastFrame < 30) return;
  lastFrame = now;
  memset(frame, 0, sizeof frame);
  if (state == SPELLING) renderSpelling(now);
  else renderIdle(now);
  matrix.draw(frame);
}
