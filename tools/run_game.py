#!/usr/bin/env python3
"""Validated launchers for the pinned development FPS; no system settings changed."""
import argparse
from functools import lru_cache
import ipaddress
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENGINE_VERSION = '4.7.2'


@lru_cache(maxsize=1)
def engine():
    override = os.environ.get('GODOT_BIN')
    pinned = ROOT / f'results/toolchain/godot-{ENGINE_VERSION}/godot'
    candidate = (shutil.which(override) or override) if override else (
        str(pinned) if pinned.is_file() else shutil.which('godot') or shutil.which('godot4'))
    if not candidate:
        raise SystemExit('Falta Godot. Ejecuta: python3 tools/prepare_godot.py')
    candidate = str(Path(candidate).resolve())
    try:
        check = subprocess.run([candidate, '--version'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f'No se pudo ejecutar Godot: {error}') from error
    if check.returncode or not check.stdout.strip().startswith(ENGINE_VERSION+'.stable.'):
        raise SystemExit(f'Esta entrega requiere Godot {ENGINE_VERSION} estable. Ejecuta tools/prepare_godot.py o ajusta GODOT_BIN.')
    return candidate


def port_number(value):
    number = int(value)
    if not 1024 <= number <= 65535:
        raise argparse.ArgumentTypeError('puerto entre 1024 y 65535')
    return number


def ip_address(value):
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError as error:
        raise argparse.ArgumentTypeError('se requiere una dirección IPv4') from error


def player_name(value):
    if not value.isidentifier() or len(value) > 24:
        raise argparse.ArgumentTypeError('nombre de 1–24 caracteres, identificador sin espacios')
    return value


def parse_args(args):
    parser = argparse.ArgumentParser(description='Middleware Arena v0.1.0 — FPS LAN experimental sin admisión TPM integrada')
    parser.add_argument('--version', action='version', version='Middleware Arena '+(ROOT/'VERSION').read_text().strip())
    parser.add_argument('--server', action='store_true', help='servidor dedicado headless')
    parser.add_argument('--development', action='store_true', help='perfil sin atestación; obligatorio para el servidor actual')
    parser.add_argument('--join', type=ip_address, help='IPv4 del servidor LAN')
    parser.add_argument('--port', type=port_number, default=7777)
    parser.add_argument('--name', type=player_name, default='Player')
    parser.add_argument('--config', type=Path, help='configuración de servidor; por defecto game/server.cfg')
    parser.add_argument('--lab', action='store_true', help='simulador de aim interno en modo desarrollo')
    parser.add_argument('--snap-cycle', action='store_true', help='adquisición repetida del laboratorio')
    parser.add_argument('--automated', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--seconds', type=float, default=15, help=argparse.SUPPRESS)
    parser.add_argument('--screenshot', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--alert-screenshot', type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args(args)
    if options.server and options.join:
        parser.error('--server y --join son excluyentes')
    if not 1 <= options.seconds <= 3600:
        parser.error('--seconds debe estar entre 1 y 3600')
    if options.config and not options.config.is_file():
        parser.error('archivo --config inexistente')
    return options


def command(args):
    options = parse_args(args)
    arguments = ['--port', str(options.port), '--name', options.name, '--seconds', str(options.seconds)]
    for flag in ('server', 'development', 'lab', 'snap_cycle', 'automated'):
        if getattr(options, flag): arguments.append('--'+flag.replace('_','-'))
    if options.join: arguments += ['--join', options.join]
    for flag in ('config', 'screenshot', 'alert_screenshot'):
        value = getattr(options, flag)
        if value: arguments += ['--'+flag.replace('_','-'), str(value.resolve())]
    return [engine(), *(['--headless'] if options.server else []), '--path', str(ROOT/'game'), '--', *arguments]


if __name__ == '__main__':
    launch = command(sys.argv[1:])
    os.execv(launch[0], launch)
