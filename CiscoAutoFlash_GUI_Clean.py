#!/usr/bin/env python3
# CiscoAutoFlash_GUI_Enhanced.py (IDLE AI Edition)
#
# Purpose: Enhanced safe, transparent, stepwise, logged automation for resetting and flashing
# Cisco Catalyst 2960-X switches via a USB-console (USB-to-RJ45) connection and a USB flash drive.
#
# Enhanced Features (based on План.txt):
# - Mutex lock to prevent double execution
# - Automatic COM port detection with improved heuristics
# - Step-by-step workflow with explicit confirmations for destructive steps
# - Visual GUI (tkinter) with colored log area showing progress and phases
# - USB flash drive detection and monitoring (USBFLASH-5-CHANGE events)
# - Free space checking before installation
# - Initial configuration dialog handling
# - Final verification after installation (show version, show boot, dir flash:)
# - Install report generation (install_report_<timestamp>.txt)
# - Enhanced error handling and progress tracking
# - Digital signature verification monitoring
# - Ability to stop process safely (graceful stop)
# - Persisted log files per run (in user's Documents/CiscoAutoFlash_logs)
#
# IDLE AI Features:
# - Self-healing imports (auto-install missing dependencies)
# - Health monitoring (JSON metrics in logs/health_metrics.json)
# - Performance tracking (CPU/Memory/Time for each Stage)
# - Graceful shutdown (Ctrl+C handler with state preservation)
# - Self-testing at startup (validation of imports, permissions, disk space)
#
# Requirements: Python 3.8+, pyserial, tkinter (builtin on Windows)
# Dependencies are auto-installed if missing
#
# IMPORTANT SAFETY NOTES:
# - This script will interact with a real switch and *can* erase configs and reload the device.
#   Make sure you target the correct physical device before confirming destructive actions.
# - Always keep a working backup of configs/software and physical access to the device.
#
# Author: Enhanced version based on requirements from План.txt + IDLE AI patterns
#

import argparse
import logging
import os
import sys
import time
import datetime
import threading
import traceback
import re
import json
import subprocess
import atexit
import signal
import functools
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

# ========== IDLE AI: SELF-HEALING IMPORTS ==========
def auto_install(pkg: str, version: str | None = None):
    """Auto-install missing package"""
    pkg_spec = f"{pkg}=={version}" if version else pkg
    print(f"[AUTO-HEAL] Installing {pkg_spec}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", pkg_spec],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[AUTO-HEAL] ✅ {pkg_spec} installed successfully")
    except Exception as e:
        print(f"[AUTO-HEAL] ⚠️ Failed to install {pkg_spec}: {e}")

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext, simpledialog
except ImportError:
    print("[AUTO-HEAL] tkinter not found, attempting installation...")
    auto_install("tk")
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext, simpledialog

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[AUTO-HEAL] pyserial not found, installing...")
    auto_install("pyserial", "3.5")
    import serial
    import serial.tools.list_ports

try:
    import psutil
except ImportError:
    print("[AUTO-HEAL] psutil not found, installing for performance monitoring...")
    auto_install("psutil")
    import psutil

# ========== IDLE AI: HEALTH MONITORING ==========
class HealthMonitor:
    """Monitors application health and tracks metrics"""
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.metrics_file = log_path / "health_metrics.json"
        self.metrics = {
            "startup_time": datetime.datetime.now().isoformat(),
            "operations": 0,
            "errors": 0,
            "stages_completed": {},
            "last_health_check": None,
            "performance": {}
        }
        self._load_metrics()
    
    def _load_metrics(self):
        """Load existing metrics if available"""
        try:
            if self.metrics_file.exists():
                with open(self.metrics_file, 'r') as f:
                    old_metrics = json.load(f)
                    # Preserve startup time and reset session data
                    self.metrics["previous_session"] = old_metrics
                    self.metrics["startup_time"] = datetime.datetime.now().isoformat()
        except Exception:
            pass
    
    def record_operation(self, op_name: str, success: bool, duration: float = 0, **kwargs):
        """Record operation result"""
        self.metrics["operations"] += 1
        if not success:
            self.metrics["errors"] += 1
        
        self.metrics[f"last_{op_name}"] = {
            "timestamp": datetime.datetime.now().isoformat(),
            "success": success,
            "duration": duration
        }
        
        if kwargs:
            self.metrics[f"last_{op_name}"].update(kwargs)
        
        self._save_metrics()
    
    def record_stage_completion(self, stage_name: str, success: bool, duration: float = 0):
        """Record Stage completion"""
        self.metrics["stages_completed"][stage_name] = {
            "success": success,
            "duration": duration,
            "timestamp": datetime.datetime.now().isoformat()
        }
        self._save_metrics()
    
    def health_check(self) -> dict:
        """Perform health check and return status"""
        try:
            startup = datetime.datetime.fromisoformat(self.metrics["startup_time"])
            uptime = (datetime.datetime.now() - startup).seconds
        except:
            uptime = 0
        
        error_rate = self.metrics["errors"] / max(self.metrics["operations"], 1)
        
        health = {
            "status": "healthy" if error_rate < 0.1 else "degraded",
            "uptime_seconds": uptime,
            "error_rate": error_rate,
            "metrics": self.metrics
        }
        
        self.metrics["last_health_check"] = datetime.datetime.now().isoformat()
        self._save_metrics()
        return health
    
    def _save_metrics(self):
        """Save metrics to JSON file"""
        try:
            with open(self.metrics_file, 'w') as f:
                json.dump(self.metrics, f, indent=2)
        except Exception:
            pass  # Fail silently

# ========== IDLE AI: PERFORMANCE TRACKING ==========
def monitor_performance(stage_name: str):
    """Decorator to monitor performance of Stage functions"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            if not hasattr(self, 'health_monitor'):
                return func(self, *args, **kwargs)
            
            try:
                process = psutil.Process()
                mem_before = process.memory_info().rss / 1024 / 1024  # MB
                start_time = time.time()
                
                result = func(self, *args, **kwargs)
                
                duration = time.time() - start_time
                mem_after = process.memory_info().rss / 1024 / 1024
                mem_delta = mem_after - mem_before
                
                self.log(f"[PERF] {stage_name}: {duration:.1f}s, MEM: {mem_after:.1f}MB (Δ{mem_delta:+.1f}MB)", "debug")
                
                self.health_monitor.record_stage_completion(stage_name, True, duration)
                self.health_monitor.metrics["performance"][stage_name] = {
                    "duration_seconds": round(duration, 2),
                    "memory_mb": round(mem_after, 1),
                    "memory_delta_mb": round(mem_delta, 1)
                }
                
                return result
            except Exception as e:
                start_time = start_time if 'start_time' in locals() else time.time()
                duration = time.time() - start_time
                self.health_monitor.record_stage_completion(stage_name, False, duration)
                raise
        
        return wrapper
    return decorator

# ========== IDLE AI: GRACEFUL SHUTDOWN ==========
class GracefulShutdown:
    """Handles graceful shutdown on SIGINT/SIGTERM"""
    def __init__(self):
        self.cleanup_handlers = []
        self.shutdown_requested = False
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        atexit.register(self._cleanup)
    
    def register_cleanup(self, func, description: str = ""):
        """Register cleanup function"""
        self.cleanup_handlers.append((func, description))
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        if self.shutdown_requested:
            print("\n[SHUTDOWN] Force quit...")
            sys.exit(1)
        
        print(f"\n[SHUTDOWN] Received signal {signum}, shutting down gracefully...")
        print("[SHUTDOWN] Press Ctrl+C again to force quit")
        self.shutdown_requested = True
        self._cleanup()
        sys.exit(0)
    
    def _cleanup(self):
        """Execute all cleanup handlers"""
        for handler, desc in self.cleanup_handlers:
            try:
                if desc:
                    print(f"[CLEANUP] {desc}")
                handler()
            except Exception as e:
                print(f"[CLEANUP] Failed: {e}")

# Global shutdown manager
shutdown_manager = GracefulShutdown()

# ---------------------- Configuration ----------------------
APP_NAME = "CiscoAutoFlash_GUI_Clean"
APP_VERSION = "3.0 Commercial IDLE AI Edition"
DEFAULT_FIRMWARE_FILENAME = "c2960x-universalk9-tar.152-7.E13.tar"
DEFAULT_DRY_RUN = False  # ✅ PRODUCTION MODE: Real device operations enabled


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cisco Catalyst 2960-X automated flashing tool")
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=DEFAULT_DRY_RUN,
        help="Simulate all serial commands without sending them to the device"
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Disable dry run and allow real commands to be sent"
    )
    parser.add_argument(
        "--log-level",
        dest="log_level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set console log level (file logging remains verbose)"
    )
    return parser


ARGS = _build_arg_parser().parse_args()
DRY_RUN = ARGS.dry_run

def _resolve_base_dir():
    """Определяет директорию рядом с исполняемым файлом/скриптом."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = _resolve_base_dir()
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Mutex lock file to prevent double execution
LOCK_FILE = LOG_DIR / "ciscoautoflash.lock"
LOG_FILE_NAME = f"{APP_NAME}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
LOG_FILE_PATH = LOG_DIR / f"{LOG_FILE_NAME}.log"
REPORT_FILE_PATH = LOG_DIR / f"install_report_{LOG_FILE_NAME.split('_')[-1]}.txt"


def _configure_logging() -> logging.Logger:
    """Configure console logging according to CLI arguments."""
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        console_handler = logging.StreamHandler()
        level = getattr(logging, ARGS.log_level.upper(), logging.INFO)
        console_handler.setLevel(level)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        )
        logger.addHandler(console_handler)

    return logger


LOGGER = _configure_logging()

# Дополнительные команды аудита после прошивки
AUDIT_COMMANDS = [
    ("show inventory", "SHOW INVENTORY", 2.0),
    ("show license", "SHOW LICENSE", 2.0),
    ("show system mtu", "SHOW SYSTEM MTU", 1.5),
    ("show switch", "SHOW SWITCH", 1.5),
    ("show switch detail", "SHOW SWITCH DETAIL", 2.5),
    ("show power inline", "SHOW POWER INLINE", 2.0),
    ("show interfaces status", "SHOW INTERFACES STATUS", 3.0),
    ("show ip interface brief", "SHOW IP INTERFACE BRIEF", 2.5),
    ("show interfaces trunk", "SHOW INTERFACES TRUNK", 2.0),
    ("show vlan brief", "SHOW VLAN BRIEF", 2.0),
    ("show spanning-tree summary", "SHOW SPANNING-TREE SUMMARY", 2.5),
    ("show ip default-gateway", "SHOW IP DEFAULT-GATEWAY", 1.5),
    ("show mac address-table", "SHOW MAC ADDRESS-TABLE", 3.0),
    ("show mac address-table secure", "SHOW MAC ADDRESS-TABLE SECURE", 2.5),
    ("show arp", "SHOW ARP", 2.0),
    ("show ip route", "SHOW IP ROUTE", 2.5),
    ("show port-security", "SHOW PORT-SECURITY", 2.0),
    ("show ip dhcp binding", "SHOW IP DHCP BINDING", 2.0),
    ("show ip dhcp snooping", "SHOW IP DHCP SNOOPING", 2.5),
    ("show ntp status", "SHOW NTP STATUS", 2.0),
    ("show running-config", "SHOW RUNNING-CONFIG", 5.0),
    ("show startup-config", "SHOW STARTUP-CONFIG", 4.0),
    ("show clock", "SHOW CLOCK", 1.0),
    ("show logging", "SHOW LOGGING", 4.0),
    ("show cdp neighbors", "SHOW CDP NEIGHBORS", 2.0),
    ("show cdp neighbors detail", "SHOW CDP NEIGHBORS DETAIL", 3.0),
    ("show lldp neighbors", "SHOW LLDP NEIGHBORS", 2.0),
    ("show lldp neighbors detail", "SHOW LLDP NEIGHBORS DETAIL", 3.0),
    ("show etherchannel summary", "SHOW ETHERCHANNEL SUMMARY", 2.0),
]

# Serial read timeout (seconds) - Best practice from Cisco automation experts
SERIAL_TIMEOUT = 1.0  # Increased from 0.5 to 1.0 for more reliable reads

# Timeouts & waits (seconds)
SHORT_WAIT = 1.0
MEDIUM_WAIT = 3.0

# Command response timeouts (based on Cisco IOS behavior)
PROMPT_TIMEOUT = 15  # Time to wait for Switch# or Switch>
ENABLE_TIMEOUT = 10  # Time to wait for enable command
RELOAD_TIMEOUT = 3   # Time per attempt to detect reload confirmation

# Boot-detection markers
PROMPT_PRIV = "Switch#"
PROMPT_USER = "Switch>"
PROMPT_REDUCED = "switch:"

# ---------------------- Startup Cleanup (v3.0) ----------------------
def cleanup_on_startup():
    """
    Очистка при запуске программы (v3.0 Commercial)
    - Удаляет старые lock-файлы
    - Очищает старые логи (оставляет последние 10)
    - Сбрасывает COM-порты
    - Очищает временные файлы
    """
    print("[CLEANUP] Очистка при запуске...")
    
    # 1. Удаление старых lock-файлов
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
            print("  [OK] Lock-файл удалён")
    except Exception as e:
        print(f"  ⚠ Не удалось удалить lock: {e}")
    
    # 2. Очистка старых логов (оставить последние 10)
    try:
        log_files = sorted(LOG_DIR.glob("CiscoAutoFlash*.log"), key=lambda x: x.stat().st_mtime, reverse=True)
        if len(log_files) > 10:
            for old_log in log_files[10:]:
                try:
                    old_log.unlink()
                    print(f"  [OK] Удалён старый лог: {old_log.name}")
                except:
                    pass
            print(f"  [OK] Очищено {len(log_files) - 10} старых логов")
    except Exception as e:
        print(f"  ⚠ Ошибка очистки логов: {e}")
    
    # 3. Сброс COM-портов (закрыть все открытые)
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        for port in ports:
            try:
                # Попытка открыть и сразу закрыть для сброса
                test_ser = serial.Serial(port.device, 9600, timeout=0.1)
                test_ser.close()
            except:
                pass
        print("  [OK] COM-порты сброшены")
    except Exception as e:
        print(f"  ⚠ Ошибка сброса COM: {e}")
    
    # 4. Очистка временных файлов
    try:
        temp_patterns = ["temp_*.txt", "*.tmp"]
        for pattern in temp_patterns:
            for temp_file in LOG_DIR.glob(pattern):
                try:
                    temp_file.unlink()
                    print(f"  [OK] Удалён временный файл: {temp_file.name}")
                except:
                    pass
    except Exception as e:
        print(f"  ⚠ Ошибка очистки temp: {e}")
    
    print("[CLEANUP] Очистка завершена!")
    print()

