from typing import Annotated, Optional

import typer

from ..errors import MangostaError
from ..mongo import client, require_collection
from ..output import confirm_typed, emit, success
from ..parsing import parse_index_keys

app = typer.Typer(help="Índices: listar, crear, ocultar, borrar.", no_args_is_help=True)

Db = Annotated[str, typer.Argument(help="Base de datos")]
Coll = Annotated[str, typer.Argument(help="Colección")]
Name = Annotated[str, typer.Argument(help="Nombre del índice")]


@app.command("list")
def list_(db: Db, coll: Coll):
    """Lista los índices de una colección."""
    require_collection(db, coll)
    idx = list(client()[db][coll].list_indexes())
    rows = [{
        "name": i["name"],
        "keys": ", ".join(f"{k}:{v}" for k, v in i["key"].items()),
        "unique": i.get("unique"),
        "sparse": i.get("sparse"),
        "ttl": f"{i['expireAfterSeconds']}s" if "expireAfterSeconds" in i else None,
        "hidden": i.get("hidden"),
        "partial": i.get("partialFilterExpression"),
    } for i in idx]
    emit(rows, [("name", "Nombre"), ("keys", "Claves"), ("unique", "Único"), ("sparse", "Sparse"),
                ("ttl", "TTL"), ("hidden", "Oculto"), ("partial", "Filtro parcial")], raw=idx)


@app.command()
def create(
    db: Db,
    coll: Coll,
    keys: Annotated[str, typer.Argument(help='Claves: "email:1,fecha:-1" (tipos: 1, -1, text, 2dsphere, 2d, hashed) o JSON')],
    name: Annotated[Optional[str], typer.Option("--name", help="Nombre del índice")] = None,
    unique: Annotated[bool, typer.Option("--unique", help="Índice único")] = False,
    sparse: Annotated[bool, typer.Option("--sparse", help="Ignorar docs sin el campo")] = False,
    ttl: Annotated[Optional[int], typer.Option("--ttl", help="Borrar docs N segundos después de la fecha del campo")] = None,
    hidden: Annotated[bool, typer.Option("--hidden", help="Crearlo oculto al planificador")] = False,
):
    """Crea un índice."""
    opts: dict = {}
    if name:
        opts["name"] = name
    if unique:
        opts["unique"] = True
    if sparse:
        opts["sparse"] = True
    if ttl is not None:
        opts["expireAfterSeconds"] = ttl
    if hidden:
        opts["hidden"] = True
    created = client()[db][coll].create_index(parse_index_keys(keys), **opts)
    success(f"Índice '{created}' creado en {db}.{coll}")


def _set_hidden(db: str, coll: str, name: str, hidden: bool) -> None:
    require_collection(db, coll)
    client()[db].command({"collMod": coll, "index": {"name": name, "hidden": hidden}})
    success(f"Índice '{name}' {'oculto' if hidden else 'visible'}")


@app.command()
def hide(db: Db, coll: Coll, name: Name):
    """Oculta un índice al planificador (para probar antes de borrarlo)."""
    _set_hidden(db, coll, name, True)


@app.command()
def unhide(db: Db, coll: Coll, name: Name):
    """Vuelve a hacer visible un índice oculto."""
    _set_hidden(db, coll, name, False)


@app.command()
def drop(db: Db, coll: Coll, name: Name):
    """Borra un índice."""
    if name == "_id_":
        raise MangostaError("El índice _id_ no se puede borrar")
    require_collection(db, coll)
    confirm_typed(f"Vas a borrar el índice '{name}' de {db}.{coll}.", name)
    client()[db][coll].drop_index(name)
    success(f"Índice '{name}' borrado")
