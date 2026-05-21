#!/usr/bin/env python3

import RPi.GPIO as GPIO
import time
import subprocess
import os
import signal

# =========================
# PIN CONFIGURATION - BCM
# =========================

PIN_PULSE_001 = 18   # physical pin 12 -> x0.01 sec pulse
PIN_PULSE_01  = 23   # physical pin 16 -> x0.1 sec pulse
PIN_PULSE_1   = 24   # physical pin 18 -> x1 sec pulse
PIN_PULSE_10  = 25   # physical pin 22 -> x10 sec pulse

PIN_RESET_MAIN = 12  # physical pin 32 -> reset x10 and x1 digits
PIN_RESET_LOW  = 7   # physical pin 26 -> reset x0.1 and x0.01 digits

PIN_BUTTON = 16      # physical pin 36 -> main button
PIN_TEST_WIN = 20    # physical pin 38 -> test win button
PIN_WIDE_MODE = 21   # physical pin 40 -> wide mode switch

# =========================
# TIMING
# =========================

TICK_SEC = 0.01
PULSE_WIDTH_SEC = 0.005

RESET_HOLD_SEC = 0.15
READY_DELAY_SEC = 1.0
BUTTON_LOCK_AFTER_STOP_SEC = 2.0
DEBOUNCE_SEC = 0.05

TARGET_COUNT = 1000
TIMEOUT_COUNT = 2500

WIDE_WIN_MIN = 970
WIDE_WIN_MAX = 1020

# =========================
# SOUNDS
# =========================

ENABLE_RESET_SOUND = True
ENABLE_RUNNING_SOUND = True
ENABLE_FREEZE_SOUND = False
ENABLE_WIN_SOUND = True
ENABLE_FAIL_SOUND = True

DESKTOP = "/home/pi/Desktop"

SOUND_RESET = os.path.join(DESKTOP, "reset.mp3")
SOUND_RUNNING = os.path.join(DESKTOP, "running.mp3")
SOUND_FREEZE = os.path.join(DESKTOP, "freeze.mp3")
SOUND_WIN = os.path.join(DESKTOP, "win.mp3")
SOUND_FAIL = os.path.join(DESKTOP, "fail.mp3")

# =========================
# STATES
# =========================

STATE_HOME = "HOME"
STATE_RUNNING = "RUNNING"
STATE_FROZEN = "FROZEN"

state = STATE_HOME

count_cs = 0
ready_time = 0
button_locked_until = 0
next_tick = 0

sound_process = None