# ---------------------- Mutex Lock ----------------------
class SingleInstanceLock:
    """Prevent multiple instances of the script from running"""
    def __init__(self, lockfile):
        self.lockfile = lockfile
        self.locked = False
        
    def acquire(self):
        """Try to acquire lock. Returns True if successful, False if already locked"""
        if self.lockfile.exists():
            try:
                # Check if the process that created lock is still running
                with open(self.lockfile, 'r') as f:
                    pid = int(f.read().strip())
                # Try to check if process exists (Windows compatible)
                try:
                    import psutil
                    if psutil.pid_exists(pid):
                        return False
                except ImportError:
                    # If psutil not available, assume lock is valid
                    return False
            except (ValueError, FileNotFoundError):
                # Invalid lock file, remove it
                try:
                    self.lockfile.unlink()
                except:
                    pass
        
        # Create lock file with current PID
        try:
            with open(self.lockfile, 'w') as f:
                f.write(str(os.getpid()))
            self.locked = True
            return True
        except Exception:
            return False
    
    def release(self):
        """Release the lock"""
        if self.locked:
            try:
                self.lockfile.unlink()
            except:
                pass
            self.locked = False

# ---------------------- Utilities ----------------------
def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def mask_sensitive(text: str) -> str:
    """Маскирует чувствительные данные (пароли, секреты) перед логированием."""
    sensitive_pattern = re.compile(r"(password|enable secret|secret|key)\s+\S+", re.IGNORECASE)
    return sensitive_pattern.sub(lambda match: f"{match.group(1)} ******", text)


def safe_write_log_file(text, log_path):
    """Запись строки в лог-файл в кодировке CP1251 (совместимость с Windows Notepad)."""
    try:
        masked = mask_sensitive(text)
        normalized = masked.encode("cp1251", errors="replace").decode("cp1251", errors="replace")
        with open(log_path, "a", encoding="cp1251", errors="replace") as f:
            f.write(normalized + "\n")
    except Exception as e:
        print(f"[CRITICAL] Cannot write log: {e}")

def parse_free_space(output):
    """Parse free space from 'show flash:' or 'dir' output
    Returns: (free_bytes, total_bytes) or (None, None) if parsing fails
    """
    # Look for patterns like "123456789 bytes total (98765432 bytes free)"
    pattern = r'(\d+)\s+bytes\s+total\s+\((\d+)\s+bytes\s+free\)'
    match = re.search(pattern, output)
    if match:
        total = int(match.group(1))
        free = int(match.group(2))
        return (free, total)
    return (None, None)

def parse_version_info(output):
    """Parse version from 'show version' output
    Returns dict with version info or empty dict
    """
    info = {}
    # Software version pattern
    version_match = re.search(r'Version\s+(\S+)', output)
    if version_match:
        info['version'] = version_match.group(1)
    
    # System image pattern
    image_match = re.search(r'System\s+image\s+file\s+is\s+"([^"]+)"', output)
    if image_match:
        info['image'] = image_match.group(1)
    
    # Model pattern
    model_match = re.search(r'Model\s+[Nn]umber\s*:\s*(\S+)', output)
    if model_match:
        info['model'] = model_match.group(1)
    
    return info

# ---------------------- Serial helper ----------------------
class SerialController:
    RETRIES = 3
    BACKOFF = 2.0

    def __init__(self, port: str, baud: int = 9600, timeout: float = SERIAL_TIMEOUT, dry_run: bool = DRY_RUN):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.dry_run = dry_run
        self.ser: Optional[serial.Serial] = None
        self._stop = False

    def open(self) -> None:
        if self.dry_run:
            LOGGER.debug("[DRY-RUN] Skipping serial open for %s", self.port)
            return
        if self.ser and self.ser.is_open:
            return
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            time.sleep(0.5)
        except serial.SerialException as exc:
            raise RuntimeError(f"Serial open failed: {exc}") from exc

    def close(self) -> None:
        if self.dry_run:
            return
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except serial.SerialException:
                pass
        self.ser = None

    def write(self, text: str) -> None:
        if not text.endswith("\r"):
            text += "\r"
        if self.dry_run:
            LOGGER.info("[DRY-RUN] Would write: %s", mask_sensitive(text.strip()))
            return

        for attempt in range(1, self.RETRIES + 1):
            try:
                self.open()
                if not self.ser:
                    raise RuntimeError("Serial port not available")
                self.ser.write(text.encode("utf-8", errors="ignore"))
                return
            except (serial.SerialException, RuntimeError) as exc:
                LOGGER.warning("Serial write failed (attempt %s/%s): %s", attempt, self.RETRIES, exc)
                if attempt == self.RETRIES:
                    raise
                time.sleep(self.BACKOFF * attempt)

    def read_available(self) -> str:
        if self.dry_run:
            return "[DRY-RUN] simulated output"
        if not self.ser or not self.ser.is_open:
            return ""
        try:
            waiting = self.ser.in_waiting
            if waiting > 0:
                data = self.ser.read(waiting).decode("utf-8", errors="ignore")
                return mask_sensitive(data)
        except serial.SerialException as exc:
            LOGGER.debug("Serial read failed: %s", exc)
        return ""

    def expect(self, substrings: List[str], timeout: float = 30) -> Tuple[Optional[str], str]:
        if self.dry_run:
            return substrings[0] if substrings else None, "[DRY-RUN] expected"

        end = time.time() + timeout
        buffer = ""
        while time.time() < end and not self._stop:
            buffer += self.read_available()
            for s in substrings:
                if s and s in buffer:
                    return s, buffer
            time.sleep(0.2)
        return None, buffer

    def flush_input(self) -> None:
        if self.dry_run:
            return
        if self.ser and self.ser.is_open:
            try:
                self.ser.reset_input_buffer()
            except serial.SerialException:
                pass

    def stop(self) -> None:
        self._stop = True

# ---------------------- COM detection ----------------------
def detect_com_ports():
    ports = serial.tools.list_ports.comports()
    results = []
    for p in ports:
        results.append((p.device, p.description))
    return results

def auto_detect_cisco_port():
    """Enhanced COM port detection with better heuristics"""
    ports = serial.tools.list_ports.comports()
    candidates = []
    
    for p in ports:
        desc = (p.description or "").lower()
        manuf = (p.manufacturer or "").lower() if getattr(p, "manufacturer", None) else ""
        
        # Score each port based on likelihood
        score = 0
        if any(k in desc for k in ("usb", "serial", "ftdi", "prolific", "cp210", "pl2303", "ch340")):
            score += 2
        if any(k in manuf for k in ("ftdi", "prolific", "silicon", "silicon labs", "qinheng")):
            score += 3
        if "uart" in desc or "com" in desc:
            score += 1
            
        if score > 0:
            candidates.append((p.device, score, desc))
    
    # Sort by score (highest first)
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    if candidates:
        return candidates[0][0]  # Return highest scoring port
    
    # If no scored candidates but exactly one port, return it
    if len(ports) == 1:
        return ports[0].device
    
    return None

def check_device_availability(port, timeout=12):
    """Check if a device responds on the given COM port.
    Returns: (is_available, status_message, prompt_type)

    Улучшено для более устойчивого обнаружения Cisco устройств.
    """
    ser = None
    try:
        ser = serial.Serial(port, 9600, timeout=0.5, write_timeout=0.5)
        time.sleep(0.3)

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass

        # Пробуем «разбудить» устройство
        try:
            if hasattr(ser, "dtr"):
                ser.dtr = True
            if hasattr(ser, "rts"):
                ser.rts = True
        except Exception:
            pass

        wake_sequence = [b"\r\n", b"\x03", b"\r\n", b"\r\n"]
        for payload in wake_sequence:
            try:
                ser.write(payload)
                ser.flush()
            except Exception:
                pass
            time.sleep(0.2)

        buffer = ""
        start_time = time.time()
        last_ping = start_time

        primary_markers = [
            (PROMPT_PRIV, "✅ Коммутатор готов (Switch#)", "priv"),
            (PROMPT_USER, "✅ Коммутатор готов (Switch>)", "user"),
            (PROMPT_REDUCED, "⚠️ Коммутатор в ROMMON режиме", "rommon"),
        ]
        secondary_markers = [
            ("Press RETURN to get started", "⚙️ Устройство ожидает нажатия Enter", "press_return"),
            ("User Access Verification", "🔐 Требуется авторизация (User Access Verification)", "login"),
            ("Username:", "🔐 Требуется ввод логина", "login"),
            ("Password:", "🔑 Требуется пароль", "login"),
            ("Would you like to enter the initial configuration dialog", "⚙️ Initial config dialog активен", "config_dialog"),
        ]

        while time.time() - start_time < timeout:
            try:
                chunk = ser.read(ser.in_waiting or 256)
            except serial.SerialException as e:
                return (False, f"Ошибка чтения: {e}", None)

            if chunk:
                decoded = chunk.decode('utf-8', errors='ignore')
                buffer += decoded

                for marker, message, prompt in primary_markers:
                    if marker and marker in buffer:
                        if prompt in ("priv", "user"):
                            # Попытка вытащить версию ПО для отображения
                            fw_match = re.search(r'Version\s+([\w()./-]+)', buffer)
                            if fw_match:
                                message = f"{message} - FW: {fw_match.group(1)}"
                        return (True, message, prompt)

                for marker, message, prompt in secondary_markers:
                    if marker and marker in buffer:
                        return (True, message, prompt)

            if time.time() - last_ping >= 1.5:
                try:
                    ser.write(b"\r\n")
                except Exception:
                    pass
                last_ping = time.time()

            time.sleep(0.2)

        if buffer.strip():
            tail_line = buffer.strip().splitlines()[-1]
            tail_preview = tail_line[-80:]
            return (True, f"❓ Устройство отвечает, но приглашение не распознано (фрагмент: {tail_preview})", "unknown")

        return (False, "❌ Нет ответа от устройства", None)

    except serial.SerialException as e:
        if "PermissionError" in str(e) or "Access is denied" in str(e):
            return (False, "Порт занят другой программой", None)
        return (False, f"Ошибка: {str(e)}", None)
    except Exception as e:
        return (False, f"Ошибка: {str(e)}", None)
    finally:
        try:
            if ser and ser.is_open:
                ser.close()
        except Exception:
            pass

def scan_all_ports_for_devices():
    """Scan all COM ports and check for responding devices
    Returns: list of (port, is_available, status, prompt_type)
    
    IMPROVED: Longer timeout for reliable Cisco detection
    """
    ports = serial.tools.list_ports.comports()
    results = []
    
    for p in ports:
        # Use 10 second timeout for thorough check
        available, status, prompt = check_device_availability(p.device, timeout=10)
        results.append({
            'port': p.device,
            'description': p.description,
            'available': available,
            'status': status,
            'prompt_type': prompt
        })
    
    return results

