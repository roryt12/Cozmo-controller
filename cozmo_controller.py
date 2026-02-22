#!/usr/bin/env python3
"""
Cozmo Robot Control Module - COMPREHENSIVE VERSION

KNOWN WORKING FEATURES:
✓ Connection and initialization
✓ Head position control (set_head_angle with radians, range -0.44 to 0.78)
✓ Lift speed control (move_lift with rad/s) - POSITION CONTROL DOES NOT WORK
✓ Wheel drive (drive_wheels with mm/s)
✓ Precise turning (turn_to_angle with tolerance)
✓ Path following (go_to_pose)
✓ Camera streaming (320x240 JPEG)
✓ Screen display (128x32 OLED)
✓ TTS audio playback (via espeak)
✓ Volume control
✓ Backpack LED control (individual + all)
✓ IR head light for night vision
✓ Cliff detection (auto-stop on edges)
✓ Motor calibration
✓ Animation playback (individual + groups)
✓ Robot state feedback (battery, pose, etc.)

NOT WORKING:
✗ Lift position control (SetLiftHeight with mm) - robot doesn't respond
"""

import sys
import time
import argparse
import json
import os
import subprocess
import shutil
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

try:
    import pycozmo
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from pycozmo import protocol_encoder, lights, event
    from pycozmo.expressions import Happiness, Sadness, Anger, Surprise, Neutral
except ImportError as e:
    print(f"Error: pycozmo not installed. Run: pip install --user pycozmo")
    sys.exit(1)

TTS_AVAILABLE = True
ESPEAK_CMD = "/usr/bin/espeak"


