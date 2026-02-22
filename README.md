# Cozmo Robot Controller

A comprehensive Python controller for the [Anki Cozmo](https://anki.bot/pages/meet-cozmo) robot (but version 1), built on [pycozmo](https://github.com/zayfod/pycozmo) with custom patches and an extended scripting language.

## About Cozmo

**Cozmo** is a miniature educational robot originally created by **Anki** (2016-2019) and later continued by **Digital Dream Labs**. It's a charming, palm-sized robot with a distinctive personality powered by an "emotion engine" that allows it to express feelings through animations, sounds, and facial expressions on its OLED screen.

### Hardware Specifications

| Feature | Specification |
|---------|---------------|
| **Dimensions** | ~10 cm (4 inches) tall |
| **Display** | 128×32 pixel OLED screen |
| **Camera** | 320×240 VGA camera |
| **Sensors** | Cliff detection IR, gyroscope, accelerometer |
| **Movement** | 2 tank treads, 1 lift arm, 1 head tilt |
| **Connectivity** | WiFi (creates own access point) |
| **Lights** | Backpack LEDs (5), IR head light |
| **Audio** | Built-in speaker |
| **Battery** | Li-ion, ~90 minutes runtime |

### Key Features

- **Facial Recognition**: Cozmo can recognize and remember faces
- **Emotion Engine**: Expresses happiness, sadness, surprise, and more
- **1000+ Animations**: Pre-programmed movements and sounds
- **Power Cubes**: Interactive cubes for games and activities
- **Programmable**: Supports Python SDK and visual coding (Code Lab)

### My story

I bought Cozmo ver 1, back at 2016 or 2017 because my younger son has seen it on Internet and he liked it. By the time I had the impression that this will be a great reason to introduce him to programming and robotics (he was 10 years old). But after playing with it for a while, he realized that - although it is intresting-  his is not interested. Oh GOD!, I would loved to have something like this, plus all the tools and languages and platforms that are now available, back at start of 80's when I was a teenager. Anyway, fast forward 10 years after, the robot accumilated dust, and I decided to give it a try............

---

## About pycozmo

**pycozmo** is a pure-Python communication library that provides an alternative SDK for Cozmo. Unlike the official Anki SDK, pycozmo:

- **No mobile device required**: Connects directly to Cozmo via WiFi
- **No cloud dependency**: Works completely offline
- **Low-level access**: Direct protocol communication
- **Open source**: Hosted on [GitHub](https://github.com/zayfod/pycozmo)

The library is based on reverse-engineering of the Cozmo protocol and provides access to:
- Motor control (wheels, lift, head)
- Camera streaming
- Audio playback
- Display rendering
- Animation playback
- Sensor data

> **Note**: The project is described by its author as "unstable and heavily under development."

---

## pycozmo Patches

During development, several bugs were discovered in pycozmo that prevented proper robot operation. These patches are **required** for my controller to work correctly. Your mileage may vary depending on your Cozmo's firmware version - i just do not know. I have the very first robot, the one without the button, era 2016 or 2017. I heavily used tcpdump to sniff and reverse engineer the communication between the android app (I have version 3.4 installed) and the Robot. Please see https://github.com/roryt12/pycozmo , this is the patched version I use. Again, YMMV.

---

## Features

### Robot Control
- ✅ **Movement**: Forward, backward, turning, precise navigation
- ✅ **Head Control**: Position control with angle aliases (up, down, middle)
- ✅ **Lift Control**: Speed-based control (position control not supported by firmware)
- ✅ **Lights**: Backpack LED control (individual and group)
- ✅ **Screen**: Text and image display on OLED

### Audio
- ✅ **Text-to-Speech**: Via espeak with voice/language/speed/pitch options
- ✅ **Sound Playback**: From Cozmo's asset library (2214 WEM files) or external files
- ✅ **Volume Control**: 0-65535 range

### Sensing
- ✅ **Cliff Detection**: Automatic stop on table edges (configurable reaction)
- ✅ **Battery Monitoring**: Voltage and percentage display
- ✅ **Camera**: Image capture

### Animations
- ✅ **Individual Animations**: 993 available
- ✅ **Animation Groups**: 573 groups for random selection

### Scripting
- ✅ **Variables**: Set and use with `$var` syntax
- ✅ **Loops**: `for` (range and list) and `while` loops
- ✅ **Conditions**: `if/else/endif` blocks
- ✅ **Subroutines**: `def/call` for reusable code
- ✅ **Includes**: Nested script files with spaces support
- ✅ **Async Execution**: Run animations and sounds in parallel

### Safety
- ✅ **Cliff Detection**: Enabled by default with configurable reactions
- ✅ **Connection Validation**: Detects failed connections (serial=0, battery=0V)
- ✅ **Loop Limits**: Max 1000 iterations to prevent infinite loops
- ✅ **Circular Include Protection**: Prevents infinite recursion

---

## Installation

### Prerequisites

1. **Python 3.8+** with pip
2. **espeak** for text-to-speech:
   ```bash
   sudo apt install espeak
   ```
3. **ffmpeg** for audio conversion:
   ```bash
   sudo apt install ffmpeg
   ```
4. **vgmstream-cli** for WEM audio files:
   ```bash
   # Build from source: https://github.com/vgmstream/vgmstream
   sudo make install
   ```
5. Last but not least, pycozmo library, original or patched


### Download Assets

On first run, pycozmo will download Cozmo assets (~500MB) to `~/.pycozmo/assets/`. The incuded script pycozmo_resources.py does this also.

---

## Quick Start

### Connect to Cozmo

1. Power on Cozmo
2. Lift the handles (or press the button, if it has one) to show WiFi credentials
3. Connect your computer to Cozmo's WiFi network
4. Run the controller:

```bash
python3 cozmo_controller.py status
```

### Basic Commands

```bash
# Say hello
python3 cozmo_controller.py "say Hello World"

# Move forward 100mm
python3 cozmo_controller.py "move 100"

# Play an animation
python3 cozmo_controller.py "anim-group DanceMambo"

# Check battery
python3 cozmo_controller.py "battery mode=voltage"
```

### Script File

Create `myscript.txt`:
```
# My first Cozmo script
say Hello! I am Cozmo.
head up
lights color=blue
anim-group CodeLabBored
```

Run it:
```bash
python3 cozmo_controller.py --script myscript.txt
```

---

## Command Reference

### Connection & Status

| Command | Description |
|---------|-------------|
| `connect` | Connect to robot |
| `status` | Show robot status |
| `wait` | Wait for robot to stabilize |
| `sleep` | `<duration>` | - | Pause execution (seconds) |

### Movement

| Command | Args | Options | Description |
|---------|------|---------|-------------|
| `move` | `<distance>` | `speed=100`, `async=false` | Move forward/backward (mm) |
| `turn` | `<angle>` | `async=false` | Turn by angle (degrees) |
| `goto` | `<x> <y>` | `angle=0`, `async=false` | Navigate to position |
| `lift` | `<speed>` | `duration=1.0`, `async=false` | Move lift (rad/s) |

### Head

| Command | Args | Options | Description |
|---------|------|---------|-------------|
| `head` | - | `angle=middle`, `async=false` | Set head angle |

**Angle aliases**: `down`, `bottom`, `lower`, `middle`, `neutral`, `center`, `upper`, `up`, `top`, or radians (-0.44 to 0.78)

### Lights

| Command | Args | Options | Description |
|---------|------|---------|-------------|
| `lights` | - | `color=blue`, `colors=...` | Set backpack LEDs |
| `ir` | - | `enable=true` | IR head light |

### Audio

| Command | Args | Options | Description |
|---------|------|---------|-------------|
| `say` | `<text>` | `voice=en-us`, `speed=150`, `pitch=50`, `amplitude=100`, `async=false` | Text-to-speech |
| `play-sound` | - | `name=...`, `file=...`, `async=false` | Play sound |
| `volume` | `<level>` | - | Set volume (0-65535) |

### Animation

| Command | Args | Options | Description |
|---------|------|---------|-------------|
| `animate` | `<name>` | `async=false`, `wait=2.0` | Play animation |
| `anim-group` | `<group>` | `async=false`, `wait=2.0` | Play animation group |
| `list-anims` | - | `search=...` | List animations (offline) |
| `list-groups` | - | `search=...` | List groups (offline) |
| `list-sounds` | - | `search=...` | List sounds (offline) |

**Animation Wait Parameter:**
- `wait=2.0` (default) - Block for 2 seconds after starting
- `wait=0` - Don't wait, continue immediately (use with `sleep`)
- `wait=5` - Block for 5 seconds

Example for long animations:
```
anim-group DanceMambo wait=0
sleep 5
lights color=blue
```

### Display & Camera

| Command | Args | Options | Description |
|---------|------|---------|-------------|
| `screen` | `<text>` | `duration=5.0`, `size=12`, `x=5`, `y=10` | Display text |
| `camera` | - | `output=camera_capture.jpg` | Capture image |
| `battery` | - | `mode=icon`, `duration=5.0` | Show battery |

### Safety

| Command | Args | Options | Description |
|---------|------|---------|-------------|
| `cliff` | - | `enable=true`, `reaction=backup` | Cliff detection |
| `calibrate` | - | `head=true`, `lift=true` | Calibrate motors |

---

## Scripting Language

### Variables

```
set name Cozmo
set count 5
set count=10           # Alternative syntax
say Hello $name        # Use variable
say ${name} is here    # Braces for clarity
```

### For Loops

```
# Range: 1 to 5
for i in 1..5
  say Count $i
endfor

# With step
for i in 0..10 step 2
  say Even number $i
endfor

# List of values
for color in red green blue
  lights color=$color
endfor
```

### While Loops

```
set count 5
while $count > 0
  say Countdown $count
  set count $count-1
endwhile
say Blast off!
```

### Conditions

```
if $count > 5
  say High count
else
  say Low count
endif

# Comparison operators: == != > < >= <=
```

### Subroutines

```
def greet
  say Hello!
  lights color=blue
enddef

call greet           # Call subroutine

# With arguments (accessible as $1, $2, etc.)
def announce
  say Attention: $1
enddef

call announce Important message
```

### Delays

```
say Starting
sleep 3              # Wait 3 seconds
say Three seconds later
sleep 0.5            # Wait half a second
```

### Includes

```
include "common setup.txt"
include "scripts/dance moves.txt"
include "path with spaces/script.txt"
```

### Full Example

```
# Dance party script
set rounds 3
set name Cozmo

for i in 1..$rounds
  say Round $i for $name
  
  # Sequential execution with timing control
  play-sound name=music
  sleep 1
  anim-group DanceMambo wait=0
  sleep 5
  
  lights color=blue
endfor

say Thanks for watching!
```

---

## Examples

### Patrol Script

```
# patrol.txt
set corners 4
for i in 1..$corners
  move 200
  turn 90
endfor
say Patrol complete
```

### Interactive Story

```
# story.txt
say Once upon a time
head down
anim-group CodeLabBored

head up
say there was a little robot
lights color=blue

anim-group DanceMambo wait=0
say who loved to dance!
```

### Battery Check Routine

```
# battery_check.txt
battery mode=text
say Battery status displayed on screen
```

---

## Troubleshooting

### Connection Issues

**Problem**: "Connection failed: serial number is 0"
- Ensure Cozmo is powered on (blue light visible)
- Verify you're connected to Cozmo's WiFi network
- Check firewall allows UDP port 5551

**Problem**: "Connection failed: battery voltage is 0.0V"
- Robot state not received - wait longer or reconnect
- Try pressing Cozmo's button to re-broadcast WiFi

### Audio Issues

**Problem**: "Error generating TTS"
- Install espeak: `sudo apt install espeak`

**Problem**: "Error converting with vgmstream-cli"
- Install vgmstream-cli for WEM file support
- Or use external audio files with `file=` option

### Animation Issues

**Problem**: "Animation not found"
- Use `list-anims` to find correct names
- Animation groups: `list-groups`

**Problem**: Sound doesn't play during animation
- Cozmo has a single audio channel
- Animations with embedded audio will interrupt custom sounds
- Use `async=true` and ensure animations don't have sound

### Movement Issues

**Problem**: Lift position control doesn't work
- This is a firmware limitation
- Use speed control with `lift <speed> duration=X`

**Problem**: Robot doesn't stop at table edge
- Cliff detection must be enabled: `cliff enable=true`
- Default reaction is to backup

---

## Known Limitations

1. **Lift Position Control**: Firmware doesn't respond to position commands - use speed control
2. **Audio Channel**: Single channel - animations with sound will interrupt
3. **Procedural Face**: Must be disabled for custom screen content
4. **Async Audio**: Robot must stay connected until audio transmits

---

## Credits

- **Anki / Digital Dream Labs** - Cozmo robot
- **zayfod** - [pycozmo library](https://github.com/zayfod/pycozmo)
- **vgmstream** - WEM audio decoding

---