# ---------------------- GUI & Core Workflow ----------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME)
        root.geometry("1000x1000")
        root.resizable(False, False)  # Фиксированный размер

        # Single instance lock
        self.lock = SingleInstanceLock(LOCK_FILE)
        if not self.lock.acquire():
            messagebox.showerror(
                "Уже запущено", 
                "Приложение уже запущено в другом окне.\nЗавершите предыдущий экземпляр перед запуском нового."
            )
            root.destroy()
            sys.exit(1)

        # State
        self.serial_ctrl = None
        self.running = False
        self.log_path = LOG_FILE_PATH
        self.report_path = REPORT_FILE_PATH
        self.worker_thread = None
        self.early_logs = []  # Для хранения логов до создания UI
        
        # IDLE AI: Health Monitor
        self.health_monitor = HealthMonitor(LOG_DIR)
        
        # IDLE AI: Register cleanup handlers
        shutdown_manager.register_cleanup(
            lambda: self.health_monitor.health_check(),
            "Saving health metrics"
        )
        shutdown_manager.register_cleanup(
            lambda: self._safe_close_serial(),
            "Closing serial connection"
        )
        
        # Auto-reconnect system (v3.0)
        self.auto_reconnect_enabled = False
        self.auto_reconnect_thread = None
        self.reconnect_attempts = 0

        # Installation tracking
        self.install_stages = {
            'examining': False,
            'extracting': False,
            'installing': False,
            'signature_verified': False,
            'deleting_old': False,
            'reload_requested': False
        }

        # Build UI
        self._build_ui()
        
        # Setup cleanup on close
        root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Auto-scan ВКЛЮЧЕНО - сканирование при запуске (после создания UI)
        root.after(500, self.auto_scan_on_startup)

    def _build_ui(self):
        root = self.root
        root.configure(bg='#f0f0f0')
        
        # ========== HEADER WITH LOGO ==========
        header_frame = tk.Frame(root, bg='#2c3e50', height=80)
        header_frame.pack(fill="x", padx=0, pady=0)
        header_frame.pack_propagate(False)
        
        # Simplified Header - CiscoAutoFlash Powered by InRack
        dry_run_suffix = " (dry-run)" if DRY_RUN else ""
        title_label = tk.Label(
            header_frame,
            text=f"🔧 CiscoAutoFlash v3.0{dry_run_suffix}",
            font=("Arial", 20, "bold"),
            bg='#2c3e50',
            fg='white'
        )
        title_label.pack(side="left", padx=20, pady=25)
        
        # Animated "Powered by InRack" label
        self.powered_label = tk.Label(
            header_frame,
            text="Powered by InRack",
            font=("Arial", 14, "bold"),
            bg='#2c3e50',
            fg='#3498db'  # Начальный цвет
        )
        self.powered_label.pack(side="left", padx=5, pady=25)
        
        # Цвета для анимации InRack (голубой-синий-серый)
        self.inrack_colors = ['#3498db', '#2980b9', '#5dade2', '#85c1e9', '#7f8c8d', '#5499c7']
        self.color_index = 0
        self.animate_inrack()
        
        # ========== QUICK TIPS PANEL (v3.0) ==========
        tips_frame = tk.Frame(root, bg='#ecf8f8', relief='solid', borderwidth=2)
        tips_frame.pack(fill="x", padx=15, pady=(0, 12))
        
        tips_header = tk.Label(
            tips_frame,
            text="💡 Быстрые подсказки",
            font=("Arial", 9, "bold"),
            bg='#ecf8f8',
            fg='#16a085'
        )
        tips_header.pack(anchor="w", padx=15, pady=(10, 5))
        
        self.tips_text = tk.StringVar(value="Автоматический поиск коммутатора активирован. Подключите USB-RJ45 кабель и дождитесь обнаружения устройства.")
        self.tips_label = tk.Label(
            tips_frame,
            textvariable=self.tips_text,
            font=("Arial", 8),
            bg='#ecf8f8',
            fg='#34495e',
            wraplength=950,
            justify="left"
        )
        self.tips_label.pack(anchor="w", padx=30, pady=(0, 10))
        
        # ========== CONNECTION STATUS PANEL (v4.0) ==========
        self.connection_panel = tk.Frame(root, bg='#f8f9fa', relief='solid', borderwidth=2)
        # Панель скрыта по умолчанию и показывается после сканирования
        
        conn_panel_header = tk.Label(
            self.connection_panel,
            text="🔌 СОСТОЯНИЕ ПОДКЛЮЧЕНИЯ",
            font=("Arial", 12, "bold"),
            bg='#f8f9fa',
            fg='#2c3e50'
        )
        conn_panel_header.pack(pady=(15, 10))

        # Создаем фрейм для индикаторов в ряд
        indicators_frame = tk.Frame(self.connection_panel, bg='#f8f9fa')
        indicators_frame.pack(fill="x", padx=20, pady=(0, 15))

        # Индикатор питания
        power_frame = tk.Frame(indicators_frame, bg='#f8f9fa')
        power_frame.pack(side="left", padx=15)

        self.power_icon = tk.Label(
            power_frame,
            text="🔴",
            font=("Arial", 20),
            bg='#f8f9fa',
            fg='#e74c3c'
        )
        self.power_icon.pack()

        self.power_label = tk.Label(
            power_frame,
            text="Питание: Не обнаружено",
            font=("Arial", 9, "bold"),
            bg='#f8f9fa',
            fg='#7f8c8d',
            wraplength=120,
            justify="center"
        )
        self.power_label.pack()

        # Индикатор RJ45-USB
        usb_frame = tk.Frame(indicators_frame, bg='#f8f9fa')
        usb_frame.pack(side="left", padx=15)

        self.usb_icon = tk.Label(
            usb_frame,
            text="🟡",
            font=("Arial", 20),
            bg='#f8f9fa',
            fg='#f39c12'
        )
        self.usb_icon.pack()

        self.usb_label = tk.Label(
            usb_frame,
            text="RJ45-USB: Ожидание",
            font=("Arial", 9, "bold"),
            bg='#f8f9fa',
            fg='#7f8c8d',
            wraplength=120,
            justify="center"
        )
        self.usb_label.pack()

        # Индикатор COM-порта
        com_frame = tk.Frame(indicators_frame, bg='#f8f9fa')
        com_frame.pack(side="left", padx=15)

        self.com_icon = tk.Label(
            com_frame,
            text="🟢",
            font=("Arial", 20),
            bg='#f8f9fa',
            fg='#27ae60'
        )
        self.com_icon.pack()

        self.com_label = tk.Label(
            com_frame,
            text="COM-порт: Готов",
            font=("Arial", 9, "bold"),
            bg='#f8f9fa',
            fg='#7f8c8d',
            wraplength=120,
            justify="center"
        )
        self.com_label.pack()

        # Индикатор флешки
        flash_frame = tk.Frame(indicators_frame, bg='#f8f9fa')
        flash_frame.pack(side="left", padx=15)

        self.flash_icon = tk.Label(
            flash_frame,
            text="🔴",
            font=("Arial", 20),
            bg='#f8f9fa',
            fg='#e74c3c'
        )
        self.flash_icon.pack()

        self.flash_label = tk.Label(
            flash_frame,
            text="USB-флешка: Не найдена",
            font=("Arial", 9, "bold"),
            bg='#f8f9fa',
            fg='#7f8c8d',
            wraplength=120,
            justify="center"
        )
        self.flash_label.pack()

        # Общий статус
        self.overall_frame = tk.Frame(self.connection_panel, bg='#f8f9fa')
        self.overall_frame.pack(fill="x", padx=20, pady=(0, 15))

        self.overall_icon = tk.Label(
            self.overall_frame,
            text="🔴",
            font=("Arial", 16),
            bg='#f8f9fa',
            fg='#e74c3c'
        )
        self.overall_icon.pack(side="left", padx=(0, 10))

        self.overall_label = tk.Label(
            self.overall_frame,
            text="ОБЩИЙ СТАТУС: ТРЕБУЕТСЯ ВНИМАНИЕ",
            font=("Arial", 10, "bold"),
            bg='#f8f9fa',
            fg='#e74c3c'
        )
        self.overall_label.pack(side="left")

        # ========== INFO PANEL (5 columns) ==========
        info_frame = tk.Frame(root, bg='#ecf0f1', height=110)
        info_frame.pack(fill="x", padx=0, pady=0)
        info_frame.pack_propagate(False)

        # Сохраняем ссылку на info_frame для других методов
        self.info_frame = info_frame

        # Column 1 - Device Status
        col1 = tk.Frame(info_frame, bg='#ecf0f1')
        col1.pack(side="left", padx=15, pady=10)

        tk.Label(
            col1,
            text="🔍 Устройство",
            font=("Arial", 10, "bold"),
            bg='#ecf0f1',
            fg='#2c3e50'
        ).pack(anchor="w")

        self.device_status_var = tk.StringVar(value="Ожидание сканирования...")
        self.device_status_label = tk.Label(
            col1,
            textvariable=self.device_status_var,
            font=("Arial", 9),
            bg='#ecf0f1',
            fg='#34495e',
            wraplength=180,
            justify="left"
        )
        self.device_status_label.pack(anchor="w")

        # Column 2 - Current Firmware
        col2 = tk.Frame(info_frame, bg='#ecf0f1')
        col2.pack(side="left", padx=15, pady=10)

        tk.Label(
            col2,
            text="💾 Текущая прошивка",
            font=("Arial", 10, "bold"),
            bg='#ecf0f1',
            fg='#2c3e50'
        ).pack(anchor="w")

        self.current_fw_var = tk.StringVar(value="Не определена")
        self.current_fw_label = tk.Label(
            col2,
            textvariable=self.current_fw_var,
            font=("Arial", 11, "bold"),
            bg='#ecf0f1',
            fg='#7f8c8d'
        )
        self.current_fw_label.pack(anchor="w")

        # Column 3 - Device Model
        col3 = tk.Frame(info_frame, bg='#ecf0f1')
        col3.pack(side="left", padx=15, pady=10)

        tk.Label(
            col3,
            text="🖥️ Модель",
            font=("Arial", 10, "bold"),
            bg='#ecf0f1',
            fg='#2c3e50'
        ).pack(anchor="w")

        self.model_var = tk.StringVar(value="Не определена")
        tk.Label(
            col3,
            textvariable=self.model_var,
            font=("Arial", 9),
            bg='#ecf0f1',
            fg='#34495e'
        ).pack(anchor="w")

        # Column 4 - Flash Info
        col4 = tk.Frame(info_frame, bg='#ecf0f1')
        col4.pack(side="left", padx=15, pady=10)

        tk.Label(
            col4,
            text="💽 Flash память",
            font=("Arial", 10, "bold"),
            bg='#ecf0f1',
            fg='#2c3e50'
        ).pack(anchor="w")

        self.flash_var = tk.StringVar(value="Не определена")
        tk.Label(
            col4,
            textvariable=self.flash_var,
            font=("Arial", 9),
            bg='#ecf0f1',
            fg='#34495e'
        ).pack(anchor="w")

        # Column 5 - Uptime
        col5 = tk.Frame(info_frame, bg='#ecf0f1')
        col5.pack(side="left", padx=15, pady=10)

        tk.Label(
            col5,
            text="⏱️ Время работы",
            font=("Arial", 10, "bold"),
            bg='#ecf0f1',
            fg='#2c3e50'
        ).pack(anchor="w")

        self.uptime_var = tk.StringVar(value="Не определено")
        tk.Label(
            col5,
            textvariable=self.uptime_var,
            font=("Arial", 9),
            bg='#ecf0f1',
            fg='#34495e'
        ).pack(anchor="w")

    def start_status_animation(self, indicator_type):
        """Запуск анимации индикаторов состояния подключения."""
        root = self.root
        
        def animate_indicator(label_widget, sequence, delay_ms):
            current = getattr(label_widget, "_seq_index", 0)
            next_index = (current + 1) % len(sequence)
            label_widget.config(text=sequence[next_index])
            label_widget._seq_index = next_index
            root.after(delay_ms, animate_indicator, label_widget, sequence, delay_ms)
        
        if indicator_type == 'com':
            animate_indicator(self.com_icon, ['🟢', '🟡'], 500)
        elif indicator_type == 'usb':
            animate_indicator(self.usb_icon, ['🟡', '🟠'], 600)
        elif indicator_type == 'power':
            animate_indicator(self.power_icon, ['🔴', '🟡'], 700)
        elif indicator_type == 'flash':
            animate_indicator(self.flash_icon, ['🔴', '🟡', '🔴'], 500)

        # ========== SEPARATOR LINE (v3.0) ==========
        ttk.Separator(root, orient='horizontal').pack(fill='x', padx=20, pady=10)

        # ========== CONTROL PANEL ==========
        control_frame = tk.Frame(root, bg='white')
        control_frame.pack(fill="x", padx=10, pady=8)

        com_frame = tk.Frame(control_frame, bg='white')
        com_frame.pack(side="left", padx=5)

        tk.Label(com_frame, text="COM порт:", bg='white', font=("Arial", 9)).pack(side="left", padx=5)
        self.com_var = tk.StringVar(value="")
        self.com_combo = ttk.Combobox(com_frame, textvariable=self.com_var, width=12, font=("Arial", 9))
        self.com_combo['values'] = [p[0] for p in detect_com_ports()]
        self.com_combo.pack(side="left", padx=5)

        # Автопоиск всегда включен (v3.0 - убрана кнопка)
        self.auto_var = tk.BooleanVar(value=True)

        # Убрана кнопка ручного сканирования - используется только автоматическое
        # self.scan_btn = ttk.Button(control_frame, text="🔍 Сканировать устройства", command=self.scan_devices, width=25)
        # self.scan_btn.pack(side="left", padx=8)

        self.refresh_btn = ttk.Button(control_frame, text="🔄 Обновить COM-порты", command=self.refresh_com_list, width=20)
        self.refresh_btn.pack(side="left", padx=8)

        # ========== ACTION BUTTONS (2 РЯДА) ==========
        btn_frame = tk.Frame(root, bg='white')
        btn_frame.pack(fill="x", padx=10, pady=8)

        # Row 1 - Stage buttons
        row1 = tk.Frame(btn_frame, bg='white')
        row1.pack(fill="x", pady=(0, 10))

        self.start_button = ttk.Button(
            row1,
            text="  1️⃣  Stage 1: Сброс конфигурации  ",
            command=self.start_stage1,
            width=40
        )
        self.start_button.pack(side="left", padx=12, ipady=8)
        
        self.stage2_button = ttk.Button(
            row1,
            text="  2️⃣  Stage 2: Установка прошивки  ",
            command=self.start_stage2,
            state="disabled",
            width=40
        )
        self.stage2_button.pack(side="left", padx=12, ipady=8)
        
        self.stage3_button = ttk.Button(
            row1,
            text="  3️⃣  Stage 3: Верификация  ",
            command=self.start_stage3,
            state="normal",  # Always enabled - can run independently
            width=40
        )
        self.stage3_button.pack(side="left", padx=12, ipady=8)

        # Row 2 - Control buttons
        row2 = tk.Frame(btn_frame, bg='white')
        row2.pack(fill="x")

        self.stop_button = ttk.Button(
            row2,
            text="  ⛔  Остановить процесс  ",
            command=self.stop_all,
            state="disabled",
            width=30
        )
        self.stop_button.pack(side="left", padx=12, ipady=8)
        
        self.open_log_btn = ttk.Button(
            row2,
            text="  📄  Открыть лог-файл  ",
            command=self.open_log,
            width=30
        )
        self.open_log_btn.pack(side="left", padx=12, ipady=8)
        
        self.open_report_btn = ttk.Button(
            row2,
            text="  📊  Открыть отчет  ",
            command=self.open_report,
            state="disabled",
            width=30
        )
        self.open_report_btn.pack(side="left", padx=12, ipady=8)
        
        # IDLE AI: Health Check button
        self.health_check_btn = ttk.Button(
            row2,
            text="  📡  Health Check  ",
            command=self.show_health_check,
            width=30
        )
        self.health_check_btn.pack(side="left", padx=12, ipady=8)

        # ========== SEPARATOR LINE (v3.0) ==========
        ttk.Separator(root, orient='horizontal').pack(fill='x', padx=20, pady=10)
        
        # ========== PROGRESS TRACKING PANEL (v3.0) ==========
        self.progress_frame = tk.Frame(root, bg='white', relief='solid', borderwidth=2)
        # Скрыт по умолчанию, показывается во время Stage 2
        # self.progress_frame.pack(fill="x", padx=15, pady=12)
        
        # Stage name
        self.progress_stage_var = tk.StringVar(value="Stage 2: Установка прошивки")
        tk.Label(
            self.progress_frame,
            textvariable=self.progress_stage_var,
            font=("Arial", 11, "bold"),
            bg='white',
            fg='#2c3e50'
        ).pack(pady=(12, 8))
        
        # Progress bar
        self.progress_var = tk.IntVar(value=0)
        progress_container = tk.Frame(self.progress_frame, bg='white')
        progress_container.pack(fill="x", padx=25, pady=8)
        
        tk.Label(
            progress_container,
            text="Прогресс:",
            font=("Arial", 9),
            bg='white',
            fg='#34495e'
        ).pack(side="left", padx=(0, 10))
        
        self.progress_bar = ttk.Progressbar(
            progress_container,
            variable=self.progress_var,
            maximum=100,
            mode='determinate',
            length=600
        )
        self.progress_bar.pack(side="left", fill="x", expand=True)
        
        self.progress_percent_label = tk.Label(
            progress_container,
            text="0%",
            font=("Arial", 10, "bold"),
            bg='white',
            fg='#3498db',
            width=5
        )
        self.progress_percent_label.pack(side="left", padx=(15, 0))
        
        # Current stage info
        stage_info_frame = tk.Frame(self.progress_frame, bg='white')
        stage_info_frame.pack(fill="x", padx=25, pady=8)
        
        tk.Label(
            stage_info_frame,
            text="Текущий этап:",
            font=("Arial", 9),
            bg='white',
            fg='#34495e'
        ).pack(side="left")
        
        self.current_stage_var = tk.StringVar(value="Ожидание...")
        tk.Label(
            stage_info_frame,
            textvariable=self.current_stage_var,
            font=("Arial", 9, "bold"),
            bg='white',
            fg='#2c3e50'
        ).pack(side="left", padx=(10, 0))
        
        # Time info
        time_info_frame = tk.Frame(self.progress_frame, bg='white')
        time_info_frame.pack(fill="x", padx=25, pady=(0, 12))
        
        tk.Label(
            time_info_frame,
            text="⏱️ Прошло:",
            font=("Arial", 9),
            bg='white',
            fg='#34495e'
        ).pack(side="left")
        
        self.elapsed_time_var = tk.StringVar(value="0:00")
        tk.Label(
            time_info_frame,
            textvariable=self.elapsed_time_var,
            font=("Arial", 9),
            bg='white',
            fg='#7f8c8d'
        ).pack(side="left", padx=(5, 20))
        
        tk.Label(
            time_info_frame,
            text="📊 Примерно осталось:",
            font=("Arial", 9),
            bg='white',
            fg='#34495e'
        ).pack(side="left")
        
        self.remaining_time_var = tk.StringVar(value="~10-15 мин")
        tk.Label(
            time_info_frame,
            textvariable=self.remaining_time_var,
            font=("Arial", 9),
            bg='white',
            fg='#7f8c8d'
        ).pack(side="left", padx=(5, 0))
        
        # Progress tracking variables
        self.stage2_start_time = None
        self.stage2_current_stage = 0
        self.stage2_total_stages = 5

        # ========== LOG AREA ==========
        log_frame = tk.Frame(root, bg='white')
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        tk.Label(
            log_frame,
            text="📋 Журнал операций:",
            font=("Arial", 10, "bold"),
            bg='white',
            fg='#2c3e50'
        ).pack(anchor="w", pady=(0, 5))
        
        self.log_box = scrolledtext.ScrolledText(
            log_frame,
            height=28,
            wrap="none",
            font=("Consolas", 9),
            bg='#1e1e1e',
            fg='#d4d4d4',
            insertbackground='white'
        )
        self.log_box.pack(fill="both", expand=True)
        self._setup_tags()

        # Переносим ранние логи в GUI
        self.flush_early_logs()

        # ========== ENHANCED FOOTER STATUS BAR (v3.0) ==========
        footer_frame = tk.Frame(root, bg='#2c3e50', height=40)
        footer_frame.pack(fill="x", padx=0, pady=0)
        footer_frame.pack_propagate(False)
        
        # Left side - Main status
        left_footer = tk.Frame(footer_frame, bg='#2c3e50')
        left_footer.pack(side="left", fill="y", padx=15)
        
        status_text = "DRY-RUN: команды не отправляются" if DRY_RUN else "Готов к работе"
        self.status_var = tk.StringVar(value=status_text)
        status_label = tk.Label(
            left_footer,
            textvariable=self.status_var,
            font=("Arial", 10, "bold"),
            bg='#2c3e50',
            fg='#2ecc71',
            anchor="w"
        )
        status_label.pack(side="left", pady=10)
        
        # Separator
        tk.Label(footer_frame, text="│", bg='#2c3e50', fg='#7f8c8d', font=("Arial", 14)).pack(side="left", padx=10)
        
        # Middle - Connection status
        middle_footer = tk.Frame(footer_frame, bg='#2c3e50')
        middle_footer.pack(side="left", fill="y")
        
        self.footer_connection_var = tk.StringVar(value="🔌 COM: —")
        connection_label = tk.Label(
            middle_footer,
            textvariable=self.footer_connection_var,
            font=("Arial", 9),
            bg='#2c3e50',
            fg='#95a5a6',
            anchor="w"
        )
        connection_label.pack(side="left", pady=10)
        
        # Separator
        tk.Label(footer_frame, text="│", bg='#2c3e50', fg='#7f8c8d', font=("Arial", 14)).pack(side="left", padx=10)
        
        # Right side - Version & Time
        right_footer = tk.Frame(footer_frame, bg='#2c3e50')
        right_footer.pack(side="right", fill="y", padx=15)
        
        version_label = tk.Label(
            right_footer,
            text="v3.0 Commercial",
            font=("Arial", 8),
            bg='#2c3e50',
            fg='#7f8c8d'
        )
        version_label.pack(side="right", pady=10, padx=(10, 0))
        
        self.footer_time_var = tk.StringVar(value="⏱️ 00:00")
        time_label = tk.Label(
            right_footer,
            textvariable=self.footer_time_var,
            font=("Arial", 9),
            bg='#2c3e50',
            fg='#95a5a6'
        )
        time_label.pack(side="right", pady=10)

    def _setup_tags(self):
        # Dark theme colors for log
        self.log_box.tag_config("time", foreground="#858585")
        self.log_box.tag_config("info", foreground="#4FC3F7")  # Light blue
        self.log_box.tag_config("ok", foreground="#66BB6A")    # Green
        self.log_box.tag_config("warn", foreground="#FFA726")  # Orange
        self.log_box.tag_config("err", foreground="#EF5350")   # Red
        self.log_box.tag_config("debug", foreground="#9E9E9E") # Gray

    def _append_log_line(self, line, level):
        """Добавляет строку в GUI-лог (ТОЛЬКО из главного потока)."""
        try:
            if hasattr(self, 'log_box') and self.log_box and self.log_box.winfo_exists():
                self.log_box.insert("end", line + "\n", level)
                self.log_box.see("end")
        except Exception:
            pass  # Игнорируем ошибки GUI
    
    def log_direct(self, message, level="info"):
        """Прямое логирование из main thread без использования root.after"""
        line = f"{timestamp()} | {message}"
        
        # Сохраняем в файл
        safe_write_log_file(line, self.log_path)
        
        # Добавляем напрямую в GUI (только из main thread!)
        self._append_log_line(line, level)
        
        # Выводим в консоль
        try:
            print(line)
        except UnicodeEncodeError:
            safe_line = line.encode('cp1251', errors='replace').decode('cp1251', errors='replace')
            print(safe_line)

    def run_on_main(self, func, *args):
        """Безопасный вызов функции в главном потоке Tk."""
        self.root.after(0, func, *args)

    def log(self, message, level="info", also_console=True):
        line = f"{timestamp()} | {message}"

        # Сохраняем в файл всегда
        safe_write_log_file(line, self.log_path)

        # Добавляем в GUI
        if not hasattr(self, 'log_box') or self.log_box is None:
            self.early_logs.append((line, level))
        else:
            # Используем root.after для безопасного добавления из любого потока
            # Важно: захватываем значения line и level в параметры lambda по умолчанию
            try:
                self.root.after(0, lambda l=line, lv=level: self._append_log_line(l, lv))
            except Exception:
                pass  # Игнорируем если GUI уже закрыт

        if also_console:
            try:
                print(line)
            except UnicodeEncodeError:
                safe_line = line.encode('cp1251', errors='replace').decode('cp1251', errors='replace')
                print(safe_line)

    def flush_early_logs(self):
        """Перенос ранних логов в GUI лог-бокс"""
        if hasattr(self, 'log_box') and self.log_box is not None:
            for line, level in self.early_logs:
                self.log_box.insert("end", line + "\n", level)
            self.log_box.see("end")
            self.early_logs.clear()

    def refresh_com_list(self):
        ports = detect_com_ports()
        self.com_combo['values'] = [p[0] for p in ports]
        if ports:
            self.com_var.set(ports[0][0])
        else:
            self.com_var.set("")
        self.log("Список COM обновлён", "debug")
    
    def auto_scan_on_startup(self):
        """Автоматическое сканирование при запуске"""
        self.log("🔍 Автоматическое сканирование COM-портов при запуске...", "info")

        # Показываем Connection Status Panel
        self.show_connection_panel()

        # Устанавливаем начальный статус сканирования с анимацией
        self.update_connection_status_v4(
            power_status='yellow',
            usb_status='yellow',
            com_status='yellow',
            flash_status='gray'
        )

        # Запускаем анимацию спиннера для COM-порта
        self.start_status_animation('com')

        self.device_status_var.set("Сканирование...")
        self.device_status_label.config(fg="#3498db")
        self.current_fw_var.set("Определяется...")
        self.current_fw_label.config(fg="#3498db")
        self.model_var.set("Определяется...")
        self.flash_var.set("Определяется...")
        self.uptime_var.set("Определяется...")

        # Run scan in background thread
        thread = threading.Thread(target=self._do_scan, daemon=True)
        thread.start()
    
    def scan_devices(self):
        """Ручное сканирование устройств"""
        self.log("🔍 Запущено ручное сканирование COM-портов...", "info")

        # Показываем Connection Status Panel
        self.show_connection_panel()

        # Устанавливаем статус сканирования с анимацией
        self.update_connection_status_v4(
            power_status='yellow',
            usb_status='yellow',
            com_status='yellow',
            flash_status='gray'
        )

        # Запускаем анимацию спиннера для COM-порта
        self.start_status_animation('com')

        self.device_status_var.set("Статус: Сканирование...")
        self.device_status_label.config(foreground="blue")

        # Run scan in background thread
        thread = threading.Thread(target=self._do_scan, daemon=True)
        thread.start()
    
    def _do_scan(self):
        """Выполнение сканирования в фоновом потоке"""
        try:
            results = scan_all_ports_for_devices()
            
            # Update GUI from results
            def update_gui():
                self.log_direct("", "info")
                self.log_direct("📊 Результаты сканирования:", "info")
                self.log_direct("=" * 80, "info")
                
                found_device = None
                found_priority = -1
                prompt_priority = {
                    'priv': 4,
                    'user': 3,
                    'rommon': 2,
                    'config_dialog': 2,
                    'press_return': 2,
                    'login': 2,
                    'unknown': 1
                }
                for result in results:
                    port = result['port']
                    desc = result['description']
                    available = result['available']
                    status = result['status']
                    prompt_type = result['prompt_type']
                    
                    if available:
                        priority = prompt_priority.get(prompt_type, 0)

                        if prompt_type in ['priv', 'user']:
                            log_level = "ok"
                        elif prompt_type in ['rommon', 'config_dialog', 'press_return', 'login']:
                            log_level = "warn"
                        else:
                            log_level = "debug"

                        icon = "✅" if prompt_type in ['priv', 'user'] else "⚠️" if priority >= 2 else "❓"
                        self.log_direct(f"{icon} {port}: {status}", log_level)
                        self.log_direct(f"   Описание: {desc}", "debug")

                        if priority > found_priority:
                            found_device = (port, status, prompt_type, priority)
                            found_priority = priority
                    else:
                        self.log_direct(f"❌ {port}: {status}", "debug")
                        self.log_direct(f"   Описание: {desc}", "debug")
                
                self.log_direct("=" * 80, "info")
                
                # Update status and auto-select port
                if found_device:
                    port, status, prompt_type, priority_score = found_device
                    self.com_var.set(port)

                    # Extract FW version if present
                    fw_version = "Не определена"
                    if "FW:" in status:
                        fw_version = status.split("FW:")[1].strip()

                    # Update device status
                    device_text = status.replace(f" - FW: {fw_version}", "") if "FW:" in status else status
                    self.device_status_var.set(f"{port} - {device_text}")
                    self.device_status_label.config(fg="#27ae60")

                    # Update FW version display
                    self.current_fw_var.set(fw_version)
                    self.current_fw_label.config(fg="#27ae60")

                    # Update additional info (will be filled later from show version)
                    self.model_var.set("Определяется...")
                    self.flash_var.set("Определяется...")
                    self.uptime_var.set("Определяется...")

                    # ===== UPDATE CONNECTION STATUS PANEL v4.0 =====
                    # Выбор цветов индикаторов
                    usb_state = 'green' if priority_score >= 2 else 'yellow'
                    flash_state = 'gray'

                    self.update_connection_status_v4(
                        power_status='green',
                        usb_status=usb_state,
                        com_status='green',
                        flash_status=flash_state
                    )

                    # Останавливаем анимацию спиннера
                    # (анимация остановится автоматически при изменении текста)

                    # Get detailed info in background (только если устройство уже в CLI)
                    if prompt_type in ('priv', 'user'):
                        threading.Thread(target=self._get_device_details, args=(port,), daemon=True).start()

                    self.log_direct(f"✅ Автоматически выбран порт: {port}", "ok")
                    
                    # IDLE AI: Record successful connection
                    self.health_monitor.record_operation(
                        "device_connected", 
                        True,
                        port=port,
                        prompt_type=prompt_type
                    )

                    # ===== UPDATE TIPS (v3.0) =====
                    if prompt_type in ('priv', 'user'):
                        self.update_tips("✅ Коммутатор найден и готов! Теперь можете запустить Stage 1 (Сброс конфигурации)")
                    elif prompt_type == 'press_return':
                        self.update_tips("⚙️ Коммутатор просит нажать Enter в консоли. Нажмите ENTER, дождитесь приглашения Switch# и запустите Stage 1")
                    elif prompt_type == 'login':
                        self.update_tips("🔐 Коммутатор найден, требуется авторизация. Выполните вход вручную (login/password), система автоматически обнаружит устройство после входа.")
                    elif prompt_type == 'config_dialog':
                        self.update_tips("⚙️ Коммутатор спрашивает про initial config dialog. Нажмите 'no' вручную, дождитесь Switch#, затем повторите сканирование")
                    elif prompt_type == 'rommon':
                        self.update_tips("⚠️ Коммутатор в ROMMON. Перезагрузите устройство в нормальный режим или выполните восстановление")
                        self.update_connection_status_v4(usb_status='green')
                    else:
                        self.update_tips("❓ Обнаружен ответ от устройства, но приглашение не распознано. Проверьте консоль вручную.")

                    # ===== UPDATE FOOTER (v3.0) =====
                    self.footer_connection_var.set(f"🔌 COM: {port} | Catalyst 2960-X")
                else:
                    # Нет отвечающих устройств: полностью сбрасываем статус
                    self.device_status_var.set("Нет отвечающих устройств")
                    self.device_status_label.config(fg="#e74c3c")
                    self.current_fw_var.set("Не определена")
                    self.current_fw_label.config(fg="gray")
                    self.model_var.set("Не определена")
                    self.flash_var.set("Не определена")
                    self.uptime_var.set("Не определено")

                    self.update_connection_status_v4(
                        power_status='yellow',
                        usb_status='yellow',
                        com_status='yellow',
                        flash_status='gray'
                    )

                    # Останавливаем анимацию спиннера (если она была запущена)
                    # (анимация остановится автоматически при изменении текста)

                    self.log_direct("⚠️ Не найдено отвечающих устройств", "warn")
                    self.log_direct("💡 Проверьте:", "info")
                    self.log_direct("   1. USB-консольный кабель подключен", "info")
                    self.log_direct("   2. Коммутатор включен и загрузился", "info")
                    self.log_direct("   3. Порт не занят другой программой (PuTTY, терминал)", "info")
                    self.log_direct("", "info")

                    # ===== UPDATE TIPS (v3.0) =====
                    self.update_tips("⚠️ Коммутатор не найден. Проверьте подключение USB-RJ45 кабеля и питание. Автопоиск каждые 3 секунды...")

                    # ===== START AUTO-RECONNECT (v3.0) =====
                    if not self.auto_reconnect_enabled:
                        self.log_direct("🔄 Автоматическое переподключение активировано", "info")
                        self.log_direct("   Повторные попытки каждые 3 секунды...", "info")
                        self.start_auto_reconnect()
                
                self.log_direct("", "info")
            
            # Schedule GUI update on main thread
            self.run_on_main(update_gui)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            def show_error():
                self.log(f"❌ Ошибка при сканировании: {e}", "err")
                self.device_status_var.set("❌ Ошибка сканирования")
                self.device_status_label.config(foreground="red")
                self.update_connection_status_v4(
                    power_status='yellow',
                    usb_status='yellow',
                    com_status='yellow',
                    flash_status='gray'
                )
            self.run_on_main(show_error)
            traceback.print_exc()

    def open_log(self):
        try:
            os.startfile(self.log_path)
        except Exception:
            messagebox.showinfo("Открыть лог", f"Лог сохранён в: {self.log_path}")
    
    def open_report(self):
        try:
            if self.report_path.exists():
                os.startfile(self.report_path)
            else:
                messagebox.showinfo("Отчет", "Отчет еще не создан")
        except Exception:
            messagebox.showinfo("Открыть отчет", f"Отчет сохранён в: {self.report_path}")
    
    def show_health_check(self):
        """Показать Health Check метрики (IDLE AI)"""
        try:
            health = self.health_monitor.health_check()
            
            # Форматирование сообщения
            status_icon = "✅" if health["status"] == "healthy" else "⚠️"
            uptime_minutes = health["uptime_seconds"] // 60
            error_rate = health["error_rate"] * 100
            
            msg = f"{status_icon} Статус: {health['status'].upper()}\n\n"
            msg += f"🕒 Uptime: {uptime_minutes} мин\n"
            msg += f"📊 Операций: {health['metrics']['operations']}\n"
            msg += f"❌ Ошибок: {health['metrics']['errors']}\n"
            msg += f"📉 Error Rate: {error_rate:.1f}%\n\n"
            
            # Информация о Stage
            if health['metrics']['stages_completed']:
                msg += "🎯 Завершённые Stage:\n"
                for stage, data in health['metrics']['stages_completed'].items():
                    status = "✅" if data['success'] else "❌"
                    msg += f"  {status} {stage}: {data['duration']:.1f}s\n"
                msg += "\n"
            
            # Performance данные
            if health['metrics']['performance']:
                msg += "⚡ Performance:\n"
                for stage, perf in health['metrics']['performance'].items():
                    msg += f"  {stage}: {perf['duration_seconds']}s, {perf['memory_mb']}MB\n"
                msg += "\n"
            
            msg += f"📄 Подробные метрики: {self.health_monitor.metrics_file}"
            
            messagebox.showinfo("📡 Health Check (IDLE AI)", msg)
            
            # Записываем операцию
            self.health_monitor.record_operation("health_check_viewed", True)
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось получить health метрики: {e}")
    
    def start_auto_reconnect(self):
        """Запуск системы автоматического переподключения (v3.0)"""
        if not self.auto_reconnect_enabled:
            self.auto_reconnect_enabled = True
            self.reconnect_attempts = 0
            self.auto_reconnect_thread = threading.Thread(target=self._auto_reconnect_loop, daemon=True)
            self.auto_reconnect_thread.start()
    
    def stop_auto_reconnect(self):
        """Остановка автопереподключения"""
        self.auto_reconnect_enabled = False
        if self.auto_reconnect_thread:
            self.auto_reconnect_thread = None
    
    def _auto_reconnect_loop(self):
        """Цикл автоматического переподключения"""
        while self.auto_reconnect_enabled:
            time.sleep(3)  # Ждём 3 секунды
            
            if not self.auto_reconnect_enabled:
                break
                
            self.reconnect_attempts += 1
            
            def log_attempt():
                self.log(f"🔄 Попытка переподключения #{self.reconnect_attempts}...", "debug")
            self.run_on_main(log_attempt)
            
            # Проверка портов
            try:
                results = scan_all_ports_for_devices()
                
                found = False
                responsive_states = {'priv', 'user', 'rommon', 'config_dialog', 'press_return', 'login'}
                for result in results:
                    if result['available'] and result['prompt_type'] in responsive_states:
                        found = True
                        port = result['port']
                        status = result['status']
                        
                        def reconnected():
                            self.log(f"✅ Устройство обнаружено на {port}!", "ok")
                            self.log(f"   Статус: {status}", "info")
                            self.log("🔄 Останавливаю автопереподключение...", "info")
                            self.stop_auto_reconnect()
                            # Запускаем новое сканирование для обновления UI
                            threading.Thread(target=self._do_scan, daemon=True).start()
                        
                        self.run_on_main(reconnected)
                        break
                
                if not found and self.reconnect_attempts % 10 == 0:
                    # Каждые 10 попыток показываем статус
                    def status_msg():
                        self.log(f"💡 Выполнено {self.reconnect_attempts} попыток. Продолжаю поиск...", "info")
                    self.run_on_main(status_msg)
                    
            except Exception as e:
                def log_error():
                    self.log(f"⚠️ Ошибка при автопереподключении: {e}", "debug")
                self.run_on_main(log_error)

    def animate_inrack(self):
        """Анимация переливания цвета для 'Powered by InRack' (v3.0)"""
        try:
            self.color_index = (self.color_index + 1) % len(self.inrack_colors)
            self.powered_label.config(fg=self.inrack_colors[self.color_index])
            # Повтор каждые 800мс
            self.root.after(800, self.animate_inrack)
        except:
            pass  # Игнорировать если окно закрыто

    def _exec_show_command(self, command, wait=2.0):
        """Выполняет команду на устройстве и возвращает вывод."""
        if not self.serial_ctrl:
            return ""
        try:
            self.serial_ctrl.flush_input()
            self.serial_ctrl.write(command + "\r")
            time.sleep(wait)
            return self.serial_ctrl.read_available()
        except Exception as e:
            self.log(f"⚠️ Ошибка выполнения '{command}': {e}", "warn")
            return ""

    def update_tips(self, message, fg="#34495e"):
        """Обновление текста блока быстрых подсказок."""
        self.tips_text.set(message)
        self.tips_label.config(fg=fg)

    def _get_device_details(self, port):
        """Получение дополнительных сведений об устройстве на выбранном порту."""
        try:
            self.log(f"[DEBUG] Запрос сведений об устройстве через {port}", "debug")

            with serial.Serial(port, 9600, timeout=1.0, write_timeout=1.0) as ser:
                time.sleep(0.3)
                try:
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                except Exception:
                    pass

                def read_window(window_seconds=2.5, step=0.2):
                    buffer = ""
                    end_time = time.time() + window_seconds
                    while time.time() < end_time:
                        waiting = ser.in_waiting
                        if waiting:
                            chunk = ser.read(waiting)
                            buffer += chunk.decode('utf-8', errors='ignore')
                        time.sleep(step)
                    return buffer

                def send(cmd, wait=1.0):
                    if cmd:
                        ser.write(cmd.encode('utf-8', errors='ignore') + b"\r\n")
                    else:
                        ser.write(b"\r\n")
                    return read_window(wait)

                # Получаем текущее приглашение
                prompt_output = send("", wait=1.2)

                if PROMPT_PRIV not in prompt_output:
                    if PROMPT_USER in prompt_output:
                        enable_output = send("enable", wait=1.5)
                        prompt_output += enable_output
                        if "Password" in enable_output:
                            self.log("[WARN] Требуется пароль enable. Получение сведений пропущено.", "warn")
                            self.run_on_main(lambda: self.update_tips("🔐 Введите пароль enable вручную и повторите сканирование"))
                            return
                        if PROMPT_PRIV not in prompt_output:
                            prompt_output += read_window(1.0)

                if PROMPT_PRIV not in prompt_output and PROMPT_USER not in prompt_output:
                    self.log("[WARN] Не удалось получить приглашение устройства для чтения сведений.", "warn")
                    return

                send("terminal length 0", wait=0.6)
                version_output = send("show version", wait=4.0)
                self.log(f"[DEBUG] Получено {len(version_output)} символов show version", "debug")

                model = None
                model_patterns = [
                    r"Model\s+[Nn]umber\s*:\s*([\w-]+)",
                    r"PID:\s*([\w-]+)",
                    r"(WS-C\d+[\w-]+)",
                ]
                for pattern in model_patterns:
                    match = re.search(pattern, version_output)
                    if match:
                        model = match.group(1)
                        break

                if model:
                    self.run_on_main(self.model_var.set, model)
                    self.log(f"[DEBUG] Модель: {model}", "debug")

                uptime_match = re.search(r"uptime is\s+([^\n,]+)", version_output, re.IGNORECASE)
                if uptime_match:
                    uptime_val = uptime_match.group(1).strip()
                    if len(uptime_val) > 24:
                        uptime_val = uptime_val[:21] + "..."
                    self.run_on_main(self.uptime_var.set, uptime_val)
                    self.log(f"[DEBUG] Uptime: {uptime_val}", "debug")

                version_match = re.search(r"Version\s+([\w()./-]+)", version_output)
                if version_match:
                    fw_version = version_match.group(1)
                    self.run_on_main(self.current_fw_var.set, fw_version)
                    self.log(f"[DEBUG] Версия ПО: {fw_version}", "debug")

                self.run_on_main(lambda: self.update_connection_status_v4(flash_status='yellow'))
                flash_output = send("dir flash:", wait=4.0)
                self.log(f"[DEBUG] Получено {len(flash_output)} символов dir flash:", "debug")

                free_bytes, total_bytes = parse_free_space(flash_output)
                if free_bytes and total_bytes:
                    total_mb = total_bytes / (1024 * 1024)
                    free_mb = free_bytes / (1024 * 1024)
                    flash_info = f"{total_mb:.0f}MB ({free_mb:.0f}MB free)"
                    self.run_on_main(self.flash_var.set, flash_info)
                    self.run_on_main(lambda: self.update_connection_status_v4(flash_status='green'))
                    self.log(f"[DEBUG] Flash: {flash_info}", "debug")

                # Проверка USB-флешки на коммутаторе
                usb_found = False
                for usb_path in ("usbflash0:", "usbflash1:"):
                    output = send(f"dir {usb_path}", wait=3.0)
                    # Проверяем успешный ответ (есть "Directory of") и отсутствие ошибок
                    if "Directory of" in output and "Error" not in output and "No such device" not in output:
                        usb_found = True
                        self.log(f"[DEBUG] Обнаружена флешка {usb_path}", "debug")
                        break
                    elif "Error" in output or "No such device" in output:
                        self.log(f"[DEBUG] Флешка {usb_path} не найдена (ошибка доступа)", "debug")

                if usb_found:
                    self.run_on_main(lambda: self.update_connection_status_v4(flash_status='green'))
                    self.log("[DEBUG] USB-флешка подключена к коммутатору", "debug")
                else:
                    self.run_on_main(lambda: self.update_connection_status_v4(flash_status='red'))
                    self.log("[DEBUG] USB-флешка НЕ обнаружена на коммутаторе", "debug")

        except Exception as e:
            self.log(f"[WARN] Не удалось получить подробности устройства: {e}", "warn")

    def show_connection_panel(self):
        """Показать панель статусов подключения"""
        self.connection_panel.pack(fill="x", padx=15, pady=(0, 12), before=self.info_frame)

    def hide_connection_panel(self):
        """Скрыть панель статусов подключения"""
        self.connection_panel.pack_forget()
    
    def show_progress_panel(self):
        """Показать панель прогресса (v3.0)"""
        self.progress_frame.pack(fill="x", padx=10, pady=(0, 10), after=self.info_frame)
        self.stage2_start_time = time.time()
        self.progress_var.set(0)
        self.progress_percent_label.config(text="0%")
        self.current_stage_var.set("Ожидание...")
        self.elapsed_time_var.set("0:00")
        self.remaining_time_var.set("~10-15 мин")
        
    def hide_progress_panel(self):
        """Скрыть панель прогресса"""
        self.progress_frame.pack_forget()
        
    def update_progress(self, stage, stage_name=""):
        """
        Обновить прогресс (v3.0)
        stage: номер текущего этапа (1-5)
        stage_name: название этапа
        """
        self.stage2_current_stage = stage
        percent = int((stage / self.stage2_total_stages) * 100)
        self.progress_var.set(percent)
        self.progress_percent_label.config(text=f"{percent}%")
        
        if stage_name:
            self.current_stage_var.set(f"{stage}/{self.stage2_total_stages} - {stage_name}")
        
        # Update elapsed time
        if self.stage2_start_time:
            elapsed = int(time.time() - self.stage2_start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            self.elapsed_time_var.set(f"{minutes}:{seconds:02d}")
            
            # Estimate remaining time
            if stage > 0:
                avg_time_per_stage = elapsed / stage
                remaining_stages = self.stage2_total_stages - stage
                estimated_remaining = int(avg_time_per_stage * remaining_stages)
                
                if estimated_remaining < 60:
                    self.remaining_time_var.set(f"~{estimated_remaining} сек")
                else:
                    est_minutes = estimated_remaining // 60
                    self.remaining_time_var.set(f"~{est_minutes} мин")
    
    def update_connection_status_v4(self, power_status=None, usb_status=None, com_status=None, flash_status=None):
        """
        Обновление Connection Status Panel v4.0 с визуальными индикаторами
        power_status, usb_status, com_status, flash_status: 'green', 'yellow', 'red', 'gray'
        """
        status_config = {
            'green': {'icon': '🟢', 'color': '#27ae60', 'text_color': '#27ae60'},
            'yellow': {'icon': '🟡', 'color': '#f39c12', 'text_color': '#f39c12'},
            'red': {'icon': '🔴', 'color': '#e74c3c', 'text_color': '#e74c3c'},
            'gray': {'icon': '⚪', 'color': '#95a5a6', 'text_color': '#95a5a6'}
        }

        # Обновление индикатора питания
        if power_status:
            config = status_config.get(power_status, status_config['gray'])
            self.power_icon.config(text=config['icon'], fg=config['color'])
            if power_status == 'green':
                self.power_label.config(text="Питание: Включено", fg=config['text_color'])
            elif power_status == 'yellow':
                self.power_label.config(text="Питание: Проверка...", fg=config['text_color'])
            elif power_status == 'red':
                self.power_label.config(text="Питание: Не обнаружено", fg=config['text_color'])
            else:
                self.power_label.config(text="Питание: Неизвестно", fg=config['text_color'])

        # Обновление индикатора RJ45-USB
        if usb_status:
            config = status_config.get(usb_status, status_config['gray'])
            self.usb_icon.config(text=config['icon'], fg=config['color'])
            if usb_status == 'green':
                self.usb_label.config(text="RJ45-USB: Подключен", fg=config['text_color'])
            elif usb_status == 'yellow':
                self.usb_label.config(text="RJ45-USB: Ожидание", fg=config['text_color'])
            elif usb_status == 'red':
                self.usb_label.config(text="RJ45-USB: Не найден", fg=config['text_color'])
            else:
                self.usb_label.config(text="RJ45-USB: Неизвестно", fg=config['text_color'])

        # Обновление индикатора COM-порта
        if com_status:
            config = status_config.get(com_status, status_config['gray'])
            self.com_icon.config(text=config['icon'], fg=config['color'])
            if com_status == 'green':
                port = self.com_var.get() if self.com_var.get() else "COM?"
                self.com_label.config(text=f"COM-порт: {port}", fg=config['text_color'])
            elif com_status == 'yellow':
                self.com_label.config(text="COM-порт: Сканирование...", fg=config['text_color'])
            elif com_status == 'red':
                self.com_label.config(text="COM-порт: Не доступен", fg=config['text_color'])
            else:
                self.com_label.config(text="COM-порт: Неизвестно", fg=config['text_color'])

        # Обновление индикатора флешки
        if flash_status:
            config = status_config.get(flash_status, status_config['gray'])
            self.flash_icon.config(text=config['icon'], fg=config['color'])
            if flash_status == 'green':
                self.flash_label.config(text="USB-флешка: Готова", fg=config['text_color'])
            elif flash_status == 'yellow':
                self.flash_label.config(text="USB-флешка: Проверка...", fg=config['text_color'])
            elif flash_status == 'red':
                self.flash_label.config(text="USB-флешка: Не найдена", fg=config['text_color'])
            else:
                self.flash_label.config(text="USB-флешка: Неизвестно", fg=config['text_color'])

        # Обновление общего статуса
        statuses = [power_status, usb_status, com_status, flash_status]
        green_count = sum(1 for s in statuses if s == 'green')
        red_count = sum(1 for s in statuses if s == 'red')
        yellow_count = sum(1 for s in statuses if s == 'yellow')

        if green_count == 4:
            self.overall_icon.config(text="🟢", fg='#27ae60')
            self.overall_label.config(text="ОБЩИЙ СТАТУС: ВСЁ ГОТОВО!", fg='#27ae60')
        elif red_count > 0:
            self.overall_icon.config(text="🔴", fg='#e74c3c')
            self.overall_label.config(text="ОБЩИЙ СТАТУС: ТРЕБУЕТСЯ ВНИМАНИЕ", fg='#e74c3c')
        elif yellow_count > 0:
            self.overall_icon.config(text="🟡", fg='#f39c12')
            self.overall_label.config(text="ОБЩИЙ СТАТУС: ПРОВЕРКА...", fg='#f39c12')
        else:
            self.overall_icon.config(text="⚪", fg='#95a5a6')
            self.overall_label.config(text="ОБЩИЙ СТАТУС: ОЖИДАНИЕ", fg='#95a5a6')
        self.overall_label.pack(side="left")

    def on_closing(self):
        """Handle window close event"""
        if self.running:
            if messagebox.askyesno("Выход", "Процесс еще выполняется. Вы уверены, что хотите выйти?"):
                self.stop_all()
                time.sleep(0.5)
                self.lock.release()
                self.root.destroy()
        else:
            self.lock.release()
            self.root.destroy()
    
    def _safe_close_serial(self):
        """Safely close serial connection for graceful shutdown"""
        if self.serial_ctrl:
            try:
                self.serial_ctrl.close()
            except Exception:
                pass

    @monitor_performance("stage1")
    def start_stage1(self):
        if self.running:
            messagebox.showwarning("Выполняется", "Процесс уже запущен")
            return
        if not messagebox.askokcancel(
            "Подтверждение", 
            "Вы собираетесь выполнить операции сброса конфигурации и перезагрузки.\n\n"
            "Это удалит текущую конфигурацию на устройстве.\n\n"
            "Убедитесь, что:\n"
            "• Вы подключены к правильному устройству\n"
            "• У вас есть резервная копия конфигурации\n"
            "• Устройство включено\n\n"
            "Продолжить?"
        ):
            return

        self.running = True
        self.start_button.config(state="disabled")
        self.stage2_button.config(state="disabled")
        self.stage3_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.status_var.set("Stage 1: Подключение и сброс...")
        
        self.update_tips("🔄 Stage 1: Выполняется сброс конфигурации и перезагрузка. Дождитесь завершения...")

        self.worker_thread = threading.Thread(target=self._do_stage1, daemon=True)
        self.worker_thread.start()

    def _do_stage1(self):
        try:
            self.log("=" * 80, "info")
            self.log("STAGE 1: ПОДКЛЮЧЕНИЕ И СБРОС КОНФИГУРАЦИИ", "info")
            self.log("=" * 80, "info")
            
            port = None
            if self.auto_var.get():
                port = auto_detect_cisco_port()
                self.log(f"Автопоиск COM-порта -> {port}", "debug")
            if not port:
                port = self.com_var.get().strip()
            if not port:
                self.log("❌ COM-порт не найден!", "err")
                messagebox.showerror("Ошибка", "USB-консольный кабель не обнаружен!\n\nПодключите кабель к ПК. Система автоматически обнаружит устройство в течение нескольких секунд.")
                self._finish_run()
                return
            
            self.log(f"✅ Найден COM-порт: {port}", "ok")
            
            self.serial_ctrl = SerialController(port, dry_run=DRY_RUN)
            try:
                self.serial_ctrl.open()
            except Exception as e:
                self.log(f"❌ Не удалось открыть порт {port}: {e}", "err")
                self._finish_run()
                return

            self.log(f"🔌 Подключено к {port}", "ok")
            
            self.log("⌛ Ожидание приглашения коммутатора (до 30 секунд)...", "info")
            found, out = self.serial_ctrl.expect([PROMPT_PRIV, PROMPT_USER, PROMPT_REDUCED], timeout=30)
            
            if found:
                self.log(f"✅ Найдено приглашение: {found}", "ok")
            else:
                self.log("⚠️ Приглашение не найдено за 30 секунд", "warn")
                self.log("🔄 Попытка повторного запроса...", "info")
                self.serial_ctrl.write("\r\nenable\r")
                time.sleep(1)
                found, out = self.serial_ctrl.expect([PROMPT_PRIV, PROMPT_USER], timeout=10)
            
            if not found or PROMPT_PRIV not in found:
                self.log("❌ Не удалось войти в привилегированный режим Switch#", "err")
                self._finish_run()
                return
            
            self.log("✅ Командная строка: Switch# (привилегированный режим)", "ok")

            # === Idempotent write erase ===
            # Note: Backup не создаётся, т.к. после reload устройство будет чистым
            self.log("🔍 Проверка startup-config для идемпотентности...", "info")
            self.serial_ctrl.write("show startup-config\r")
            time.sleep(2)
            startup_output = self.serial_ctrl.read_available()
            no_startup_markers = [
                "startup-config is not present",
                "No configuration present",
                "Can\'t find startup-config"
            ]
            need_erase = True
            if startup_output:
                lowered = startup_output.lower()
                if any(marker.lower() in lowered for marker in no_startup_markers):
                    need_erase = False
            if need_erase:
                self.log("⚙️ Выполняется write erase...", "info")
                self.serial_ctrl.flush_input()
                self.serial_ctrl.write("write erase\r")
                time.sleep(1)
                cont, buf = self.serial_ctrl.expect([
                    "Continue?", "[confirm]", "Proceed with reload?", "Delete filename"
                ], timeout=8)
                if cont:
                    self.log(f"✅ Найдено подтверждение: {cont}", "debug")
                    self.serial_ctrl.write("\r")
                    time.sleep(2)
                    response = self.serial_ctrl.read_available()
                    if response.strip():
                        self.log(f"Ответ устройства: {response.strip()}", "debug")
                else:
                    self.log("⚠️ Не получено подтверждение для write erase", "warn")
                self.log("⌛ Ожидаем завершения стирания NVRAM...", "info")
                time.sleep(3)
            else:
                self.log("ℹ️ startup-config отсутствует — пропускаем write erase", "info")

            # === Idempotent vlan.dat delete ===
            self.log("🔍 Проверка наличия flash:/vlan.dat...", "info")
            self.serial_ctrl.write("dir flash:\r")
            time.sleep(2)
            dir_output = self.serial_ctrl.read_available()
            if "vlan.dat" in dir_output:
                self.log("🗑️ Удаление vlan.dat...", "info")
                self.serial_ctrl.flush_input()
                self.serial_ctrl.write("delete flash:/vlan.dat\r")
                time.sleep(0.5)
                got, out = self.serial_ctrl.expect([
                    "Delete filename", "Delete flash:/vlan.dat?", "[confirm]"
                ], timeout=4)
                if got:
                    self.serial_ctrl.write("\r")
                    self.log("✅ Подтверждение удаления vlan.dat отправлено", "debug")
                    time.sleep(1)
                response = self.serial_ctrl.read_available()
                if response and any(word in response for word in ("Error", "Invalid")):
                    self.log("ℹ️ vlan.dat не найден (уже отсутствует)", "info")
                else:
                    self.log("✅ vlan.dat удален", "ok")
            else:
                self.log("ℹ️ vlan.dat отсутствует — пропускаем удаление", "info")

            # === Reload sequence ===
            self.log("🔄 Выполняется reload...", "info")
            self.serial_ctrl.flush_input()
            self.serial_ctrl.write("reload\r")
            time.sleep(1)

            if DRY_RUN:
                self.log("[DRY-RUN] Перезагрузка не выполнялась", "debug")
                boot_detected = True
            else:
                reload_confirmed = False
                for attempt in range(3):
                    got, out = self.serial_ctrl.expect([
                        "Proceed with reload?", "[confirm]", "System configuration"
                    ], timeout=RELOAD_TIMEOUT)
                    if got:
                        self.log(f"✅ Найдено подтверждение reload: {got}", "ok")
                        self.serial_ctrl.write("\r")
                        time.sleep(SHORT_WAIT)
                        reload_confirmed = True
                        break
                    self.serial_ctrl.write("\r")
                    time.sleep(SHORT_WAIT)

                if reload_confirmed:
                    self.log("✅ Подтверждение reload отправлено", "ok")
                else:
                    self.log("⚠️ Не получено подтверждение reload за 3 попытки", "warn")
                    self.log("🔄 Попытка принудительной перезагрузки: reload /noverify", "info")
                    self.serial_ctrl.write("reload /noverify\r")
                    time.sleep(1)
                    self.serial_ctrl.write("\r")
                    time.sleep(1)

                self.log("⌛ Ожидание перезагрузки устройства (до 5 минут)...", "info")
                self.log("📝 Загрузочные сообщения будут отображены ниже:", "info")
                self.serial_ctrl.close()

                boot_detected = False
                detect_deadline = time.time() + 300
                recent_boot_lines: List[str] = []

                while time.time() < detect_deadline and self.running:
                    try:
                        self.serial_ctrl.open()
                        data = self.serial_ctrl.read_available()
                        if data:
                            for line in data.strip().split('\n'):
                                line_clean = line.strip()
                                if not line_clean or len(line_clean) > 200:
                                    continue
                                if line_clean in recent_boot_lines:
                                    continue
                                if len(set(line_clean.replace(' ', ''))) <= 3:
                                    continue
                                skip_patterns = [
                                    'Using driver version', 'please contact', 'require further assistance',
                                    'mifs fsck took', 'sending email to', 'export@cisco.com', 'ct us by',
                                    '170 West Tasman', 'BeginortASIC', 'Port Loopback'
                                ]
                                if any(pattern in line_clean for pattern in skip_patterns):
                                    continue
                                self.log(f"  BOOT: {line_clean}", "debug", also_console=False)
                                recent_boot_lines.append(line_clean)
                                if len(recent_boot_lines) > 10:
                                    recent_boot_lines.pop(0)
                            if any(marker in data for marker in (
                                "Initializing Flash", "Loading", "System restarted",
                                "Press RETURN to get started", "Cisco IOS Software"
                            )):
                                boot_detected = True
                                self.log("✅ Обнаружены загрузочные сообщения", "ok")
                        self.serial_ctrl.close()
                    except Exception:
                        pass
                    time.sleep(2)

                if not boot_detected:
                    self.log("⚠️ Загрузочные сообщения не обнаружены, продолжаем ожидание...", "warn")

            # === Final prompt wait ===
            prompt_found = False
            if DRY_RUN:
                prompt_found = True
            else:
                deadline = time.time() + 300
                attempt = 0
                while time.time() < deadline and self.running:
                    attempt += 1
                    try:
                        self.serial_ctrl.open()
                        self.serial_ctrl.write("\r\n")
                        time.sleep(0.3)
                        self.serial_ctrl.write("\r\n")
                        
                        # Check for config dialog first
                        # Config dialog appears after write erase + reload on clean device
                        found, buf = self.serial_ctrl.expect([PROMPT_USER, PROMPT_PRIV], timeout=15)
                        
                        # Check if buffer contains config dialog prompt
                        if buf and ("Would you like to enter" in buf or "initial configuration dialog" in buf):
                            self.log("📋 Обнаружен config dialog, пропускаем (no)...", "info")
                            self.serial_ctrl.write("no\r")
                            time.sleep(2)
                            # После "no" должен появиться Switch>
                            found, buf = self.serial_ctrl.expect([PROMPT_USER, PROMPT_PRIV], timeout=10)
                        
                        if found:
                            prompt_found = True
                            self.log(f"✅ Появилось приглашение: {found}", "ok")
                            if found == PROMPT_USER:
                                self.log("🔐 Входим в привилегированный режим (enable)...", "info")
                                self.serial_ctrl.write("enable\r")
                                time.sleep(2)
                                found, buf = self.serial_ctrl.expect([PROMPT_PRIV], timeout=ENABLE_TIMEOUT)
                            break
                        if attempt % 5 == 0:
                            self.log(f"⏳ Попытка {attempt}: приглашение не найдено, продолжаем ждать...", "debug")
                    except Exception as exc:
                        self.log(f"⚠️ Ошибка при ожидании приглашения (попытка {attempt}): {exc}", "debug")
                        try:
                            self.serial_ctrl.close()
                        except Exception:
                            pass
                    time.sleep(MEDIUM_WAIT)

            if not prompt_found:
                self.log("❌ Не удалось дождаться приглашения Switch>", "err")
                self.log("💡 Попробуйте вручную подключиться к коммутатору через терминал", "info")
                self._finish_run()
                return

            self.log("=" * 80, "ok")
            self.log("✅ STAGE 1 ЗАВЕРШЕНА УСПЕШНО", "ok")
            self.log("=" * 80, "ok")
            self.log("", "info")
            self.log("📌 Следующие шаги:", "info")
            self.log("  1. Вставьте USB-флешку с файлом прошивки", "info")
            self.log("  2. Нажмите кнопку '2) Проверка USB и Запуск прошивки'", "info")
            self.log("", "info")
            
            # ВАЖНО: Сбрасываем running ПЕРЕД активацией Stage 2
            self.running = False
            
            # Обновление UI должно быть в главном потоке
            def enable_stage2():
                self.stage2_button.config(state="normal")
                self.stop_button.config(state="disabled")
                self.status_var.set("✅ Stage 1 завершена. Готов к Stage 2")
                self.update_tips("✅ Stage 1 завершена! Вставьте USB-флешку с прошивкой и нажмите Stage 2")
            
            self.run_on_main(enable_stage2)
        except Exception as e:
            self.log("Ошибка в Stage 1: " + str(e), "err")
            traceback.print_exc()
            self._finish_run()

    @monitor_performance("stage2")
    def start_stage2(self):
        if self.running:
            messagebox.showwarning("Выполняется", "Дождитесь завершения текущего этапа перед запуском Stage 2.")
            return
        if self.stage2_button['state'] == 'disabled':
            return

        if not messagebox.askyesno(
            "USB-флешка",
            "USB-флешка вставлена?\n\n"
            "Процесс займет 20-40 минут.\n\n"
            "Продолжить?"
        ):
            self.log("❌ Пользователь отменил Stage 2", "warn")
            return

        self.running = True
        self.start_button.config(state="disabled")
        self.stage2_button.config(state="disabled")
        self.stage3_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.status_var.set("Stage 2: проверка USB и запуск прошивки")
        self.update_tips("🔄 Stage 2: Установка прошивки. Процесс займёт 20-40 минут. НЕ ВЫКЛЮЧАЙТЕ коммутатор!")

        self.worker_thread = threading.Thread(target=self._do_stage2, daemon=True)
        self.worker_thread.start()

    def _do_stage2(self):
        def abort_stage2(msg: str, level: str = "err") -> None:
            if msg:
                self.log(msg, level)
            self.run_on_main(self.hide_progress_panel)
            try:
                if self.serial_ctrl:
                    self.serial_ctrl.close()
            except Exception:
                pass
            self.running = False
            self._finish_run(success=False)

        try:
            fw_file = DEFAULT_FIRMWARE_FILENAME

            self.log("=" * 80, "info")
            self.log("STAGE 2: ПРОВЕРКА USB И ЗАПУСК ПРОШИВКИ", "info")
            self.log("=" * 80, "info")

            self.run_on_main(self.show_progress_panel)
            self.log("📌 ВАЖНО: Необходима USB-флешка с образом прошивки", "info")
            self.log(f"   Файл: {fw_file}", "info")

            if not self.serial_ctrl:
                abort_stage2("❌ Serial контроллер недоступен")
                return

            # Сбрасываем состояние стадий установки
            for key in self.install_stages:
                self.install_stages[key] = False

            try:
                self.serial_ctrl.open()
            except Exception as exc:
                abort_stage2(f"❌ Не удалось открыть serial-порт: {exc}")
                return

            self.serial_ctrl.write("\r")
            time.sleep(1)
            prompt_data = self.serial_ctrl.read_available()

            if PROMPT_PRIV not in prompt_data:
                found, _ = self.serial_ctrl.expect([PROMPT_PRIV, PROMPT_USER], timeout=15)
                if not found:
                    abort_stage2("❌ Не удалось получить приглашение Switch#")
                    return
                if found == PROMPT_USER:
                    self.log("⚠️ Обнаружен режим Switch> — выполняем enable", "warn")
                    self.serial_ctrl.write("enable\r")
                    time.sleep(2)
                    found, _ = self.serial_ctrl.expect([PROMPT_PRIV], timeout=ENABLE_TIMEOUT)
                    if not found:
                        abort_stage2("❌ Не удалось войти в привилегированный режим")
                        return
                    self.log("✅ Успешно вошли в привилегированный режим Switch#", "ok")
            else:
                self.log("✅ Уже в привилегированном режиме Switch#", "ok")

            # Flash space check (informational only - archive download-sw /overwrite manages space)
            self.log("📊 Проверка flash (информационно)...", "info")
            self.serial_ctrl.write("show flash:\r")
            time.sleep(2)
            flash_output = self.serial_ctrl.read_available()
            free_bytes, total_bytes = parse_free_space(flash_output)
            if free_bytes and total_bytes:
                free_mb = free_bytes / (1024 * 1024)
                total_mb = total_bytes / (1024 * 1024)
                self.log(f"  Свободно: {free_mb:.1f} MB из {total_mb:.1f} MB", "info")
                self.log("ℹ️ Команда archive download-sw /overwrite автоматически управляет памятью", "info")
            else:
                self.log("⚠️ Не удалось определить свободное место (не критично)", "warn")

            self.log("🔍 Поиск файла прошивки на usbflash0:", "info")
            
            if DRY_RUN:
                self.log(f"[DRY-RUN] Симуляция: файл {fw_file} найден на USB", "debug")
                self.log(f"✅ Файл {fw_file} найден на USB", "ok")
            else:
                self.serial_ctrl.write("dir usbflash0:\r")
                time.sleep(2)
                usb_dir_output = self.serial_ctrl.read_available()
                if fw_file not in usb_dir_output:
                    abort_stage2(f"❌ Файл {fw_file} не найден на USB")
                    return
                self.log(f"✅ Файл {fw_file} найден на USB", "ok")

            # MD5 проверка отключена (можно включить при необходимости)
            expected_md5 = None
            self.log("ℹ️ MD5 проверка пропущена (можно включить в настройках)", "debug")

            if DRY_RUN:
                self.log("[DRY-RUN] Проверка MD5 пропущена", "debug")
            else:
                self.log("🔍 Проверяем MD5 файла на usbflash0:", "info")
                self.serial_ctrl.write(f"verify /md5 usbflash0:/{fw_file}\r")
                md5_output = ""
                md5_deadline = time.time() + 180
                md5_verified = False
                while time.time() < md5_deadline and self.running:
                    chunk = self.serial_ctrl.read_available()
                    if chunk:
                        md5_output += chunk
                        match = re.search(r"= ([0-9a-fA-F]{32})", md5_output)
                        if match:
                            found_md5 = match.group(1).lower()
                            self.log(f"✅ MD5: {found_md5}", "ok")
                            if expected_md5 and found_md5 != expected_md5:
                                abort_stage2("❌ MD5 не совпадает с ожидаемым значением")
                                return
                            if expected_md5:
                                self.log("✅ MD5 совпадает с ожидаемым", "ok")
                            md5_verified = True
                            break
                    time.sleep(1)

                if expected_md5 and not md5_verified:
                    abort_stage2("❌ Не удалось подтвердить MD5 — прекращаем установку")
                    return
                if not md5_verified:
                    self.log("⚠️ Не удалось получить MD5 (verify /md5)", "warn")

            if DRY_RUN:
                self.log("[DRY-RUN] Симуляция archive download-sw", "info")
                for idx, label in enumerate([
                    "Examining", "Extracting", "Installing", "Deleting", "Signature Verify"
                ], start=1):
                    self.run_on_main(self.update_progress, idx, label)
                    time.sleep(0.1)
                self.install_stages['examining'] = True
                self.install_stages['extracting'] = True
                self.install_stages['installing'] = True
                self.install_stages['deleting_old'] = True
                self.install_stages['signature_verified'] = True
                self.install_stages['reload_requested'] = True
                self.run_on_main(self.hide_progress_panel)

                def ui_dry_run():
                    self.stop_button.config(state="disabled")
                    self.stage3_button.config(state="normal")
                    self.status_var.set("[DRY-RUN] Stage 2 завершена")

                self.run_on_main(ui_dry_run)
                self.update_tips("[DRY-RUN] Stage 2 завершена. Перейдите к Stage 3 для аудита.")
                self.log("📊 [PERF] Stage 2 завершена (DRY-RUN)", "debug")
                self.running = False
                return

            self.log("🚀 Запуск archive download-sw ...", "info")
            self.serial_ctrl.write(f"archive download-sw /overwrite /reload usbflash0:/{fw_file}\r")

            stage_markers = {
                "examining": False,
                "extracting": False,
                "installing": False,
                "deleting": False,
                "signature": False,
                "reload": False
            }

            download_complete = False
            error_detected = False
            buffer = ""
            archive_deadline = time.time() + 2400  # 40 минут
            last_data_time = time.time()
            last_progress_log = time.time()
            start_time = time.time()
            silence_after_extract = False
            recent_install_lines: List[str] = []

            while time.time() < archive_deadline and self.running:
                chunk = self.serial_ctrl.read_available()
                if chunk:
                    buffer += chunk
                    last_data_time = time.time()
                    for raw_line in chunk.splitlines():
                        line = raw_line.strip()
                        if not line:
                            continue

                        lowered = line.lower()
                        if "examining" in lowered and not stage_markers["examining"]:
                            stage_markers["examining"] = True
                            self.install_stages['examining'] = True
                            self.run_on_main(self.update_progress, 1, "Examining")
                        elif "extracting" in lowered and not stage_markers["extracting"]:
                            stage_markers["extracting"] = True
                            self.install_stages['extracting'] = True
                            self.run_on_main(self.update_progress, 2, "Extracting")
                        elif "installing" in lowered and not stage_markers["installing"]:
                            stage_markers["installing"] = True
                            self.install_stages['installing'] = True
                            self.run_on_main(self.update_progress, 3, "Installing")
                            self.log("📌 ВАЖНО: Образ копируется с USB-флешки на flash-память", "warn")
                            self.log("⚠️ После завершения копирования ДОСТАНЬТЕ USB-ФЛЕШКУ!", "warn")
                            silence_after_extract = True
                        elif "deleting" in lowered and not stage_markers["deleting"]:
                            stage_markers["deleting"] = True
                            self.install_stages['deleting_old'] = True
                            self.run_on_main(self.update_progress, 4, "Deleting")
                        elif "signature" in lowered and not stage_markers["signature"]:
                            stage_markers["signature"] = True
                            self.install_stages['signature_verified'] = True
                            self.run_on_main(self.update_progress, 5, "Signature Verify")
                        elif "reload" in lowered:
                            stage_markers["reload"] = True
                            self.install_stages['reload_requested'] = True

                        if len(line) > 200 or line in recent_install_lines:
                            continue

                        unique_chars = set(line.replace(' ', ''))
                        if len(unique_chars) <= 3:
                            continue

                        skip_patterns = (
                            'Using driver version', 'bytes available', 'please contact',
                            'require further assistance', 'mifs fsck took', 'hpaa_port_bitm',
                            'export@cisco.com', '170 West Tasman', 'Port Loopback'
                        )
                        if any(pattern.lower() in lowered for pattern in skip_patterns):
                            continue

                        self.log(f"  INSTALL: {line}", "debug", also_console=False)
                        recent_install_lines.append(line)
                        if len(recent_install_lines) > 10:
                            recent_install_lines.pop(0)

                    lower_buffer = buffer.lower()
                    if any(marker in lower_buffer for marker in (
                        "new software image installed",
                        "requested system reload",
                        "reload of the system",
                        "all software images installed"
                    )):
                        download_complete = True
                        break

                    if any(err in lower_buffer for err in (
                        " error", "failed", "insufficient", "malformed", "checksum", "permission denied"
                    )):
                        error_detected = True
                        break
                else:
                    if time.time() - last_data_time > 60:
                        self.log("⏳ Нет вывода более 60 секунд. Ожидаем...", "warn")
                        last_data_time = time.time()

                if silence_after_extract and self.install_stages['installing']:
                    if time.time() - last_data_time > 90:
                        self.log("📊 Обнаружено завершение установки (90 сек без вывода)", "ok")
                        download_complete = True
                        break

                if time.time() - last_progress_log > 120:
                    elapsed = int(time.time() - start_time)
                    mins, secs = divmod(elapsed, 60)
                    self.log(f"⏱️ Прошло времени: {mins} мин {secs:02d} сек", "info")
                    last_progress_log = time.time()

                time.sleep(1)

            if error_detected:
                abort_stage2("❌ Обнаружена ошибка в процессе установки")
                return

            if not download_complete:
                abort_stage2("⏰ Таймаут: archive download-sw не завершился вовремя", level="warn")
                return

            self.log("✅ Установка образа завершена. Ожидаем появление приглашения...", "ok")

            prompt_found = False
            if not DRY_RUN:
                prompt_deadline = time.time() + 900  # до 15 минут на перезагрузку
                attempt = 0
                while time.time() < prompt_deadline and self.running:
                    attempt += 1
                    try:
                        self.serial_ctrl.open()
                        self.serial_ctrl.write("\r\n")
                        time.sleep(0.5)
                        self.serial_ctrl.write("\r\n")
                        found, _ = self.serial_ctrl.expect([PROMPT_PRIV, PROMPT_USER], timeout=15)
                        if found:
                            prompt_found = True
                            self.log(f"✅ Получено приглашение: {found}", "ok")
                            if found == PROMPT_USER:
                                self.log("🔐 Выполняем enable для перехода в Switch#", "info")
                                self.serial_ctrl.write("enable\r")
                                time.sleep(2)
                                found, _ = self.serial_ctrl.expect([PROMPT_PRIV], timeout=ENABLE_TIMEOUT)
                                if not found:
                                    abort_stage2("❌ Не удалось войти в привилегированный режим после перезагрузки")
                                    return
                            break
                    except Exception as exc:
                        self.log(f"⚠️ Ошибка ожидания приглашения (попытка {attempt}): {exc}", "debug")
                    finally:
                        try:
                            self.serial_ctrl.close()
                        except Exception:
                            pass

                    if attempt % 5 == 0:
                        self.log(f"⏳ Попытка {attempt}: ожидаем приглашение...", "info")
                    time.sleep(MEDIUM_WAIT)

                if not prompt_found:
                    abort_stage2("❌ Не удалось получить приглашение после перезагрузки")
                    return

            try:
                if self.serial_ctrl:
                    self.serial_ctrl.close()
            except Exception:
                pass

            self.log("✅ Stage 2 завершена: устройство вернулось в Switch#", "ok")
            self.log("✅ Обновление ПО завершено", "ok")

            def ui_success():
                self.hide_progress_panel()
                self.stop_button.config(state="disabled")
                self.stage3_button.config(state="normal")
                self.status_var.set("✅ Stage 2 завершена. Ожидается перезагрузка")

            self.run_on_main(ui_success)
            self.update_tips("✅ Stage 2 завершена! После загрузки устройства выполните Stage 3.")

            self.log("📋 Статус этапов установки:", "info")
            self.log(f"  • Examining: {'✓' if self.install_stages['examining'] else '✗'}", "info")
            self.log(f"  • Extracting: {'✓' if self.install_stages['extracting'] else '✗'}", "info")
            self.log(f"  • Installing: {'✓' if self.install_stages['installing'] else '✗'}", "info")
            self.log(f"  • Deleting old: {'✓' if self.install_stages['deleting_old'] else '✗'}", "info")
            self.log(f"  • Signature verified: {'✓' if self.install_stages['signature_verified'] else '✗'}", "info")
            self.log(f"  • Reload requested: {'✓' if self.install_stages['reload_requested'] else '✗'}", "info")

            self.running = False

        except Exception as err:
            traceback.print_exc()
            abort_stage2(f"❌ Ошибка Stage 2: {err}")

    @monitor_performance("stage3")
    def start_stage3(self):
        # Stage 3 can run independently - no disabled check needed
        
        if self.running:
            messagebox.showwarning("Выполняется", "Дождитесь завершения текущего этапа перед запуском Stage 3.")
            return

        self.running = True
        self.stage3_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.status_var.set("Stage 3: финальная верификация...")

        self.update_tips("🔄 Stage 3: Проверка установленной прошивки и создание отчёта. Последний этап!")

        self.worker_thread = threading.Thread(target=self._do_stage3, daemon=True)
        self.worker_thread.start()

    def _do_stage3(self):
        def abort_stage3(message: str, level: str = "err") -> None:
            if message:
                self.log(message, level)
            self._finish_run()

        try:
            self.log("=" * 80, "info")
            self.log("STAGE 3: ФИНАЛЬНАЯ ВЕРИФИКАЦИЯ", "info")
            self.log("=" * 80, "info")

            if DRY_RUN:
                self.log("[DRY-RUN] Stage 3: симуляция финальной верификации", "info")

                simulated_info = {
                    "version": "DRY-RUN-IMAGE",
                    "image": "flash:/dry-run.bin",
                    "model": "WS-C2960X-48FPD-L"
                }
                simulated_verification = {
                    'show_version': "Cisco IOS Software, DRY-RUN Version\nSystem image file is \"flash:/dry-run.bin\"",
                    'show_boot': "BOOT variable = flash:/dry-run.bin",
                    'dir_flash': (
                        "Directory of flash:/\n"
                        "1  -rw-        123456789  dry-run.bin\n"
                        "2  -rw-          204800  config.text\n"
                        "255 blocks total (128 blocks free)"
                    ),
                    'audit_results': []
                }

                for command, title, _ in AUDIT_COMMANDS:
                    self.log(f"  ↳ [DRY-RUN] {command}", "info")
                    simulated_verification['audit_results'].append({
                        "command": command,
                        "title": title,
                        "output": "[DRY-RUN] Команда не выполнялась"
                    })

                self.log("📝 Генерация отчета (dry-run)...", "info")
                self._generate_install_report(simulated_verification, simulated_info, free_mb=128.0)
                self.log(f"✅ Отчет сохранен: {self.report_path}", "ok")
                self.open_report_btn.config(state="normal")

                self.log("✅ [DRY-RUN] Финальная верификация завершена", "ok")
                self.log("📊 [PERF] Stage 3 завершена (DRY-RUN)", "debug")
                self.status_var.set("[DRY-RUN] Stage 3 завершена")
                self.update_tips("[DRY-RUN] Stage 3 завершена. Отчет создан для проверки сценария.")
                self._finish_run(success=True)
                return

            if not self.serial_ctrl or not self.serial_ctrl.ser or not self.serial_ctrl.ser.is_open:
                self.log("⚠️ Serial порт закрыт, попытка переподключения...", "warn")
                port = self.com_var.get().strip()
                if not port and self.auto_var.get():
                    port = auto_detect_cisco_port()
                if not port:
                    abort_stage3("❌ Не удалось определить COM-порт")
                    return

                self.serial_ctrl = SerialController(port, dry_run=DRY_RUN)
                try:
                    self.serial_ctrl.open()
                    self.log(f"✅ Переподключено к {port}", "ok")
                except Exception as exc:
                    abort_stage3(f"❌ Ошибка подключения: {exc}")
                    return

            self.log("⌛ Ожидание приглашения устройства...", "info")
            self.serial_ctrl.write("\r")
            time.sleep(1)
            found, buf = self.serial_ctrl.expect([PROMPT_USER, PROMPT_PRIV], timeout=10)

            if not found:
                self.log("💡 Убедитесь, что устройство завершило загрузку", "info")
                abort_stage3("❌ Не получено приглашение устройства")
                return

            if found == PROMPT_USER:
                self.log("🔐 Входим в привилегированный режим (enable)...", "info")
                self.serial_ctrl.write("enable\r")
                time.sleep(2)
                found, buf = self.serial_ctrl.expect([PROMPT_PRIV], timeout=ENABLE_TIMEOUT)
                if not found:
                    abort_stage3("❌ Не удалось войти в привилегированный режим")
                    return

            self.log("✅ Подключено в привилегированном режиме", "ok")
            self.log("", "info")

            self.serial_ctrl.write("terminal length 0\r")
            time.sleep(0.5)
            self.serial_ctrl.read_available()

            verification_data: Dict[str, Any] = {}

            self.log("📊 Выполняется: show version", "info")
            self.serial_ctrl.flush_input()
            self.serial_ctrl.write("show version\r")
            time.sleep(3)
            version_output = self.serial_ctrl.read_available()
            verification_data['show_version'] = version_output

            version_info = parse_version_info(version_output)
            if version_info:
                self.log(f"  ✓ Версия ПО: {version_info.get('version', 'N/A')}", "ok")
                self.log(f"  ✓ Образ системы: {version_info.get('image', 'N/A')}", "ok")
                if 'model' in version_info:
                    self.log(f"  ✓ Модель: {version_info['model']}", "ok")

            self.log("", "info")
            self.log("📊 Выполняется: show boot", "info")
            self.serial_ctrl.flush_input()
            self.serial_ctrl.write("show boot\r")
            time.sleep(2)
            boot_output = self.serial_ctrl.read_available()
            verification_data['show_boot'] = boot_output

            boot_match = re.search(r'BOOT\s+variable\s*=\s*([^\r\n]+)', boot_output)
            if boot_match:
                boot_var = boot_match.group(1).strip()
                self.log(f"  ✓ BOOT variable: {boot_var}", "ok")

            self.log("", "info")
            self.log("📊 Выполняется: dir flash:", "info")
            self.serial_ctrl.flush_input()
            self.serial_ctrl.write("dir flash:\r")
            time.sleep(2)
            dir_output = self.serial_ctrl.read_available()
            verification_data['dir_flash'] = dir_output

            free_mb = None
            free_bytes, total_bytes = parse_free_space(dir_output)
            if free_bytes and total_bytes:
                free_mb = free_bytes / (1024 * 1024)
                total_mb = total_bytes / (1024 * 1024)
                used_mb = total_mb - free_mb
                self.log(f"  ✓ Свободно: {free_mb:.1f} MB из {total_mb:.1f} MB", "ok")
                self.log(f"  ✓ Использовано: {used_mb:.1f} MB", "ok")

            audit_results = []
            self.log("", "info")
            self.log("📋 Выполняются команды аудита...", "info")
            for command, title, wait_time in AUDIT_COMMANDS:
                self.log(f"  ↳ {command}", "info")
                output = self._exec_show_command(command, wait=wait_time).strip()
                if output:
                    lines_count = len(output.splitlines())
                    self.log(f"     ✓ Получено {lines_count} строк", "debug")
                else:
                    self.log("     ⚠️ Пустой ответ или превышен таймаут", "warn")
                audit_results.append({
                    "command": command,
                    "title": title,
                    "output": output
                })

            verification_data['audit_results'] = audit_results

            self.log("", "info")
            self.log("📝 Генерация отчета установки...", "info")
            self._generate_install_report(verification_data, version_info, free_mb)
            self.log(f"✅ Отчет сохранен: {self.report_path}", "ok")
            self.open_report_btn.config(state="normal")

            self.log("", "ok")
            self.log("=" * 80, "ok")
            self.log("✅ ФИНАЛЬНАЯ ВЕРИФИКАЦИЯ ЗАВЕРШЕНА", "ok")
            self.log("=" * 80, "ok")
            self.log("", "info")
            self.log("📋 Резюме:", "info")
            self.log(f"  • Версия ПО: {version_info.get('version', 'N/A') if version_info else 'N/A'}", "info")
            self.log(f"  • Образ: {version_info.get('image', 'N/A') if version_info else 'N/A'}", "info")
            self.log(f"  • Свободное место: {free_mb:.1f} MB" if free_mb else "  • Свободное место: N/A", "info")
            self.log(f"  • Команды аудита: {len(audit_results)}", "info")
            self.log(f"  • Отчет: {self.report_path}", "info")
            self.log("", "info")
            self.log("✅ Все операции завершены успешно!", "ok")
            self.log("📂 Откройте отчет для полной информации", "info")

            self.status_var.set("✅ Все этапы завершены")
            self._finish_run(success=True)

        except Exception as exc:
            traceback.print_exc()
            abort_stage3(f"❌ Ошибка в Stage 3: {exc}")

    def _generate_install_report(self, verification_data, version_info, free_mb=None):
        """Генерация финального отчета об установке"""
        with open(self.report_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("CISCO CATALYST 2960-X - INSTALLATION REPORT\n")
            f.write("=" * 80 + "\n")
            f.write(f"\nGenerated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Log file: {self.log_path}\n")
            f.write("\n")
            
            f.write("-" * 80 + "\n")
            f.write("SYSTEM INFORMATION\n")
            f.write("-" * 80 + "\n")
            if version_info:
                f.write(f"Software Version: {version_info.get('version', 'N/A')}\n")
                f.write(f"System Image: {version_info.get('image', 'N/A')}\n")
                f.write(f"Model: {version_info.get('model', 'N/A')}\n")
            if free_mb is not None:
                f.write(f"Flash Free Space: {free_mb:.1f} MB\n")
            f.write("\n")
            
            f.write("-" * 80 + "\n")
            f.write("INSTALLATION STAGES\n")
            f.write("-" * 80 + "\n")
            for stage, completed in self.install_stages.items():
                status = "✓ COMPLETED" if completed else "✗ NOT COMPLETED"
                f.write(f"{stage.replace('_', ' ').title()}: {status}\n")
            f.write("\n")
            
            f.write("-" * 80 + "\n")
            f.write("SHOW VERSION OUTPUT\n")
            f.write("-" * 80 + "\n")
            f.write(verification_data.get('show_version', 'N/A') + "\n\n")
            
            f.write("-" * 80 + "\n")
            f.write("SHOW BOOT OUTPUT\n")
            f.write("-" * 80 + "\n")
            f.write(verification_data.get('show_boot', 'N/A') + "\n\n")
            
            f.write("-" * 80 + "\n")
            f.write("DIR FLASH: OUTPUT\n")
            f.write("-" * 80 + "\n")
            f.write(verification_data.get('dir_flash', 'N/A') + "\n\n")

            audit_results = verification_data.get('audit_results', [])
            if audit_results:
                f.write("-" * 80 + "\n")
                f.write("AUDIT COMMANDS OUTPUT\n")
                f.write("-" * 80 + "\n")
                for idx, entry in enumerate(audit_results, 1):
                    command = entry.get('command', 'N/A')
                    title = entry.get('title') or command.upper()
                    output = entry.get('output', '').strip() or "NO OUTPUT"
                    f.write(f"[{idx}] {title}\n")
                    f.write(f"Command: {command}\n")
                    f.write(output + "\n\n")
            
            f.write("=" * 80 + "\n")
            f.write("END OF REPORT\n")
            f.write("=" * 80 + "\n")

    def stop_all(self):
        if messagebox.askyesno(
            "Остановка",
            "Вы действительно хотите остановить процесс? Это не обратит уже выполненные операции."
        ):
            self.running = False
            if self.serial_ctrl:
                try:
                    self.serial_ctrl.stop()
                except Exception:
                    pass
                try:
                    self.serial_ctrl.close()
                except Exception:
                    pass
            self._finish_run()

    def _finish_run(self, success=False, keep_stage_buttons=False):
        self.running = False

        if self.serial_ctrl:
            try:
                self.serial_ctrl.close()
            except Exception:
                pass

        def update_ui():
            self.start_button.config(state="normal")
            
            # Не сбрасываем состояние Stage кнопок если keep_stage_buttons=True
            if not keep_stage_buttons:
                self.stage2_button.config(state="disabled")
                self.stage3_button.config(state="disabled")
            
            self.stop_button.config(state="disabled")

            if success:
                self.status_var.set("Успешно завершено")
                self.update_tips("🎉 ВСЕ ЭТАПЫ ЗАВЕРШЕНЫ! Прошивка установлена и проверена. Можете отключить коммутатор.")
            else:
                self.status_var.set("Остановлено/Завершено")

        if success:
            self.log("Процесс завершён успешно.", "ok")
        else:
            self.log("Процесс остановлен/завершён.", "warn")

        self.run_on_main(update_ui)

def main():
    cleanup_on_startup()
    
    root = tk.Tk()
    app = App(root)
    root.mainloop()
if __name__ == "__main__":
    main()
