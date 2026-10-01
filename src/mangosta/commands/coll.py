from typing import Annotated, Optional

import typer
from pymongo.errors import OperationFailure

from ..errors import MangostaError
from ..mongo import client, require_collection, require_db
from ..output import confirm_typed, emit, emit_obj, human_bytes, print_json, success
from ..parsing import parse_json_object

app = typer.Typer(help="Colecciones: listar, crear, renombrar, validación, borrar.", no_args_is_help=True)

Db = Annotated[str, typer.Argument(help="Base de datos")]
Coll = Annotated[str, typer.Argument(help="Colección")]


def _storage_stats(db: str, coll: str) -> dict:
    try:
        res = list(client()[db][coll].aggregate([{"$collStats": {"storageStats": {}}}]))
        return res[0]["storageStats"] if res else {}
    except OperationFailure:
        return {}


@app.command("list")
def list_(db: Db):
    """Lista las colecciones y vistas de una BD."""
    require_db(db)
    rows = []
    for c in sorted(client()[db].list_collections(), key=lambda c: c["name"]):
        kind = c.get("type", "collection")
        row = {"name": c["name"], "type": kind}
        if kind == "collection":
            s = _storage_stats(db, c["name"])
            row |= {
                "docs": s.get("count", client()[db][c["name"]].estimated_document_count()),
                "size": human_bytes(s.get("size")),
                "indexes": s.get("nindexes"),
            }
        rows.append(row)
    emit(rows, [("name", "Colección"), ("type", "Tipo"), ("docs", "Docs"), ("size", "Tamaño"), ("indexes", "Índices")])


@app.command()
def stats(db: Db, coll: Coll):
    """Estadísticas de una colección."""
    require_collection(db, coll)
    s = _storage_stats(db, coll)
    if not s:
        raise MangostaError("No se pudieron obtener estadísticas (¿es una vista o faltan permisos?)")
    emit_obj({
        "documentos": s.get("count"),
        "tamaño datos": human_bytes(s.get("size")),
        "tamaño medio doc": human_bytes(s.get("avgObjSize")),
        "tamaño almacenado": human_bytes(s.get("storageSize")),
        "índices": s.get("nindexes"),
        "tamaño índices": human_bytes(s.get("totalIndexSize")),
        "capped": s.get("capped"),
    }, title=f"{db}.{coll}")


@app.command()
def create(
    db: Db,
    coll: Coll,
    capped: Annotated[bool, typer.Option("--capped", help="Colección de tamaño fijo")] = False,
    size: Annotated[Optional[int], typer.Option("--size", help="Tamaño máximo en bytes (capped)")] = None,
    max_docs: Annotated[Optional[int], typer.Option("--max", help="Máximo de documentos (capped)")] = None,
    validator: Annotated[Optional[str], typer.Option("--validator", help="Validador JSON o @fichero.json")] = None,
):
    """Crea una colección."""
    if coll in client()[db].list_collection_names():
        raise MangostaError(f"La colección '{db}.{coll}' ya existe")
    opts: dict = {}
    if capped:
        if not size:
            raise MangostaError("Una colección capped necesita --size")
        opts |= {"capped": True, "size": size}
        if max_docs:
            opts["max"] = max_docs
    if validator:
        opts["validator"] = parse_json_object(validator, "El validador")
    client()[db].create_collection(coll, **opts)
    success(f"Colección '{db}.{coll}' creada")


@app.command()
def rename(
    db: Db,
    old: Annotated[str, typer.Argument(help="Nombre actual")],
    new: Annotated[str, typer.Argument(help="Nombre nuevo")],
    to_db: Annotated[Optional[str], typer.Option("--to-db", help="Moverla a otra BD")] = None,
    drop_target: Annotated[bool, typer.Option("--drop-target", help="Sobrescribir el destino si existe")] = False,
):
    """Renombra (o mueve a otra BD) una colección."""
    require_collection(db, old)
    target_db = to_db or db
    if drop_target:
        confirm_typed(f"Si '{target_db}.{new}' existe será BORRADA.", new)
    client().admin.command("renameCollection", f"{db}.{old}", to=f"{target_db}.{new}", dropTarget=drop_target)
    success(f"'{db}.{old}' → '{target_db}.{new}'")


@app.command()
def validator(
    db: Db,
    coll: Coll,
    set_: Annotated[Optional[str], typer.Option("--set", help="Nuevo validador JSON o @fichero.json ('{}' lo quita)")] = None,
    level: Annotated[Optional[str], typer.Option("--level", help="off | strict | moderate")] = None,
    action: Annotated[Optional[str], typer.Option("--action", help="error | warn")] = None,
):
    """Muestra o cambia la validación de esquema de una colección."""
    require_collection(db, coll)
    if set_ is None and level is None and action is None:
        spec = next(client()[db].list_collections(filter={"name": coll}))
        opts = spec.get("options", {})
        print_json({k: opts.get(k) for k in ("validator", "validationLevel", "validationAction")})
        return
    cmd: dict = {"collMod": coll}
    if set_ is not None:
        cmd["validator"] = parse_json_object(set_, "El validador")
    if level:
        cmd["validationLevel"] = level
    if action:
        cmd["validationAction"] = action
    client()[db].command(cmd)
    success(f"Validación de '{db}.{coll}' actualizada")


@app.command()
def drop(db: Db, coll: Coll):
    """Borra una colección. ¡Irreversible!"""
    require_collection(db, coll)
    n = client()[db][coll].estimated_document_count()
    confirm_typed(f"Vas a BORRAR '{db}.{coll}' con ~{n} documentos.", coll)
    client()[db].drop_collection(coll)
    success(f"Colección '{db}.{coll}' borrada")
