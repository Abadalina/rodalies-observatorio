"""Tests de la interfaz de linea de comandos (sin tocar la base de datos)."""

from __future__ import annotations

import pytest

from rodalies.cli import _parser


def test_todos_los_comandos_estan_registrados():
    esperados = {
        "migrate",
        "load-gtfs",
        "poll",
        "run",
        "refresh",
        "check",
        "stats",
        "export",
        "capture",
    }
    accion = next(a for a in _parser()._actions if a.dest == "command")
    assert esperados <= set(accion.choices)


def test_hace_falta_un_comando():
    with pytest.raises(SystemExit):
        _parser().parse_args([])


def test_opciones_de_load_gtfs():
    args = _parser().parse_args(["load-gtfs", "--force", "--file", "x.zip"])
    assert args.command == "load-gtfs"
    assert args.force is True
    assert args.file == "x.zip"


def test_export_acepta_rango():
    args = _parser().parse_args(["export", "--desde", "2026-09-01", "--hasta", "2026-09-30"])
    assert args.desde == "2026-09-01"
    assert args.source == "renfe"
