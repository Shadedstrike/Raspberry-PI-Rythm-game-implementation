# Pi 2 Rhythm Visualizer

A lightweight Raspberry Pi song carousel and rhythm game for a 200+ track SD-card library. The expensive audio analysis happens once; gameplay reads a cached chart and stays responsive on a Pi 2.

## What is implemented

- Rotary album browser showing cover, title, artist, album, length, BPM, and difficulty (1–9).
- Offline/incremental scan of MP3, FLAC, M4A, AAC, OGG, WAV, and Opus files.
- Bass/kick targets plus mid-band analysis, embedded/folder artwork extraction, metadata, BPM, and computed difficulty. Easy charts follow bass; difficulty 4+ progressively adds separated synth/mid accents.
- One-to-one hit judging with difficulty-sensitive timing windows, score, combo, misses, accuracy, and grade.
- Existing controller compatibility over USB serial. The current PlatformIO firmware emits lines like `[BTN] GPIO 38 (idx 0) PRESSED`; all ten button presses count as taps.
- Bidirectional `PPR1` mode control: song playback mutes the controller synth while buttons, LEDs, and ESP-NOW remain active; normal synth mode is restored on exit or within three seconds of a lost Pi heartbeat.
- Keyboard development controls, so the UI can be tested without cabinet hardware.

The scoring follows `pixel-perfect-revolt/src/rhythm_game.cpp`: difficulty 1–9 tightens the early window from 125 ms to 69 ms, late presses receive 68 ms additional slack, and bass onsets are the primary targets. This project uses precomputed targets rather than detecting them during playback.

## Hardware

The default wiring keeps every control connection in physical pins **33–40**, at
the bottom end of the 40-pin Pi header. `config.toml` uses BCM GPIO numbers; the
table includes physical pin numbers so they cannot be confused.

| Control connection | BCM GPIO | Physical pin |
|---|---:|---:|
| RGB LED `B` through 220–330 Ω | GPIO12 | 32 |
| RGB LED `R` through 220–330 Ω | GPIO13 | 33 |
| Arcade button ground | GND | 34 |
| RGB LED `G` through 220–330 Ω | GPIO19 | 35 |
| SparkFun `SW` | GPIO16 | 36 |
| Arcade button signal | GPIO26 | 37 |
| SparkFun encoder `B` | GPIO20 | 38 |
| SparkFun encoder `C` and `GND` | GND | 39 |
| SparkFun encoder `A` | GPIO21 | 40 |
| RGB LED `+` | 3.3 V | 1 |

`A` and `B` are the quadrature signals, `C` is their common contact, and `SW` is
the shaft pushbutton. On the side labeled `R G SW B +`, the LED is common-anode:
connect `+` to **3.3 V**, then connect each `R`, `G`, and LED `B` cathode to its GPIO
through its own **220–330 Ω series resistor**. The GPIOs sink current, so the software
uses active-low LED outputs. Do not confuse the LED `B` with the separate encoder `B`
beside `A C B`. Never connect an LED color pin directly to a Pi GPIO. The shaft switch
and separate arcade button both act as start/pause controls.

Connect the ESP32-S3 controller to the Pi by USB. Add the runtime user to `dialout` if the serial port is not readable:

```sh
sudo usermod -aG dialout pi
```

Log out/reboot after changing groups. Avoid powering both boards from conflicting sources through the same USB connection.

## Pi OS installation

FFmpeg is the only external analysis tool. SDL packages keep pygame installation predictable on older Pi OS releases.

```sh
sudo apt update
sudo apt install -y ffmpeg python3-venv python3-pip \
  python3-pygame python3-numpy python3-pil python3-serial python3-gpiozero

cd /opt
sudo cp -a /path/to/pi2-rhythm-visualizer .
sudo chown -R pi:pi pi2-rhythm-visualizer
cd pi2-rhythm-visualizer
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e . --no-deps
```

When transferring by flash drive, copy the **entire** project directory—not only
the `src` folder. Raspberry Pi OS normally mounts the drive below
`/media/<your-user>/<drive-name>`. For example:

```sh
sudo cp -a /media/<your-user>/<drive-name>/pi2-rhythm-visualizer /opt/
sudo chown -R <your-user>:<your-user> /opt/pi2-rhythm-visualizer
```

Substitute the actual username and mounted drive/folder names. Then run the install
commands above from `/opt/pi2-rhythm-visualizer`.

Edit `config.toml`, especially `music_dir`. A convenient SD layout is:

```text
/media/pi/RHYTHM/
└── music/
    ├── Artist/Album/01 Song.mp3
    └── ...
```

## Pre-scan the card

```sh
cd /opt/pi2-rhythm-visualizer
.venv/bin/pi2-rhythm-scan --config config.toml
```

The scan writes `library.json` and resized artwork under `.cache/art`. It checkpoints after every track. Re-running skips files whose path, size, modification time, and analyzer version are unchanged; use `--force` to rebuild everything.

Analysis is intentionally conservative on RAM: 11.025 kHz mono audio and chunked FFT work suit a 1 GB Pi 2. Scanning 200 songs will still take time, so run it before the public experience starts. The UI never analyzes audio while playing.

## Run

```sh
.venv/bin/pi2-rhythm --config config.toml
```

Controls:

- Encoder turn or arrow keys: previous/next song.
- Encoder click, arcade button, or Enter: start/pause.
- Any controller press or Space: rhythm tap.
- Escape/Q: leave gameplay; press again in the browser to quit.

Pressing start during a song pauses playback and begins a 30-second inactivity
timer. Any encoder movement, encoder/arcade press, or controller-button press resumes
the same song immediately. With no activity, `ARE YOU STILL EXTANT???` flashes for
10 more seconds; after 40 total seconds the game stops the song, restores the
controller synth, and returns to the browser.

## Kiosk startup

Use Raspberry Pi OS **Desktop Autologin**. This starts pygame only after the display
and per-user audio session exist; a system daemon can race those services and open
with no screen or sound.

1. Run `sudo raspi-config`.
2. Select **System Options → Boot / Auto Login → Desktop Autologin**.
3. Disable screen blanking under **Display Options → Screen Blanking**.
4. Install the included desktop autostart entry for the user that logs in:

```sh
mkdir -p ~/.config/autostart
cp /opt/pi2-rhythm-visualizer/kiosk/pi2-rhythm.desktop ~/.config/autostart/
```

Ensure `[display] fullscreen = true` in `config.toml`, reboot, and the visualizer
will cover the desktop and hide the mouse cursor automatically. The desktop entry
expects the project at `/opt/pi2-rhythm-visualizer`; edit its `Exec` and `Path` if
you choose another location.

The file under `systemd/` is retained for custom X11 installations, but desktop
autostart is the supported Raspberry Pi OS kiosk method.

## Controller notes

The Pi parser deliberately consumes only `PRESSED` records, never releases. Flash the matching controller firmware containing `pi_link.cpp`, keep USB serial at 115200 baud, and do not open a second serial monitor at the same time. Button input still uses the controller's existing debug records; a future protocol revision can replace those with compact versioned button packets.

During playback the Pi sends `PPR1 MODE PI_GAME` once per second. The controller suppresses only its local synth/audio and continues scanning buttons and driving ESP-NOW effects. The Pi sends `PPR1 MODE NORMAL` at results, on exit, and during orderly shutdown. A controller-side three-second heartbeat timeout restores the synth if the Pi crashes or its USB cable is removed.

## Tests

```sh
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```