class CozmoController:
    """Controller class for Cozmo robot - FIXED based on testing."""

    # Cliff reaction types
    CLIFF_REACTION_STOP = "stop"
    CLIFF_REACTION_BACKUP = "backup"
    CLIFF_REACTION_ANIMATE = "animate"
    CLIFF_REACTION_NONE = "none"

    def __init__(self, auto_connect: bool = True):
        self.cli: Optional[pycozmo.Client] = None
        self.connected = False
        self.anims_loaded = False
        self.battery_voltage = 0.0
        self.head_angle = 0.0
        self._clip_metadata = {}
        self._animation_groups = {}
        self._pending_audio_time = 0.0
        self._bg_threads: List[threading.Thread] = []
        self._bg_lock = threading.Lock()

        # Cliff detection settings
        self._cliff_enabled = True
        self._cliff_reaction = self.CLIFF_REACTION_BACKUP  # stop, backup, animate, none
        self._cliff_detected = False

        # TTS audio directory
        self.tts_dir = Path.home() / ".cozmo" / "tts"
        self.tts_dir.mkdir(parents=True, exist_ok=True)
        self._sound_files = []  # Cache for sound file info

        if auto_connect:
            self.connect()

    def connect(self, retries: int = 3, delay: float = 2.0) -> bool:
        """Connect to Cozmo robot."""
        for attempt in range(retries):
            try:
                print(f"Connecting to Cozmo... (attempt {attempt + 1}/{retries})")
                
                # Create client with proper initialization
                # Disable procedural_face to prevent it from overriding screen
                self.cli = pycozmo.Client(
                    auto_initialize=True,
                    enable_animations=True,
                    enable_procedural_face=False
                )
                
                self.cli.start()
                self.cli.connect()
                time.sleep(3)  # Wait for connection

                if self.cli is None:
                    print(f"✗ Connection failed: cli is None")
                    continue

                # Setup battery monitoring
                self.cli.add_handler(protocol_encoder.RobotState, self._on_robot_state)

                # Wait for robot state to be received
                time.sleep(1)

                # Validate connection - check for valid serial and battery
                if self.cli.serial_number == 0:
                    print(f"✗ Connection failed: serial number is 0 (not really connected)")
                    self.disconnect()
                    continue
                
                # Battery voltage of 0.0 means robot state not received yet
                # A real battery will be 3.5V-4.2V (low battery is still ~3.2V)
                if self.cli.battery_voltage == 0.0:
                    print(f"✗ Connection failed: battery voltage is 0.0V (robot state not received)")
                    self.disconnect()
                    continue

                # Set head to neutral position (0.17 rad is middle)
                self.cli.set_head_angle(0.17)
                time.sleep(0.5)
                
                # Setup cliff detection by default
                if self._cliff_enabled:
                    self._setup_cliff_detection()

                self.connected = True
                print("✓ Connected to Cozmo!")
                print(f"   Serial: {self.cli.serial_number}")
                print(f"   Battery: {self.cli.battery_voltage:.2f}V")
                print(f"   Cliff detection: enabled (reaction={self._cliff_reaction})")

                return True
                
            except Exception as e:
                print(f"✗ Connection failed: {e}")
                import traceback
                traceback.print_exc()
                if attempt < retries - 1:
                    time.sleep(delay)
                else:
                    print("\nTroubleshooting:")
                    print("1. Make sure Cozmo is on and displaying WiFi PSK")
                    print("2. Connect your computer to Cozmo's WiFi network")
                    print("3. Ensure firewall allows UDP traffic on port 5551")

        return False

    def _on_robot_state(self, cli, pkt):
        """Handle robot state updates."""
        self.battery_voltage = getattr(pkt, 'battery_voltage', self.battery_voltage)
        self.head_angle = getattr(pkt, 'head_angle_rad', self.head_angle)
    
    def _setup_cliff_detection(self):
        """Setup cliff detection handler and enable it."""
        if not self.cli:
            return
        
        # Register cliff detection event handler
        self.cli.add_handler(pycozmo.event.EvtCliffDetectedChange, self._on_cliff_detected)
        
        # Enable cliff detection in firmware
        self.cli.conn.send(protocol_encoder.EnableStopOnCliff(enable=True))
    
    def _on_cliff_detected(self, cli, state: bool):
        """Handle cliff detection event."""
        if state:
            self._cliff_detected = True
            print("\n⚠ CLIFF DETECTED!")
            
            # Execute reaction based on setting
            self._execute_cliff_reaction()
    
    def _execute_cliff_reaction(self):
        """Execute the configured cliff reaction."""
        if self._cliff_reaction == self.CLIFF_REACTION_NONE:
            return
        
        # Always stop motors first
        try:
            self.cli.stop_all_motors()
        except:
            pass
        
        if self._cliff_reaction == self.CLIFF_REACTION_STOP:
            print("Cliff reaction: stopped")
        
        elif self._cliff_reaction == self.CLIFF_REACTION_BACKUP:
            print("Cliff reaction: backing up...")
            # Back up slowly
            pkt = protocol_encoder.DriveWheels(lwheel_speed_mmps=-50, rwheel_speed_mmps=-50)
            self.cli.conn.send(pkt)
            time.sleep(1.0)
            self.cli.stop_all_motors()
            print("Cliff reaction: backed up")
        
        elif self._cliff_reaction == self.CLIFF_REACTION_ANIMATE:
            print("Cliff reaction: playing animation...")
            try:
                if not self.anims_loaded:
                    self.load_animations()
                self.cli.play_anim_group("ReactToCliff")
                time.sleep(2.0)
            except:
                pass
    
    def set_cliff_reaction(self, reaction: str = "backup"):
        """Set what happens when a cliff is detected.
        
        Args:
            reaction: "stop", "backup", "animate", or "none"
        """
        valid = {self.CLIFF_REACTION_STOP, self.CLIFF_REACTION_BACKUP, 
                 self.CLIFF_REACTION_ANIMATE, self.CLIFF_REACTION_NONE}
        
        reaction = reaction.lower()
        if reaction not in valid:
            print(f"Invalid reaction: {reaction}. Valid: stop, backup, animate, none")
            return False
        
        self._cliff_reaction = reaction
        print(f"Cliff reaction set to: {reaction}")
        return True
    
    def is_cliff_detected(self) -> bool:
        """Check if cliff was detected (resets after reading)."""
        detected = self._cliff_detected
        self._cliff_detected = False
        return detected

    def disconnect(self):
        """Disconnect from Cozmo."""
        # Wait for all background threads to complete
        self._wait_for_bg_threads()
        
        if self.cli:
            try:
                self.cli.stop()
            except:
                pass
        
        self.cli = None
        self.connected = False
        print("Disconnected from Cozmo")
    
    def _run_in_background(self, func, *args, **kwargs):
        """Run a function in a background thread."""
        def wrapper():
            try:
                func(*args, **kwargs)
            except Exception as e:
                print(f"Background task error: {e}")
        
        with self._bg_lock:
            # Clean up finished threads
            self._bg_threads = [t for t in self._bg_threads if t.is_alive()]
            
            thread = threading.Thread(target=wrapper, daemon=True)
            self._bg_threads.append(thread)
            thread.start()
        return thread
    
    def _wait_for_bg_threads(self, timeout: float = 30.0):
        """Wait for all background threads to complete."""
        with self._bg_lock:
            threads = list(self._bg_threads)
        
        if not threads:
            return
        
        print(f"Waiting for {len(threads)} background task(s)...")
        for thread in threads:
            thread.join(timeout=timeout)
        
        with self._bg_lock:
            self._bg_threads = [t for t in self._bg_threads if t.is_alive()]

    def is_connected(self) -> bool:
        """Check if actually connected to robot (not just flag set).
        
        Returns False if:
        - connected flag is False
        - client is None
        - serial_number is 0 (robot state not received)
        - battery_voltage is 0.0 (robot state not received)
        
        Note: A low battery (3.2V-3.5V) is still valid - only 0.0V indicates no data.
        """
        if not self.connected or not self.cli:
            return False
        if self.cli.serial_number == 0:
            return False
        if self.cli.battery_voltage == 0.0:
            return False
        return True

    def load_animations(self):
        """Load animation assets."""
        if not self.connected or not self.cli:
            print("Not connected to Cozmo")
            return False

        try:
            self.cli.load_anims()
            self.anims_loaded = True
            print("✓ Animations loaded")
            return True
        except Exception as e:
            print(f"Error loading animations: {e}")
            return False

    def set_volume(self, level: int = 65535):
        """Set robot volume level.

        Args:
            level: Volume 0-65535 (0=silent, 65535=max)
        """
        if not self.connected:
            return False

        try:
            level = max(0, min(65535, level))
            self.cli.conn.send(protocol_encoder.SetRobotVolume(level=level))
            print(f"Volume set to {level}")
            return True
        except Exception as e:
            print(f"Error setting volume: {e}")
            return False

    def say_text(self, text: str, volume: int = 65535, voice: str = "en-us",
                 speed: int = 150, pitch: int = 50, amplitude: int = 100, async_mode: bool = False) -> bool:
        """Generate speech using espeak and play it on Cozmo.

        TTS happens inside this script using espeak.

        Args:
            text: Text to speak
            volume: Robot volume level 0-65535 (default: 65535 = max)
            voice: Espeak voice/language (default: en-us). Examples: en-gb, de, fr, es, it
            speed: Speed in words per minute (default: 150, range: 80-450)
            pitch: Pitch 0-99 (default: 50)
            amplitude: Amplitude 0-200 (default: 100)
            async_mode: If True, run in background thread
        """
        if not self.connected or not self.cli:
            print("Not connected to Cozmo")
            return False

        def _play():
            try:
                wav_path = self.tts_dir / f"speech_{int(time.time())}.wav"

                speed_val = max(80, min(450, speed))
                pitch_val = max(0, min(99, pitch))
                amp_val = max(0, min(200, amplitude))

                cmd = [
                    ESPEAK_CMD,
                    "-v", voice,
                    "-s", str(speed_val),
                    "-p", str(pitch_val),
                    "-a", str(amp_val),
                    "-w", str(wav_path),
                    text
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode != 0:
                    print(f"Error generating TTS: {result.stderr}")
                    return

                self.set_volume(volume)
                time.sleep(0.2)

                if not wav_path.exists():
                    print(f"Error: WAV file not created: {wav_path}")
                    return

                file_size = wav_path.stat().st_size
                print(f"Generated audio: {file_size} bytes (voice={voice}, speed={speed_val}, pitch={pitch_val})")

                import wave
                with wave.open(str(wav_path), 'r') as w:
                    duration = w.getnframes() / w.getframerate()
                
                self.cli.play_audio(str(wav_path))
                print(f"Saying: {text}")
                print(f"Audio duration: {duration:.1f}s")
                time.sleep(duration + 0.5)

            except Exception as e:
                print(f"Error in TTS: {e}")

        if async_mode:
            print(f"Saying (async): {text}")
            self._run_in_background(_play)
            return True
        else:
            _play()
            return True
            return False

    def set_head_angle(self, angle: float = 0.17, async_mode: bool = False):
        """Set Cozmo's head angle.
        
        Args:
            angle: Angle in radians (-0.44 to 0.78)
                  -0.44 = looking down, 0.78 = looking up, 0.17 = middle
            async_mode: If True, return immediately
        """
        if not self.connected:
            return False

        try:
            angle = max(-0.44, min(0.78, angle))
            self.cli.set_head_angle(angle)
            if not async_mode:
                time.sleep(0.5)
            return True
        except Exception as e:
            print(f"Error setting head angle: {e}")
            return False

    def move_lift(self, speed: float = 0.5, duration: float = 1.0, async_mode: bool = False):
        """Move Cozmo's lift with speed control.
        
        NOTE: Lift POSITION control does not work on this robot.
        Use speed control instead.
        
        Args:
            speed: Speed in rad/s (positive = up, negative = down)
            duration: How long to move (seconds)
            async_mode: If True, return immediately (NOTE: lift won't stop!)
        """
        if not self.connected:
            return False

        try:
            pkt = protocol_encoder.MoveLift(speed_rad_per_sec=speed)
            self.cli.conn.send(pkt)
            if not async_mode:
                time.sleep(duration)
                self.cli.stop_all_motors()
            return True
        except Exception as e:
            print(f"Error moving lift: {e}")
            return False

    def drive_wheels(self, left_speed: float, right_speed: float, duration: float = 1.0, async_mode: bool = False):
        """Drive Cozmo's wheels.
        
        Args:
            left_speed: Left wheel speed in mm/s
            right_speed: Right wheel speed in mm/s  
            duration: How long to drive (seconds)
            async_mode: If True, return immediately (NOTE: wheels won't stop!)
        """
        if not self.connected:
            return False

        try:
            pkt = protocol_encoder.DriveWheels(
                lwheel_speed_mmps=left_speed,
                rwheel_speed_mmps=right_speed
            )
            self.cli.conn.send(pkt)
            if not async_mode:
                time.sleep(duration)
                self.cli.stop_all_motors()
            return True
        except Exception as e:
            print(f"Error driving wheels: {e}")
            return False

    def move_forward(self, distance_mm: float = 100, speed_mmps: float = 100, async_mode: bool = False):
        """Move Cozmo forward."""
        duration = distance_mm / speed_mmps
        return self.drive_wheels(speed_mmps, speed_mmps, duration, async_mode)

    def move_backward(self, distance_mm: float = 100, speed_mmps: float = 100, async_mode: bool = False):
        """Move Cozmo backward."""
        duration = distance_mm / speed_mmps
        return self.drive_wheels(-speed_mmps, -speed_mmps, duration, async_mode)

    def turn_in_place(self, angle_degrees: float = 90, async_mode: bool = False):
        """Turn Cozmo in place.
        
        Args:
            angle_degrees: Angle to turn (positive = left, negative = right)
            async_mode: If True, return immediately (NOTE: wheels won't stop!)
        """
        if not self.connected:
            return False

        try:
            duration = abs(angle_degrees) / 90.0
            speed = 100 if angle_degrees > 0 else -100
            
            if angle_degrees > 0:
                self.drive_wheels(-speed, speed, duration, async_mode)
            else:
                self.drive_wheels(speed, -speed, duration, async_mode)
            return True
        except Exception as e:
            print(f"Error turning: {e}")
            return False

    def set_backpack_lights(self, color: str = "blue"):
        """Set backpack LED color.

        Available colors: red, green, blue, white, off
        """
        if not self.connected:
            return False

        try:
            color_map = {
                "red": lights.red_light,
                "green": lights.green_light,
                "blue": lights.blue_light,
                "white": lights.white_light,
                "off": lights.off_light,
            }

            light = color_map.get(color.lower(), lights.blue_light)
            self.cli.set_all_backpack_lights(light)
            return True
        except Exception as e:
            print(f"Error setting lights: {e}")
            return False

    def set_backpack_lights_individual(self, colors: list):
        """Set individual backpack LED colors.

        Args:
            colors: List of 5 colors for [left, front, middle, back, right]
                   Available: red, green, blue, white, off
        """
        if not self.connected:
            return False

        try:
            color_map = {
                "red": lights.red_light,
                "green": lights.green_light,
                "blue": lights.blue_light,
                "white": lights.white_light,
                "off": lights.off_light,
            }

            if len(colors) != 5:
                print("Error: Must provide exactly 5 colors")
                return False

            light_list = [color_map.get(c.lower(), lights.off_light) for c in colors]
            self.cli.set_backpack_lights(light_list)
            return True
        except Exception as e:
            print(f"Error setting individual lights: {e}")
            return False

    def set_head_light(self, enable: bool = True):
        """Enable/disable IR head light for night vision.

        Args:
            enable: True to turn on IR LED, False to turn off
        """
        if not self.connected:
            return False

        try:
            self.cli.set_head_light(enable)
            status = "on" if enable else "off"
            print(f"Head light (IR) turned {status}")
            return True
        except Exception as e:
            print(f"Error setting head light: {e}")
            return False

    def enable_cliff_detection(self, enable: bool = True):
        """Enable/disable automatic stop on cliff detection.

        Prevents robot from falling off edges.
        """
        if not self.connected:
            return False

        try:
            self._cliff_enabled = enable
            pkt = protocol_encoder.EnableStopOnCliff(enable=enable)
            self.cli.conn.send(pkt)
            status = "enabled" if enable else "disabled"
            print(f"Cliff detection {status} (reaction={self._cliff_reaction})")
            return True
        except Exception as e:
            print(f"Error setting cliff detection: {e}")
            return False

    def turn_to_angle(self, angle_rad: float, speed_rad_per_sec: float = 3.0,
                      accel_rad_per_sec2: float = 10.0, tolerance_rad: float = 0.05, async_mode: bool = False):
        """Turn robot to a specific angle with precision.

        More accurate than turn_in_place for positioning.

        Args:
            angle_rad: Target angle in radians (positive = left/CCW, negative = right/CW)
            speed_rad_per_sec: Maximum turn speed (default: 3.0)
            accel_rad_per_sec2: Acceleration (default: 10.0)
            tolerance_rad: Angle tolerance for completion (default: 0.05 = ~3 degrees)
            async_mode: If True, return immediately
        """
        if not self.connected:
            return False

        try:
            pkt = protocol_encoder.TurnInPlace(
                angle_rad=angle_rad,
                speed_rad_per_sec=speed_rad_per_sec,
                accel_rad_per_sec2=accel_rad_per_sec2,
                angle_tolerance_rad=tolerance_rad,
                is_absolute=False
            )
            self.cli.conn.send(pkt)
            if not async_mode:
                est_time = abs(angle_rad) / speed_rad_per_sec + 0.5
                time.sleep(est_time)
            return True
        except Exception as e:
            print(f"Error turning to angle: {e}")
            return False

    def calibrate_motors(self, head: bool = True, lift: bool = True):
        """Calibrate head and/or lift motors.

        Useful if robot has been moved manually or after power on.
        Should be run if position control seems inaccurate.

        Args:
            head: Calibrate head motor
            lift: Calibrate lift motor
        """
        if not self.connected:
            return False

        try:
            pkt = protocol_encoder.StartMotorCalibration(head=head, lift=lift)
            self.cli.conn.send(pkt)
            print(f"Calibrating motors: head={head}, lift={lift}")
            # Wait for calibration - takes a few seconds
            time.sleep(3)
            return True
        except Exception as e:
            print(f"Error calibrating motors: {e}")
            return False

    def go_to_pose(self, x_mm: float, y_mm: float, angle_rad: float = 0.0):
        """Navigate to a specific pose (position and orientation).

        Args:
            x_mm: Target X position in millimeters
            y_mm: Target Y position in millimeters
            angle_rad: Target angle in radians (default: 0)
        """
        if not self.connected:
            return False

        try:
            self.cli.go_to_pose(x_mm, y_mm, angle_rad)
            return True
        except Exception as e:
            print(f"Error going to pose: {e}")
            return False

    def wait_for_robot(self):
        """Wait for robot to be ready and stable."""
        if not self.connected:
            return False

        try:
            self.cli.wait_for_robot()
            return True
        except Exception as e:
            print(f"Error waiting for robot: {e}")
            return False

    def play_anim_group(self, group_name: str = "CodeLabBored", async_mode: bool = False):
        """Play an animation group (plays a random animation from the group).

        Args:
            group_name: Name of animation group 
                          (e.g., "CodeLabBored", "CodeLabChicken", "DanceMambo", "FistBumpSuccess")
            async_mode: If True, run in background thread
        """
        if not self.connected:
            return False

        def _play():
            try:
                if not self.anims_loaded:
                    self.load_animations()
                self.cli.play_anim_group(group_name)
                time.sleep(2.0)
            except Exception as e:
                print(f"Error playing animation group: {e}")

        if async_mode:
            print(f"Playing animation group (async): {group_name}")
            self._run_in_background(_play)
        else:
            print(f"Playing animation group: {group_name}")
            _play()
        return True

    def play_animation(self, anim_name: str = "anim_bored_01", async_mode: bool = False):
        """Play an animation.
        
        Args:
            anim_name: Name of animation to play
            async_mode: If True, run in background thread
        """
        if not self.connected:
            return False

        def _play():
            try:
                if not self.anims_loaded:
                    self.load_animations()
                self.cli.play_anim(anim_name)
                time.sleep(2.0)
            except Exception as e:
                print(f"Error playing animation: {e}")

        if async_mode:
            print(f"Playing animation (async): {anim_name}")
            self._run_in_background(_play)
        else:
            print(f"Playing animation: {anim_name}")
            _play()
        return True

    def list_animations(self, search: str = None):
        """List available animations.
        
        Args:
            search: Optional filter string to search animation names
        """
        try:
            # Load animation metadata if not loaded
            if not self.anims_loaded:
                pycozmo.util.check_assets()
                anim_dir = str(pycozmo.util.get_cozmo_anim_dir())
                self._clip_metadata = pycozmo.anim_encoder.get_clip_metadata(anim_dir)
            
            names = sorted(self._clip_metadata.keys())
            
            if search:
                search = search.lower()
                names = [n for n in names if search in n.lower()]
            
            print(f"Available animations ({len(names)} total):")
            for name in names:
                print(f"  {name}")
            
            return True
        except Exception as e:
            print(f"Error listing animations: {e}")
            return False

    def list_animation_groups(self, search: str = None):
        """List available animation groups.
        
        Args:
            search: Optional filter string to search group names
        """
        try:
            # Load animation groups if not loaded
            if not self.anims_loaded:
                pycozmo.util.check_assets()
                resource_dir = str(pycozmo.util.get_cozmo_asset_dir())
                self._animation_groups = pycozmo.anim.load_animation_groups(resource_dir)
            
            names = sorted(self._animation_groups.keys())
            
            if search:
                search = search.lower()
                names = [n for n in names if search in n.lower()]
            
            print(f"Available animation groups ({len(names)} total):")
            for name in names:
                print(f"  {name}")
            
            return True
        except Exception as e:
            print(f"Error listing animation groups: {e}")
            return False

    def list_sounds(self, search: str = None):
        """List available sounds from assets.
        
        Args:
            search: Optional filter string to search sound names
        """
        try:
            import xml.etree.ElementTree as ET
            
            # Load sound info from SoundbanksInfo.xml
            sound_dir = pycozmo.util.get_cozmo_asset_dir() / "cozmo_resources" / "sound"
            info_path = sound_dir / "SoundbanksInfo.xml"
            
            if not info_path.exists():
                print(f"Sound info not found: {info_path}")
                return False
            
            # Parse XML
            tree = ET.parse(info_path)
            root = tree.getroot()
            
            sounds = []
            for file_elem in root.findall('.//File'):
                file_id = file_elem.get('Id')
                short_name = file_elem.findtext('ShortName', '')
                language = file_elem.get('Language', 'SFX')
                sounds.append({
                    'id': int(file_id) if file_id else 0,
                    'name': short_name,
                    'language': language
                })
            
            # Sort by name
            sounds.sort(key=lambda x: x['name'])
            
            if search:
                search = search.lower()
                sounds = [s for s in sounds if search in s['name'].lower() or search in str(s['id'])]
            
            print(f"Available sounds ({len(sounds)} total):")
            for s in sounds:
                print(f"  {s['id']:10d} | {s['name']}")
            
            return True
        except Exception as e:
            print(f"Error listing sounds: {e}")
            return False

    def play_sound(self, name: str = None, file: str = None, async_mode: bool = False):
        """Play a sound from assets or a local file on the robot.
        
        Args:
            name: Partial sound name to search in assets (uses vgmstream-cli)
            file: Path to local sound file (uses ffmpeg: MP3, WAV, OGG, etc.)
            async_mode: If True, run in background thread
        """
        if not self.connected:
            print("Not connected to robot")
            return False
        
        def _play():
            try:
                temp_wav = self.tts_dir / f"sound_{int(time.time())}.wav"
                
                if file:
                    file_path = Path(file)
                    if not file_path.exists():
                        print(f"File not found: {file}")
                        return
                    
                    result = subprocess.run(
                        ['ffmpeg', '-y', '-i', str(file_path), 
                         '-acodec', 'pcm_s16le', '-ar', '22050', '-ac', '1',
                         str(temp_wav)],
                        capture_output=True, text=True
                    )
                    
                    if result.returncode != 0:
                        print(f"Error converting with ffmpeg:")
                        print(result.stderr[:300] if result.stderr else "ffmpeg failed")
                        return
                    
                elif name:
                    import xml.etree.ElementTree as ET
                    
                    sound_dir = pycozmo.util.get_cozmo_asset_dir() / "cozmo_resources" / "sound"
                    info_path = sound_dir / "SoundbanksInfo.xml"
                    
                    if not info_path.exists():
                        print(f"Sound assets info not found")
                        return
                    
                    tree = ET.parse(info_path)
                    root = tree.getroot()
                    
                    found_file = None
                    for file_elem in root.findall('.//File'):
                        short_name = file_elem.findtext('ShortName', '')
                        if name.lower() in short_name.lower():
                            found_file = file_elem
                            break
                    
                    if found_file is None:
                        print(f"Sound not found: {name}")
                        return
                    
                    file_id = found_file.get('Id')
                    short_name = found_file.findtext('ShortName', '')
                    path_elem = found_file.findtext('Path', '')
                    
                    wem_path = sound_dir / path_elem
                    if not wem_path.exists():
                        wem_path = sound_dir / f"{file_id}.wem"
                    
                    if not wem_path.exists():
                        for root_dir, dirs, files in os.walk(sound_dir):
                            for f in files:
                                if f == f"{file_id}.wem":
                                    wem_path = Path(root_dir) / f
                                    break
                    
                    if not wem_path.exists():
                        print(f"WEM file not found for sound {file_id}")
                        return
                    
                    temp_raw = self.tts_dir / f"sound_{int(time.time())}_raw.wav"
                    
                    result = subprocess.run(
                        ['vgmstream-cli', '-o', str(temp_raw), str(wem_path)],
                        capture_output=True, text=True
                    )
                    
                    if result.returncode != 0:
                        print(f"Error converting with vgmstream-cli:")
                        print(result.stderr[:300] if result.stderr else "vgmstream-cli failed")
                        return
                    
                    result = subprocess.run(
                        ['ffmpeg', '-y', '-i', str(temp_raw), 
                         '-acodec', 'pcm_s16le', '-ar', '22050', '-ac', '1',
                         str(temp_wav)],
                        capture_output=True, text=True
                    )
                    
                    if temp_raw.exists():
                        temp_raw.unlink()
                    
                    if result.returncode != 0:
                        print(f"Error converting with ffmpeg:")
                        print(result.stderr[:300] if result.stderr else "ffmpeg failed")
                        return
                    
                    print(f"Playing sound: {short_name}")
                    
                else:
                    print("Error: specify name= or file=")
                    return
                
                if not temp_wav.exists():
                    print(f"Error: converted file not created")
                    return
                
                import wave
                with wave.open(str(temp_wav), 'r') as w:
                    duration = w.getnframes() / w.getframerate()
                
                self.cli.play_audio(str(temp_wav))
                print(f"Sound duration: {duration:.1f}s")
                time.sleep(duration + 0.5)
                
            except Exception as e:
                print(f"Error playing sound: {e}")
                import traceback
                traceback.print_exc()

        if async_mode:
            if file:
                print(f"Playing sound (async): {Path(file).name}")
            elif name:
                print(f"Playing sound (async): {name}")
            self._run_in_background(_play)
        else:
            _play()
        return True

    def display_text_on_screen(self, text: str, duration: float = 5.0, font_size: int = 12, 
                                x: int = 5, y: int = 10, clear_after: bool = True):
        """Display text on Cozmo's OLED screen.
        
        Screen is 128x32 pixels, black and white.
        
        Args:
            text: Text to display (supports \\n for newline, \\t for tab)
            duration: How long to display (seconds)
            font_size: Font size in pixels (default 12, range 8-24)
            x: X position (default 5)
            y: Y position (default 10)
            clear_after: Clear screen after duration (default True)
        """
        if not self.connected:
            return False

        try:
            img = Image.new('1', (128, 32), color=0)
            draw = ImageDraw.Draw(img)
            
            # Clamp font size
            font_size = max(8, min(24, font_size))
            
            # Process escape sequences manually (don't use unicode_escape - it corrupts UTF-8)
            # Only replace specific escape sequences
            text = text.replace('\\n', '\n')
            text = text.replace('\\t', '\t')
            text = text.replace('\\r', '\r')
            
            # Try to use a scalable font, fall back to default
            font = None
            font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
            if os.path.exists(font_path):
                font = ImageFont.truetype(font_path, font_size)
            
            # Draw text
            if font:
                draw.text((x, y), text, fill=1, font=font)
                print(f"Displaying with font size {font_size}: '{text}'")
            else:
                draw.text((x, y), text, fill=1)
                print(f"Displaying with default font: '{text}'")
            
            # Display
            self.cli.display_image(img)
            time.sleep(duration)
            
            if clear_after:
                self.cli.clear_screen()
            return True
        except Exception as e:
            print(f"Error displaying text: {e}")
            import traceback
            traceback.print_exc()
            return False

    def capture_camera_image(self, output_path: str = "camera_capture.jpg"):
        """Capture an image from Cozmo's camera."""
        if not self.connected:
            return False

        try:
            # Set head to middle for best view
            self.set_head_angle(0.17)
            
            # Enable camera
            self.cli.enable_camera(enable=True, color=True)
            time.sleep(2.0)

            image_path = Path(output_path)
            captured = [False]
            
            def on_camera_image(cli, image):
                image.save(str(image_path), "JPEG")
                captured[0] = True

            self.cli.add_handler(pycozmo.event.EvtNewRawCameraImage, on_camera_image, one_shot=True)
            time.sleep(1)

            return str(image_path) if captured[0] else False

        except Exception as e:
            print(f"Error capturing image: {e}")
            return False

    def _voltage_to_percentage(self, voltage: float) -> float:
        """Convert voltage to approximate percentage."""
        # Cozmo Li-ion battery: 4.2V = 100%, 3.5V = 0%
        min_v = 3.5
        max_v = 4.2
        pct = (voltage - min_v) / (max_v - min_v) * 100
        return max(0, min(100, pct))

    def _draw_battery_icon(self, percentage: float) -> Image:
        """Create battery icon image."""
        img = Image.new('1', (128, 32), color=0)
        draw = ImageDraw.Draw(img)
        
        # Draw battery outline
        draw.rectangle([10, 8, 100, 24], outline=1, fill=0)  # Main body
        draw.rectangle([100, 12, 104, 20], fill=1)  # Positive terminal
        
        # Draw fill level
        fill_width = int((percentage / 100) * 86)
        if fill_width > 0:
            draw.rectangle([12, 10, 12 + fill_width, 22], fill=1)
        
        # Draw percentage text
        text = f"{int(percentage)}%"
        draw.text((110, 10), text, fill=1)
        
        return img

    def display_battery_icon(self, duration: float = 5.0):
        """Display battery icon with fill level on screen."""
        if not self.connected:
            return False
        
        try:
            voltage = self.get_battery_voltage()
            pct = self._voltage_to_percentage(voltage)
            img = self._draw_battery_icon(pct)
            self.cli.display_image(img)
            print(f"Battery: {voltage:.2f}V ({pct:.0f}%)")
            time.sleep(duration)
            self.cli.clear_screen()
            return True
        except Exception as e:
            print(f"Error displaying battery icon: {e}")
            return False

    def display_battery_voltage(self, duration: float = 5.0):
        """Display battery voltage as large text."""
        if not self.connected:
            return False
        
        try:
            voltage = self.get_battery_voltage()
            text = f"{voltage:.2f}V"
            
            img = Image.new('1', (128, 32), color=0)
            draw = ImageDraw.Draw(img)
            draw.text((20, 8), text, fill=1)
            
            self.cli.display_image(img)
            print(f"Voltage: {voltage:.2f}V")
            time.sleep(duration)
            self.cli.clear_screen()
            return True
        except Exception as e:
            print(f"Error displaying voltage: {e}")
            return False

    def display_battery_percentage(self, duration: float = 5.0):
        """Display battery percentage as large text."""
        if not self.connected:
            return False
        
        try:
            voltage = self.get_battery_voltage()
            pct = self._voltage_to_percentage(voltage)
            text = f"{pct:.0f}%"
            
            img = Image.new('1', (128, 32), color=0)
            draw = ImageDraw.Draw(img)
            draw.text((35, 8), text, fill=1)
            
            self.cli.display_image(img)
            print(f"Percentage: {pct:.0f}%")
            time.sleep(duration)
            self.cli.clear_screen()
            return True
        except Exception as e:
            print(f"Error displaying percentage: {e}")
            return False

    def display_battery_two_lines(self, duration: float = 5.0):
        """Display battery info on two lines."""
        if not self.connected:
            return False
        
        try:
            voltage = self.get_battery_voltage()
            pct = self._voltage_to_percentage(voltage)
            
            line1 = f"BAT: {voltage:.2f}V"
            line2 = f"{pct:.0f}% CHARGED"
            
            img = Image.new('1', (128, 32), color=0)
            draw = ImageDraw.Draw(img)
            draw.text((5, 2), line1, fill=1)
            draw.text((5, 17), line2, fill=1)
            
            self.cli.display_image(img)
            print(f"Line 1: {line1}")
            print(f"Line 2: {line2}")
            time.sleep(duration)
            self.cli.clear_screen()
            return True
        except Exception as e:
            print(f"Error displaying two lines: {e}")
            return False

    def get_battery_voltage(self) -> float:
        """Get Cozmo's current battery voltage."""
        if not self.is_connected():
            return 0.0
        return self.cli.battery_voltage

    def get_status(self) -> Dict[str, Any]:
        """Get current robot status."""
        if not self.is_connected():
            return {
                "connected": False,
                "reason": "Not connected or invalid robot state (serial=0 or battery<3V)"
            }

        return {
            "connected": self.connected,
            "serial_number": self.cli.serial_number,
            "battery_voltage": self.battery_voltage,
            "head_angle": self.head_angle,
            "animations_loaded": self.anims_loaded,
        }


class CommandParser:
    """Parser for command sequences with command-specific arguments."""
    
    # Define command signatures: (command_name, required_args, optional_args_with_defaults)
    COMMANDS = {
        'connect': {
            'desc': 'Connect to robot',
            'args': [],
            'opts': {}
        },
        'status': {
            'desc': 'Show robot status',
            'args': [],
            'opts': {}
        },
        'wait': {
            'desc': 'Wait for robot to stabilize',
            'args': [],
            'opts': {}
        },
        'say': {
            'desc': 'Text-to-speech',
            'args': ['text'],
            'opts': {'volume': 65535, 'voice': 'en-us', 'speed': 150, 'pitch': 50, 'amplitude': 100, 'async': False},
            'varargs': True
        },
        'volume': {
            'desc': 'Set volume',
            'args': ['level'],
            'opts': {}
        },
        'move': {
            'desc': 'Move forward/backward',
            'args': ['distance'],
            'opts': {'speed': 100, 'async': False}
        },
        'turn': {
            'desc': 'Turn by angle',
            'args': ['angle'],
            'opts': {'async': False}
        },
        'goto': {
            'desc': 'Go to position',
            'args': ['x', 'y'],
            'opts': {'angle': 0, 'async': False}
        },
        'head': {
            'desc': 'Set head angle (aliases: down/bottom, middle/neutral, up/top, or radians)',
            'args': [],
            'opts': {'angle': 'middle', 'async': False},
            'varargs': True
        },
        'lift': {
            'desc': 'Move lift',
            'args': ['speed'],
            'opts': {'duration': 1.0, 'async': False}
        },
        'lights': {
            'desc': 'Set LED color(s)',
            'args': [],
            'opts': {'color': 'blue', 'colors': None}
        },
        'ir': {
            'desc': 'IR head light',
            'args': [],
            'opts': {'enable': True}
        },
        'cliff': {
            'desc': 'Cliff detection settings',
            'args': [],
            'opts': {'enable': True, 'reaction': 'backup'}
        },
        'calibrate': {
            'desc': 'Calibrate motors',
            'args': [],
            'opts': {'head': True, 'lift': True}
        },
        'animate': {
            'desc': 'Play animation',
            'args': ['name'],
            'opts': {'async': False}
        },
        'anim-group': {
            'desc': 'Play animation group',
            'args': ['group'],
            'opts': {'async': False}
        },
        'list-anims': {
            'desc': 'List available animations',
            'args': [],
            'opts': {'search': None}
        },
        'list-groups': {
            'desc': 'List available animation groups',
            'args': [],
            'opts': {'search': None}
        },
        'list-sounds': {
            'desc': 'List available sounds',
            'args': [],
            'opts': {'search': None}
        },
        'play-sound': {
            'desc': 'Play sound by name or file',
            'args': [],
            'opts': {'name': None, 'file': None, 'async': False},
            'varargs': True
        },
        'camera': {
            'desc': 'Capture image',
            'args': [],
            'opts': {'output': 'camera_capture.jpg'}
        },
        'battery': {
            'desc': 'Show battery',
            'args': [],
            'opts': {'mode': 'icon', 'duration': 5.0}
        },
        'screen': {
            'desc': 'Display text',
            'args': ['text'],
            'opts': {'duration': 5.0, 'size': 12, 'x': 5, 'y': 10},
            'varargs': True  # Allow multiple words for text
        },
    }
    
    @classmethod
    def print_help(cls):
        """Print detailed help."""
        print("Cozmo Robot Controller")
        print("=" * 60)
        print()
        print("USAGE:")
        print("  python3 cozmo_controller.py <command1> [command2] ...")
        print("  python3 cozmo_controller.py --script <script.txt>")
        print()
        print("COMMANDS:")
        for cmd, info in cls.COMMANDS.items():
            args_str = " ".join([f"<{a}>" for a in info['args']])
            opts_str = " ".join([f"[{k}={v}]" for k, v in info['opts'].items() if v is not None])
            print(f"  {cmd:12s} {args_str:20s} {opts_str:30s} - {info['desc']}")
        print()
        print("EXAMPLES:")
        print('  python3 cozmo_controller.py "say Hello" "move 100" "turn 90"')
        print('  python3 cozmo_controller.py "lights color=red"')
        print('  python3 cozmo_controller.py "battery mode=voltage"')
        print('  python3 cozmo_controller.py "goto 200 100 angle=0"')
        print('  python3 cozmo_controller.py "ir enable=false"')
        print('  python3 cozmo_controller.py "calibrate head=true lift=true"')
        print('  python3 cozmo_controller.py "say Guten Tag voice=de speed=120"')
        print('  python3 cozmo_controller.py "animate anim_bored_01"')
        print('  python3 cozmo_controller.py "anim-group CodeLabChicken"')
        print('  python3 cozmo_controller.py "head up" "head middle" "head down"')
        print('  python3 cozmo_controller.py "list-sounds search=meow"')
        print('  python3 cozmo_controller.py "play-sound name=meow"')
        print('  python3 cozmo_controller.py "play-sound file=music.mp3"')
        print('  python3 cozmo_controller.py "play-sound file=\\"path with spaces/audio.mp3\\""')
        print('  python3 cozmo_controller.py --script dance_sequence.txt')
        print()
        print("SCRIPT FILE FORMAT:")
        print("  - One command per line")
        print("  - Lines starting with # are comments")
        print("  - Blank lines are ignored")
        print("  - Use 'include \"filename\"' to include another script")
        print("  - Include paths are relative to the current script's directory")
        print()
        print("SCRIPTING FEATURES:")
        print()
        print("  VARIABLES:")
        print("    set name value        # Set variable")
        print("    set count=5           # Alternative syntax")
        print("    say Hello $name       # Use variable with $var")
        print("    say ${name} there     # Use variable with ${var}")
        print()
        print("  FOR LOOPS:")
        print("    for i in 1..5         # Loop 1 to 5")
        print("      say Count $i")
        print("    endfor")
        print("    for i in 1..10 step 2 # Step by 2")
        print("    for item in a b c     # Loop over list")
        print()
        print("  WHILE LOOPS:")
        print("    while $count > 0")
        print("      say Count is $count")
        print("      set count $count-1")
        print("    endwhile")
        print()
        print("  CONDITIONS:")
        print("    if $count > 5")
        print("      say High count")
        print("    else")
        print("      say Low count")
        print("    endif")
        print("    # Operators: == != > < >= <=")
        print()
        print("  SUBROUTINES:")
        print("    def greet")
        print("      say Hello!")
        print("      lights color=blue")
        print("    enddef")
        print("    call greet           # Call subroutine")
        print("    call greet extra     # Pass argument as $1")
        print()
        print("EXAMPLE SCRIPT (dance.txt):")
        print("  # Dance sequence with loops")
        print("  set name Cozmo")
        print("  for i in 1..3")
        print("    say Round $i for $name")
        print("    anim-group DanceMambo async=true")
        print("    play-sound name=music async=true")
        print("  endfor")
        print()
        print("NOTES:")
        print("  - Commands execute in order (async commands run in parallel)")
        print("  - Boolean values: true/false, yes/no, on/off, 1/0")
        print("  - Distance in mm, angles in degrees, speed in mm/s")
        print("  - Head: down/bottom, middle/neutral, up/top, or radians (-0.44 to 0.78)")
        print("  - Voice: en-us (default), en-gb, de, fr, es, it, and many more")
        print("  - Text can have spaces (no quotes needed inside command)")
        print("  - Animations: anim_bored_01, anim_dancing_mambo_02, anim_greeting_01")
        print("  - Anim groups: CodeLabBored, CodeLabChicken, DanceMambo, FistBumpSuccess")
        print("  - Use quotes for paths with spaces: file=\"path with spaces/file.mp3\"")
        print()
    
    @staticmethod
    def _split_respecting_quotes(s):
        """Split string by spaces, but respect quoted substrings."""
        import shlex
        try:
            return shlex.split(s)
        except ValueError:
            # If shlex fails (e.g., unmatched quotes), fall back to simple split
            return s.split()
    
    @classmethod
    def parse_command(cls, cmd_str):
        """Parse a single command string into (command, args, opts)."""
        parts = cls._split_respecting_quotes(cmd_str)
        if not parts:
            return None
        
        cmd = parts[0]
        if cmd not in cls.COMMANDS:
            raise ValueError(f"Unknown command: {cmd}")
        
        cmd_info = cls.COMMANDS[cmd]
        args = []
        opts = {}
        
        i = 1
        arg_idx = 0
        
        while i < len(parts):
            part = parts[i]
            
            # Check if it's an option (key=value)
            if '=' in part:
                key, value = part.split('=', 1)
                if key in cmd_info['opts']:
                    # Parse value based on default type
                    default = cmd_info['opts'][key]
                    if isinstance(default, bool):
                        opts[key] = cls._parse_bool(value)
                    elif isinstance(default, int):
                        opts[key] = int(value)
                    elif isinstance(default, float):
                        opts[key] = float(value)
                    else:
                        opts[key] = value
                else:
                    raise ValueError(f"Unknown option '{key}' for command '{cmd}'")
            else:
                # It's a positional argument
                if arg_idx < len(cmd_info['args']):
                    args.append(part)
                    arg_idx += 1
                elif cmd_info.get('varargs', False):
                    # Command accepts variable arguments (e.g., 'say' with multi-word text)
                    args.append(part)
                    arg_idx += 1
                else:
                    raise ValueError(f"Too many arguments for command '{cmd}'")
            
            i += 1
        
        # Check required args
        if arg_idx < len(cmd_info['args']):
            raise ValueError(f"Command '{cmd}' requires {len(cmd_info['args'])} arguments: {cmd_info['args']}")
        
        # Fill in default options
        for key, default in cmd_info['opts'].items():
            if key not in opts:
                opts[key] = default
        
        return cmd, args, opts
    
    @staticmethod
    def _parse_bool(value):
        """Parse boolean value."""
        value = value.lower()
        if value in ('true', 'yes', 'on', '1'):
            return True
        elif value in ('false', 'no', 'off', '0'):
            return False
        raise ValueError(f"Cannot parse '{value}' as boolean")


def execute_command(controller, cmd, args, opts):
    """Execute a single parsed command."""
    print(f"\n>>> {cmd} {args} {opts}")
    
    if cmd == 'connect':
        return controller.connect()
    
    elif cmd == 'status':
        time.sleep(1)
        status = controller.get_status()
        print("-" * 40)
        for key, value in status.items():
            print(f"  {key}: {value}")
        print("-" * 40)
        return True
    
    elif cmd == 'wait':
        return controller.wait_for_robot()
    
    elif cmd == 'say':
        text = ' '.join(args)
        volume = int(opts.get('volume', 65535))
        voice = opts.get('voice', 'en-us')
        speed = int(opts.get('speed', 150))
        pitch = int(opts.get('pitch', 50))
        amplitude = int(opts.get('amplitude', 100))
        async_mode = opts.get('async', False)
        return controller.say_text(text, volume=volume, voice=voice, speed=speed, pitch=pitch, amplitude=amplitude, async_mode=async_mode)
    
    elif cmd == 'volume':
        level = int(args[0])
        return controller.set_volume(level)
    
    elif cmd == 'move':
        distance = float(args[0])
        speed = float(opts.get('speed', 100))
        async_mode = opts.get('async', False)
        return controller.move_forward(distance, speed, async_mode)
    
    elif cmd == 'turn':
        angle = float(args[0])
        angle_rad = angle * 3.14159 / 180.0
        async_mode = opts.get('async', False)
        return controller.turn_to_angle(angle_rad, async_mode=async_mode)
    
    elif cmd == 'goto':
        x = float(args[0])
        y = float(args[1])
        angle = float(opts.get('angle', 0))
        angle_rad = angle * 3.14159 / 180.0
        return controller.go_to_pose(x, y, angle_rad)
    
    elif cmd == 'head':
        if args:
            angle_str = args[0].lower()
        else:
            angle_str = opts.get('angle', 'middle').lower()
        
        head_aliases = {
            'down': -0.44,
            'bottom': -0.44,
            'lower': -0.20,
            'middle': 0.17,
            'neutral': 0.17,
            'center': 0.17,
            'upper': 0.45,
            'up': 0.78,
            'top': 0.78,
        }
        
        if angle_str in head_aliases:
            angle = head_aliases[angle_str]
            print(f"Head position: {angle_str} ({angle:.2f} rad)")
        else:
            angle = float(angle_str)
            print(f"Head angle: {angle:.2f} rad")
        
        async_mode = opts.get('async', False)
        return controller.set_head_angle(angle, async_mode)
    
    elif cmd == 'lift':
        speed = float(args[0])
        duration = float(opts.get('duration', 1.0))
        async_mode = opts.get('async', False)
        return controller.move_lift(speed, duration, async_mode)
    
    elif cmd == 'lights':
        if opts.get('colors'):
            colors = opts['colors'].split(',')
            return controller.set_backpack_lights_individual(colors)
        else:
            return controller.set_backpack_lights(opts.get('color', 'blue'))
    
    elif cmd == 'ir':
        enable = opts.get('enable', True)
        return controller.set_head_light(enable)
    
    elif cmd == 'cliff':
        enable = opts.get('enable', True)
        reaction = opts.get('reaction', 'backup')
        controller.set_cliff_reaction(reaction)
        return controller.enable_cliff_detection(enable)
    
    elif cmd == 'calibrate':
        head = opts.get('head', True)
        lift = opts.get('lift', True)
        return controller.calibrate_motors(head=head, lift=lift)
    
    elif cmd == 'animate':
        name = args[0]
        async_mode = opts.get('async', False)
        return controller.play_animation(name, async_mode=async_mode)
    
    elif cmd == 'anim-group':
        group = args[0]
        async_mode = opts.get('async', False)
        return controller.play_anim_group(group, async_mode=async_mode)
    
    elif cmd == 'list-anims':
        search = opts.get('search')
        return controller.list_animations(search)
    
    elif cmd == 'list-groups':
        search = opts.get('search')
        return controller.list_animation_groups(search)
    
    elif cmd == 'list-sounds':
        search = opts.get('search')
        return controller.list_sounds(search)
    
    elif cmd == 'play-sound':
        name = opts.get('name')
        file = opts.get('file')
        async_mode = opts.get('async', False)
        if name is None and file is None and args:
            # First arg could be name or file path
            arg = args[0]
            if os.path.exists(arg):
                file = arg
            else:
                name = arg
        return controller.play_sound(name=name, file=file, async_mode=async_mode)
    
    elif cmd == 'camera':
        output = opts.get('output', 'camera_capture.jpg')
        result = controller.capture_camera_image(output)
        if result:
            print(f"  Saved to: {result}")
        return bool(result)
    
    elif cmd == 'battery':
        mode = opts.get('mode', 'icon')
        duration = float(opts.get('duration', 5.0))
        
        controller.set_head_angle(0.17)
        time.sleep(0.5)
        
        if mode == 'icon':
            return controller.display_battery_icon(duration)
        elif mode == 'voltage':
            return controller.display_battery_voltage(duration)
        elif mode == 'percent':
            return controller.display_battery_percentage(duration)
        elif mode == 'text':
            return controller.display_battery_two_lines(duration)
        else:
            voltage = controller.get_battery_voltage()
            print(f"  Battery: {voltage:.2f}V")
            return True
    
    elif cmd == 'screen':
        text = ' '.join(args)
        duration = float(opts.get('duration', 5.0))
        size = int(opts.get('size', 12))
        x = int(opts.get('x', 5))
        y = int(opts.get('y', 10))
        return controller.display_text_on_screen(text, duration=duration, font_size=size, x=x, y=y)
    
    return False


class ScriptInterpreter:
    """Interpreter for advanced script features: variables, loops, conditions, subroutines."""
    
    def __init__(self):
        self.variables = {}
        self.subroutines = {}
        self.max_iterations = 1000  # Safety limit for loops
    
    def preprocess(self, lines: list, base_dir: Path = None) -> list:
        """Preprocess script lines, expanding control structures.
        
        Args:
            lines: List of raw script lines
            base_dir: Base directory for includes
        
        Returns:
            List of expanded command strings
        """
        # First pass: extract subroutines
        lines = self._extract_subroutines(lines)
        
        # Second pass: expand control structures
        return self._expand_block(lines, base_dir)
    
    def _extract_subroutines(self, lines: list) -> list:
        """Extract subroutine definitions and return remaining lines."""
        result = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            if line.lower().startswith('def '):
                # Extract subroutine name
                parts = line.split(None, 1)
                if len(parts) < 2:
                    print(f"Error: Invalid def syntax: {line}")
                    i += 1
                    continue
                
                sub_name = parts[1].strip()
                sub_lines = []
                i += 1
                depth = 1
                
                while i < len(lines) and depth > 0:
                    sub_line = lines[i].strip().lower()
                    if sub_line.startswith('def '):
                        depth += 1
                    elif sub_line == 'enddef':
                        depth -= 1
                        if depth == 0:
                            break
                    sub_lines.append(lines[i])
                    i += 1
                
                self.subroutines[sub_name] = sub_lines
                i += 1
            else:
                result.append(lines[i])
                i += 1
        
        return result
    
    def _expand_block(self, lines: list, base_dir: Path, depth: int = 0) -> list:
        """Expand a block of lines, handling control structures."""
        if depth > 50:
            print("Error: Maximum nesting depth exceeded")
            return []
        
        result = []
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                i += 1
                continue
            
            lower_line = line.lower()
            
            # Handle include
            if lower_line.startswith('include '):
                included = self._handle_include(line, base_dir)
                result.extend(included)
                i += 1
                continue
            
            # Handle set variable
            if lower_line.startswith('set '):
                self._handle_set(line)
                i += 1
                continue
            
            # Handle for loop
            if lower_line.startswith('for '):
                expanded, new_i = self._handle_for(lines, i, base_dir, depth)
                result.extend(expanded)
                i = new_i
                continue
            
            # Handle while loop
            if lower_line.startswith('while '):
                expanded, new_i = self._handle_while(lines, i, base_dir, depth)
                result.extend(expanded)
                i = new_i
                continue
            
            # Handle if condition
            if lower_line.startswith('if '):
                expanded, new_i = self._handle_if(lines, i, base_dir, depth)
                result.extend(expanded)
                i = new_i
                continue
            
            # Handle call subroutine
            if lower_line.startswith('call '):
                expanded = self._handle_call(line, base_dir, depth)
                result.extend(expanded)
                i += 1
                continue
            
            # Handle else/endif/endfor/endwhile (should not appear here)
            if lower_line in ('else', 'endif', 'endfor', 'endwhile', 'enddef'):
                print(f"Warning: Unexpected {line} at line {i+1}")
                i += 1
                continue
            
            # Regular command - expand variables
            expanded_line = self._expand_variables(line)
            result.append(expanded_line)
            i += 1
        
        return result
    
    def _handle_include(self, line: str, base_dir: Path) -> list:
        """Handle include directive."""
        import re
        match = re.match(r'^include\s+(.+)$', line, re.IGNORECASE)
        if not match:
            return []
        
        include_arg = match.group(1).strip()
        if (include_arg.startswith('"') and include_arg.endswith('"')) or \
           (include_arg.startswith("'") and include_arg.endswith("'")):
            include_arg = include_arg[1:-1]
        
        include_path = Path(include_arg)
        if not include_path.is_absolute() and base_dir:
            include_path = base_dir / include_arg
        
        if not include_path.exists():
            print(f"Error: Include file not found: {include_path}")
            return []
        
        return load_script_file(include_path, include_path.parent)
    
    def _handle_set(self, line: str):
        """Handle set variable: set varname value or set varname="value"."""
        import re
        
        # Match: set varname value or set varname="value with spaces"
        match = re.match(r'^set\s+(\w+)\s*=?\s*(.*)$', line, re.IGNORECASE)
        if not match:
            print(f"Error: Invalid set syntax: {line}")
            return
        
        var_name = match.group(1)
        value = match.group(2).strip()
        
        # Remove quotes if present
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        
        # Try to evaluate as expression
        value = self._evaluate_expression(value)
        
        self.variables[var_name] = value
        print(f"  [set {var_name} = {value}]")
    
    def _evaluate_expression(self, expr: str):
        """Evaluate an expression (math, variables, etc.)."""
        import re
        
        # First expand any variables
        expr = self._expand_variables(expr)
        
        # Try simple arithmetic: number op number
        try:
            # Only allow safe characters for eval
            if re.match(r'^[\d\s\+\-\*\/\%\(\)\.]+$', expr):
                result = eval(expr)
                if isinstance(result, float) and result == int(result):
                    return int(result)
                return result
        except:
            pass
        
        return expr
    
    def _expand_variables(self, line: str) -> str:
        """Expand $var and ${var} references in a line."""
        import re
        
        def replace_var(match):
            var_name = match.group(1) or match.group(2)
            return str(self.variables.get(var_name, ''))
        
        # Match $varname or ${varname}
        line = re.sub(r'\$\{(\w+)\}', replace_var, line)
        line = re.sub(r'\$(\w+)', replace_var, line)
        
        return line
    
    def _handle_for(self, lines: list, start: int, base_dir: Path, depth: int) -> tuple:
        """Handle for loop: for var in 1..5 or for var in a b c."""
        import re
        
        line = lines[start].strip()
        match = re.match(r'^for\s+(\w+)\s+in\s+(.+)$', line, re.IGNORECASE)
        
        if not match:
            print(f"Error: Invalid for syntax: {line}")
            return [], start + 1
        
        var_name = match.group(1)
        values_str = match.group(2).strip()
        
        # Parse values
        values = []
        
        # Check for range: 1..5 or 1..10 step 2
        range_match = re.match(r'^(\d+)\.\.(\d+)(?:\s+step\s+(\d+))?$', values_str)
        if range_match:
            start_val = int(range_match.group(1))
            end_val = int(range_match.group(2))
            step = int(range_match.group(3)) if range_match.group(3) else 1
            values = list(range(start_val, end_val + 1, step))
        else:
            # List of values (split by space, respect quotes)
            values = self._split_values(values_str)
        
        # Find matching endfor
        block_lines, end_idx = self._find_block_end(lines, start + 1, 'endfor')
        
        # Expand block for each value
        result = []
        iteration = 0
        
        for val in values:
            if iteration >= self.max_iterations:
                print(f"Warning: For loop exceeded max iterations ({self.max_iterations})")
                break
            
            old_val = self.variables.get(var_name)
            self.variables[var_name] = val
            
            expanded = self._expand_block(block_lines, base_dir, depth + 1)
            result.extend(expanded)
            
            if old_val is not None:
                self.variables[var_name] = old_val
            else:
                del self.variables[var_name]
            
            iteration += 1
        
        return result, end_idx + 1
    
    def _handle_while(self, lines: list, start: int, base_dir: Path, depth: int) -> tuple:
        """Handle while loop: while condition."""
        import re
        
        line = lines[start].strip()
        match = re.match(r'^while\s+(.+)$', line, re.IGNORECASE)
        
        if not match:
            print(f"Error: Invalid while syntax: {line}")
            return [], start + 1
        
        condition = match.group(1).strip()
        
        # Find matching endwhile
        block_lines, end_idx = self._find_block_end(lines, start + 1, 'endwhile')
        
        # Expand block while condition is true
        result = []
        iteration = 0
        
        while self._evaluate_condition(condition):
            if iteration >= self.max_iterations:
                print(f"Warning: While loop exceeded max iterations ({self.max_iterations})")
                break
            
            expanded = self._expand_block(block_lines, base_dir, depth + 1)
            result.extend(expanded)
            iteration += 1
        
        return result, end_idx + 1
    
    def _handle_if(self, lines: list, start: int, base_dir: Path, depth: int) -> tuple:
        """Handle if/else/endif."""
        import re
        
        line = lines[start].strip()
        match = re.match(r'^if\s+(.+)$', line, re.IGNORECASE)
        
        if not match:
            print(f"Error: Invalid if syntax: {line}")
            return [], start + 1
        
        condition = match.group(1).strip()
        
        # Find else and endif
        if_lines = []
        else_lines = []
        end_idx = None
        found_else = False
        nested = 0
        i = start + 1
        
        while i < len(lines):
            lower = lines[i].strip().lower()
            
            if lower.startswith('if '):
                nested += 1
            elif lower == 'endif':
                if nested == 0:
                    end_idx = i
                    break
                nested -= 1
            elif lower == 'else' and nested == 0:
                found_else = True
                i += 1
                continue
            
            if found_else:
                else_lines.append(lines[i])
            else:
                if_lines.append(lines[i])
            
            i += 1
        
        if end_idx is None:
            print(f"Error: No matching endif for if at line {start + 1}")
            return [], start + 1
        
        # Evaluate condition and expand appropriate block
        if self._evaluate_condition(condition):
            result = self._expand_block(if_lines, base_dir, depth + 1)
        else:
            result = self._expand_block(else_lines, base_dir, depth + 1)
        
        return result, end_idx + 1
    
    def _handle_call(self, line: str, base_dir: Path, depth: int) -> list:
        """Handle call subroutine."""
        import re
        
        match = re.match(r'^call\s+(\w+)(?:\s+(.*))?$', line, re.IGNORECASE)
        if not match:
            print(f"Error: Invalid call syntax: {line}")
            return []
        
        sub_name = match.group(1)
        args_str = match.group(2) or ''
        
        if sub_name not in self.subroutines:
            print(f"Error: Subroutine not found: {sub_name}")
            return []
        
        # Parse arguments and set as $1, $2, etc.
        args = self._split_values(args_str)
        old_args = {}
        
        for i, arg in enumerate(args, 1):
            old_args[str(i)] = self.variables.get(str(i))
            self.variables[str(i)] = arg
        
        # Expand subroutine
        result = self._expand_block(self.subroutines[sub_name], base_dir, depth + 1)
        
        # Restore old args
        for key, val in old_args.items():
            if val is not None:
                self.variables[key] = val
            elif key in self.variables:
                del self.variables[key]
        
        return result
    
    def _find_block_end(self, lines: list, start: int, end_keyword: str) -> tuple:
        """Find the end of a block (endfor, endwhile, etc.)."""
        block_lines = []
        nested = 0
        i = start
        
        while i < len(lines):
            lower = lines[i].strip().lower()
            
            # Check for nested blocks
            if lower.startswith('for ') or lower.startswith('while ') or lower.startswith('if '):
                nested += 1
            elif lower in ('endfor', 'endwhile', 'endif'):
                if nested == 0 and lower == end_keyword:
                    return block_lines, i
                nested -= 1
            
            block_lines.append(lines[i])
            i += 1
        
        print(f"Warning: No matching {end_keyword} found")
        return block_lines, i
    
    def _evaluate_condition(self, condition: str) -> bool:
        """Evaluate a condition expression."""
        import re
        
        # Expand variables first
        condition = self._expand_variables(condition)
        
        # Handle comparison operators
        operators = ['==', '!=', '>=', '<=', '>', '<']
        
        for op in operators:
            if op in condition:
                parts = condition.split(op, 1)
                if len(parts) == 2:
                    left = self._evaluate_expression(parts[0].strip())
                    right = self._evaluate_expression(parts[1].strip())
                    
                    # Convert to comparable types
                    try:
                        left = float(left) if '.' in str(left) or isinstance(left, (int, float)) else str(left)
                        right = float(right) if '.' in str(right) or isinstance(right, (int, float)) else str(right)
                    except:
                        left = str(left)
                        right = str(right)
                    
                    if op == '==':
                        return left == right
                    elif op == '!=':
                        return left != right
                    elif op == '>=':
                        return left >= right
                    elif op == '<=':
                        return left <= right
                    elif op == '>':
                        return left > right
                    elif op == '<':
                        return left < right
        
        # Treat non-empty string as true
        return bool(condition and condition.lower() not in ('false', '0', 'no', 'off'))
    
    def _split_values(self, s: str) -> list:
        """Split a string into values, respecting quotes."""
        import shlex
        try:
            return shlex.split(s)
        except:
            return s.split()


def load_script_file(filepath: Path, base_dir: Path = None, visited: set = None, interpreter: ScriptInterpreter = None) -> list:
    """Load commands from a script file, handling nested includes and scripting features.
    
    Args:
        filepath: Path to the script file
        base_dir: Base directory for relative includes (defaults to filepath's parent)
        visited: Set of already visited files to prevent infinite loops
        interpreter: ScriptInterpreter instance for preprocessing
    
    Returns:
        List of command strings
    """
    if visited is None:
        visited = set()
    
    filepath = Path(filepath).resolve()
    
    if filepath in visited:
        print(f"Warning: Skipping already included file: {filepath}")
        return []
    
    visited.add(filepath)
    
    if base_dir is None:
        base_dir = filepath.parent
    
    lines = []
    
    try:
        with open(filepath, 'r') as f:
            lines = [line.rstrip('\n\r') for line in f]
    
    except Exception as e:
        print(f"Error reading file {filepath}: {e}")
        return []
    
    # Use interpreter for preprocessing if available
    if interpreter:
        return interpreter.preprocess(lines, base_dir)
    
    # Fallback: basic parsing without interpreter
    commands = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            commands.append(line)
    
    return commands


def main():
    """CLI interface with multi-command support."""
    import sys
    
    args = sys.argv[1:]
    
    if not args or args[0] in ('-h', '--help', 'help'):
        CommandParser.print_help()
        return
    
    # Check for file input
    commands_raw = []
    interpreter = None
    
    if args[0] in ('-s', '--script'):
        if len(args) < 2:
            print("Error: --script requires a filename")
            return 1
        filepath = Path(args[1])
        if not filepath.exists():
            print(f"Error: Script not found: {filepath}")
            return 1
        interpreter = ScriptInterpreter()
        commands_raw = load_script_file(filepath, interpreter=interpreter)
        if not commands_raw:
            return 1
    else:
        commands_raw = args
    
    # Parse all commands first to catch errors early
    commands = []
    for cmd_str in commands_raw:
        try:
            parsed = CommandParser.parse_command(cmd_str)
            commands.append(parsed)
        except ValueError as e:
            print(f"Error parsing '{cmd_str}': {e}")
            return 1
    
    # Check if all commands are offline commands (don't need robot connection)
    offline_commands = {'list-anims', 'list-groups', 'list-sounds', 'help'}
    needs_connection = any(cmd[0] not in offline_commands for cmd in commands)
    
    if not needs_connection:
        # Don't connect to robot for offline commands
        controller = CozmoController(auto_connect=False)
        
        # Execute commands
        for cmd, args, opts in commands:
            execute_command(controller, cmd, args, opts)
        return 0
    
    # Connect to robot for commands that need it
    print("Connecting to Cozmo...")
    controller = CozmoController(auto_connect=True)
    
    if not controller.connected:
        print("Failed to connect!")
        return 1
    
    print("Connected! Executing commands...")
    print("=" * 60)
    
    # Execute commands in sequence
    try:
        for cmd, args, opts in commands:
            success = execute_command(controller, cmd, args, opts)
            if not success:
                print(f"  Command failed: {cmd}")
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("=" * 60)
        print("Disconnecting...")
        controller.disconnect()
    
    return 0


if __name__ == "__main__":
    main()
