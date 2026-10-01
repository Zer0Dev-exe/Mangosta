from typing import Annotated

import typer

from ..errors import MangostaError
from ..mongo import SYSTEM_DBS, client, database_names, require_db
from ..output import confirm_typed, emit, emit_obj, human_bytes, info, success

app = typer.Typer(help="Bases de datos: listar, crear, copiar, renombrar, borrar.", no_args_is_help=True)

Db = Annotated[str, typer.Argument(help="Nombre de la base de datos")]
Force = Annotated[bool, typer.Option("--force", help="Permitir tocar BDs del sistema (admin, local, config)")]


def _guard_system(name: str, force: bool) -> None:
    if name in SYSTEM_DBS and not force:
        raise MangostaError(f"'{name}' es una BD del sistema; usa --force si de verdad quieres hacerlo")


@app.command("list")
def list_():
    """Lista las bases de datos con su tamaño."""
    dbs = list(client().list_databases())
    rows = [{"name": d["name"], "size": human_bytes(d.get("sizeOnDisk")), "empty": d.get("empty")} for d in dbs]
    emit(rows, [("name", "Base de datos"), ("size", "Tamaño en disco"), ("empty", "Vacía")], raw=dbs)


@app.command()
def stats(name: Db):
    """Estadísticas de una base de datos."""
    require_db(name)
    s = client()[name].command("dbStats")
    emit_obj({
        "colecciones": s.get("collections"),
        "vistas": s.get("views"),
        "documentos": s.get("objects"),
        "tamaño datos": human_bytes(s.get("dataSize")),
        "tamaño almacenado": human_bytes(s.get("storageSize")),
        "índices": s.get("indexes"),
        "tamaño índices": human_bytes(s.get("indexSize")),
    }, title=f"BD {name}")


@app.command()
def create(
    name: Db,
    collection: Annotated[str, typer.Option("--collection", "-c", help="Primera colección (MongoDB no guarda BDs vacías)")] = "init",
):
    """Crea una base de datos (creando su primera colección)."""
    if name in database_names():
        raise MangostaError(f"La base de datos '{name}' ya existe")
    client()[name].create_collection(collection)
    success(f"Base de datos '{name}' creada con la colección '{collection}'")


def _copy(src: str, dst: str) -> int:
    cli = client()
    src_db, dst_db = cli[src], cli[dst]
    existing = set(dst_db.list_collection_names())
    specs = [c for c in src_db.list_collections() if not c["name"].startswith("system.")]
    clash = existing & {c["name"] for c in specs}
    if clash:
        raise MangostaError(f"Ya existen en '{dst}': {', '.join(sorted(clash))}")
    # Primero colecciones, luego vistas (pueden depender de las colecciones).
    specs.sort(key=lambda c: c.get("type") == "view")
    for spec in specs:
        name, opts = spec["name"], spec.get("options", {})
        if spec.get("type") == "view":
            dst_db.command({"create": name, "viewOn": opts["viewOn"], "pipeline": opts.get("pipeline", [])})
            info(f"  vista {name}")
            continue
        create_opts = {k: v for k, v in opts.items() if k in ("capped", "size", "max", "validator", "validationLevel", "validationAction", "collation", "timeseries", "expireAfterSeconds")}
        dst_db.create_collection(name, **create_opts)
        if opts.get("capped"):
            # $out no puede escribir en colecciones capped: copia por lotes.
            batch = []
            for doc in src_db[name].find().sort("$natural", 1):
                batch.append(doc)
                if len(batch) == 1000:
                    dst_db[name].insert_many(batch)
                    batch = []
            if batch:
                dst_db[name].insert_many(batch)
        else:
            src_db[name].aggregate([{"$match": {}}, {"$out": {"db": dst, "coll": name}}])
        for idx in src_db[name].list_indexes():
            if idx["name"] == "_id_":
                continue
            idx = dict(idx)
            keys = list(idx.pop("key").items())
            idx.pop("v", None)
            idx.pop("ns", None)
            dst_db[name].create_index(keys, **idx)
        info(f"  colección {name} ({dst_db[name].estimated_document_count()} docs)")
    return len(specs)


@app.command()
def copy(src: Annotated[str, typer.Argument(help="BD origen")], dst: Annotated[str, typer.Argument(help="BD destino")]):
    """Copia una BD completa (colecciones, documentos, índices y vistas) a otra."""
    require_db(src)
    n = _copy(src, dst)
    success(f"Copiadas {n} colecciones/vistas de '{src}' a '{dst}'")


@app.command()
def rename(old: Annotated[str, typer.Argument(help="Nombre actual")], new: Annotated[str, typer.Argument(help="Nombre nuevo")], force: Force = False):
    """Renombra una BD (copia + borrado del original; MongoDB no tiene rename nativo)."""
    _guard_system(old, force)
    require_db(old)
    if new in database_names():
        raise MangostaError(f"La base de datos '{new}' ya existe")
    confirm_typed(f"Se copiará '{old}' a '{new}' y después se BORRARÁ '{old}'.", old)
    _copy(old, new)
    client().drop_database(old)
    success(f"Base de datos '{old}' renombrada a '{new}'")


@app.command()
def drop(name: Db, force: Force = False):
    """Borra una base de datos entera. ¡Irreversible!"""
    _guard_system(name, force)
    require_db(name)
    n = len(client()[name].list_collection_names())
    confirm_typed(f"Vas a BORRAR la base de datos '{name}' con {n} colecciones. No se puede deshacer.", name)
    client().drop_database(name)
    success(f"Base de datos '{name}' borrada")
