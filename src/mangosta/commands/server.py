"""Estado del servidor, conexiones y operaciones en curso."""

from collections import defaultdict
from datetime import timedelta
from typing import Annotated

import typer
from pymongo.errors import OperationFailure

from ..mongo import client
from ..output import confirm, emit, emit_obj, print_json, success, to_json, warn
from ..state import state

app = typer.Typer(help="Servidor: estado, quién está conectado, operaciones lentas, matar operaciones.", no_args_is_help=True)


@app.command()
def status():
    """Versión, uptime, conexiones y operaciones del servidor."""
    cli = client()
    build = cli.admin.command("buildInfo")
    data = {"versión": build.get("version")}
    try:
        s = cli.admin.command("serverStatus")
        conns = s.get("connections", {})
        ops = s.get("opcounters", {})
        data |= {
            "host": s.get("host"),
            "proceso": s.get("process"),
            "uptime": str(timedelta(seconds=int(s.get("uptime", 0)))),
            "conexiones": f"{conns.get('current')} activas / {conns.get('available')} disponibles",
            "operaciones": ", ".join(f"{k}={v}" for k, v in ops.items()),
        }
        if "repl" in s:
            data["replica set"] = f"{s['repl'].get('setName')} ({'primario' if s['repl'].get('isWritablePrimary') else 'secundario'})"
    except OperationFailure as e:
        warn(f"Sin permisos para serverStatus: {e.details.get('errmsg', e)}")
    if state.json:
        print_json({"buildInfo": build, **data})
    else:
        emit_obj(data, title="Servidor")


def _current_ops(idle: bool) -> list[dict]:
    return list(client().admin.aggregate([
        {"$currentOp": {"allUsers": True, "idleConnections": idle, "localOps": False}}
    ]))


@app.command()
def who():
    """Quién está conectado ahora mismo: agrupado por IP, usuario y aplicación."""
    groups: dict[tuple, dict] = defaultdict(lambda: {"connections": 0, "active": 0})
    for op in _current_ops(idle=True):
        if not op.get("client"):
            continue  # hilos internos del servidor
        ip = op["client"].rsplit(":", 1)[0]
        users = ", ".join(f"{u['user']}@{u['db']}" for u in op.get("effectiveUsers", [])) or "(sin autenticar)"
        key = (ip, users, op.get("appName", ""))
        groups[key]["connections"] += 1
        groups[key]["active"] += 1 if op.get("active") else 0
    rows = [{"ip": ip, "user": user, "app": app_name, **counts}
            for (ip, user, app_name), counts in sorted(groups.items(), key=lambda kv: -kv[1]["connections"])]
    emit(rows, [("ip", "IP"), ("user", "Usuario"), ("app", "Aplicación"), ("connections", "Conexiones"), ("active", "Activas")])


_NOISE_KEYS = {"lsid", "$db", "$clusterTime", "$readPreference", "txnNumber", "cursor"}


def _is_internal(op: dict) -> bool:
    """Heartbeats de drivers y nuestra propia consulta a $currentOp."""
    cmd = op.get("command") or {}
    first = next(iter(cmd), "")
    if first.lower() in ("hello", "ismaster"):
        return True
    pipeline = cmd.get("pipeline") or []
    return bool(pipeline) and "$currentOp" in pipeline[0]


def _short_command(cmd: dict, width: int = 100) -> str:
    text = " ".join(to_json({k: v for k, v in (cmd or {}).items() if k not in _NOISE_KEYS}).split())
    return text if len(text) <= width else text[: width - 1] + "…"


@app.command()
def ops(
    min_secs: Annotated[int, typer.Option("--min-secs", help="Solo operaciones que llevan al menos N segundos")] = 0,
):
    """Operaciones en curso (para encontrar consultas lentas)."""
    rows = []
    raw = []
    for op in _current_ops(idle=False):
        if not op.get("active") or op.get("secs_running", 0) < min_secs or not op.get("client") or _is_internal(op):
            continue
        raw.append(op)
        rows.append({
            "opid": op.get("opid"),
            "secs": op.get("secs_running", 0),
            "op": op.get("op"),
            "ns": op.get("ns"),
            "client": op.get("client"),
            "user": [u["user"] for u in op.get("effectiveUsers", [])],
            "command": _short_command(op.get("command")),
        })
    rows.sort(key=lambda r: -r["secs"])
    emit(rows, [("opid", "opid"), ("secs", "Seg"), ("op", "Tipo"), ("ns", "Namespace"), ("client", "Cliente"),
                ("user", "Usuario"), ("command", "Comando")], raw=raw)


@app.command()
def kill(opid: Annotated[str, typer.Argument(help="opid (ver: mangosta server ops)")]):
    """Mata una operación en curso."""
    confirm(f"¿Matar la operación {opid}?")
    op = int(opid) if opid.lstrip("-").isdigit() else opid  # en sharded el opid es "shard:num"
    client().admin.command("killOp", op=op)
    success(f"Operación {opid} terminada")