def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    output_pins = [
        PIN_PULSE_001,
        PIN_PULSE_01,
        PIN_PULSE_1,
        PIN_PULSE_10,
        PIN_RESET_MAIN,
        PIN_RESET_LOW,
    ]

    for pin in output_pins:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

    GPIO.setup(PIN_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_TEST_WIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_WIDE_MODE, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def stop_sound():
    global sound_process

    if sound_process is not None:
        try:
            sound_process.terminate()
            sound_process.wait(timeout=0.5)
        except Exception:
            try:
                os.kill(sound_process.pid, signal.SIGKILL)
            except Exception:
                pass

    sound_process = None


def play_sound(path, enabled=True, loop=False):
    global sound_process

    if not enabled:
        return

    if not os.path.exists(path):
        return

    stop_sound()

    try:
        if loop:
            sound_process = subprocess.Popen(
                ["mpg123", "-q", "--loop", "-1", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
            sound_process = subprocess.Popen(
                ["mpg123", "-q", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
    except Exception:
        sound_process = None


def pulse(pin):
    GPIO.output(pin, GPIO.HIGH)
    time.sleep(PULSE_WIDTH_SEC)
    GPIO.output(pin, GPIO.LOW)


def reset_low_digits():
    GPIO.output(PIN_RESET_LOW, GPIO.HIGH)
    time.sleep(RESET_HOLD_SEC)
    GPIO.output(PIN_RESET_LOW, GPIO.LOW)


def reset_all_digits():
    global count_cs

    GPIO.output(PIN_RESET_MAIN, GPIO.HIGH)
    GPIO.output(PIN_RESET_LOW, GPIO.HIGH)

    time.sleep(RESET_HOLD_SEC)

    GPIO.output(PIN_RESET_MAIN, GPIO.LOW)
    GPIO.output(PIN_RESET_LOW, GPIO.LOW)

    count_cs = 0


def win_correct_display_to_10_00():
    global count_cs

    reset_low_digits()
    count_cs = TARGET_COUNT


def increment_display():
    global count_cs

    count_cs += 1

    pulse(PIN_PULSE_001)

    if count_cs % 10 == 0:
        pulse(PIN_PULSE_01)

    if count_cs % 100 == 0:
        pulse(PIN_PULSE_1)

    if count_cs % 1000 == 0:
        pulse(PIN_PULSE_10)


def input_pressed(pin):
    if GPIO.input(pin) == GPIO.LOW:
        time.sleep(DEBOUNCE_SEC)
        return GPIO.input(pin) == GPIO.LOW
    return False


def wait_input_release(pin):
    while GPIO.input(pin) == GPIO.LOW:
        time.sleep(0.01)


def wide_mode_enabled():
    return GPIO.input(PIN_WIDE_MODE) == GPIO.LOW


def is_win_now(wide_mode):
    if wide_mode:
        return WIDE_WIN_MIN <= count_cs <= WIDE_WIN_MAX
    else:
        return count_cs == TARGET_COUNT


def continue_until_10_00():
    global next_tick

    next_tick = time.monotonic() + TICK_SEC

    while count_cs < TARGET_COUNT:
        now = time.monotonic()

        if now >= next_tick:
            increment_display()
            next_tick += TICK_SEC

        time.sleep(0.001)


def enter_home():
    global state, ready_time

    state = STATE_HOME
    ready_time = time.monotonic() + READY_DELAY_SEC
    play_sound(SOUND_FREEZE, ENABLE_FREEZE_SOUND, loop=True)


def enter_running():
    global state, next_tick

    state = STATE_RUNNING
    next_tick = time.monotonic() + TICK_SEC
    play_sound(SOUND_RUNNING, ENABLE_RUNNING_SOUND, loop=True)


def enter_frozen_after_stop(force_fail=False):
    global state, button_locked_until

    state = STATE_FROZEN
    button_locked_until = time.monotonic() + BUTTON_LOCK_AFTER_STOP_SEC

    if force_fail:
        play_sound(SOUND_FAIL, ENABLE_FAIL_SOUND, loop=False)
        return

    wide_mode_at_stop = wide_mode_enabled()

    if is_win_now(wide_mode_at_stop):
        if wide_mode_at_stop and count_cs < TARGET_COUNT:
            continue_until_10_00()

        win_correct_display_to_10_00()
        play_sound(SOUND_WIN, ENABLE_WIN_SOUND, loop=False)
    else:
        play_sound(SOUND_FAIL, ENABLE_FAIL_SOUND, loop=False)


def reset_game_to_home():
    reset_all_digits()
    play_sound(SOUND_RESET, ENABLE_RESET_SOUND, loop=False)
    enter_home()


def auto_test_win():
    global next_tick

    reset_all_digits()
    enter_running()

    while count_cs < TARGET_COUNT:
        now = time.monotonic()

        if now >= next_tick:
            increment_display()
            next_tick += TICK_SEC

        time.sleep(0.001)

    enter_frozen_after_stop(force_fail=False)


def main():
    global state, next_tick

    setup_gpio()

    reset_all_digits()
    enter_home()

    try:
        while True:
            now = time.monotonic()

            # Test win button
            if state in [STATE_HOME, STATE_FROZEN]:
                if now >= ready_time and now >= button_locked_until:
                    if input_pressed(PIN_TEST_WIN):
                        wait_input_release(PIN_TEST_WIN)
                        auto_test_win()

            # Main button
            if input_pressed(PIN_BUTTON):
                wait_input_release(PIN_BUTTON)

                now = time.monotonic()

                if state == STATE_HOME:
                    if now >= ready_time:
                        enter_running()

                elif state == STATE_RUNNING:
                    enter_frozen_after_stop(force_fail=False)

                elif state == STATE_FROZEN:
                    if now >= button_locked_until:
                        reset_game_to_home()

            # Running counter
            if state == STATE_RUNNING:
                now = time.monotonic()

                if now >= next_tick:
                    increment_display()
                    next_tick += TICK_SEC

                    if count_cs >= TIMEOUT_COUNT:
                        enter_frozen_after_stop(force_fail=True)

            time.sleep(0.001)

    except KeyboardInterrupt:
        pass

    finally:
        stop_sound()
        GPIO.cleanup()


if __name__ == "__main__":
    main()