from pathlib import Path
from typing import Annotated, Optional

import typer
from bson import json_util

from ..errors import MangostaError
from ..mongo import client
from ..output import confirm, console, emit, err_console, info, print_json, success
from ..parsing import parse_json, parse_json_object
from ..state import state

app = typer.Typer(help="Documentos: buscar, insertar, actualizar, borrar, exportar/importar.", no_args_is_help=True)

Db = Annotated[str, typer.Argument(help="Base de datos")]
Coll = Annotated[str, typer.Argument(help="Colección")]
Filter = Annotated[Optional[str], typer.Option("--filter", "-f", help='Filtro JSON, p.ej. \'{"edad": {"$gt": 30}}\' o @fichero.json')]
ALL_HELP = "Permitir filtro vacío (afecta a TODA la colección)"


def _filter(text: str | None, allow_empty: bool) -> dict:
    flt = parse_json_object(text, "El filtro", default={})
    if not flt and not allow_empty:
        raise MangostaError("Falta --filter. Para aplicarlo a toda la colección usa --all")
    return flt


@app.command()
def find(
    db: Db,
    coll: Coll,
    filter_: Filter = None,
    projection: Annotated[Optional[str], typer.Option("--projection", "-p", help='Campos, p.ej. \'{"nombre": 1}\'')] = None,
    sort: Annotated[Optional[str], typer.Option("--sort", "-s", help='Orden, p.ej. \'{"fecha": -1}\'')] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Máximo de documentos (0 = sin límite)")] = 20,
    skip: Annotated[int, typer.Option("--skip", help="Saltar N documentos")] = 0,
    table: Annotated[bool, typer.Option("--table", "-t", help="Mostrar como tabla (campos de primer nivel)")] = False,
):
    """Busca documentos."""
    flt = parse_json_object(filter_, "El filtro", default={})
    cursor = client()[db][coll].find(flt, parse_json_object(projection, "La proyección"))
    if sort:
        cursor = cursor.sort(list(parse_json_object(sort, "El orden").items()))
    docs = list(cursor.skip(skip).limit(limit))
    if table:
        keys: list[str] = []
        for d in docs:
            keys += [k for k in d if k not in keys]
        emit(docs, [(k, k) for k in keys])
    else:
        print_json(docs)
    if limit and len(docs) == limit and not table and not state.json:
        err_console.print(f"[dim]… mostrando {limit}; usa --limit/--skip para ver más[/]")


@app.command()
def count(db: Db, coll: Coll, filter_: Filter = None):
    """Cuenta documentos."""
    n = client()[db][coll].count_documents(parse_json_object(filter_, "El filtro", default={}))
    if state.json:
        print_json({"count": n})
    else:
        console.print(n)


@app.command()
def get(db: Db, coll: Coll, id_: Annotated[str, typer.Argument(help="_id del documento (ObjectId, número o texto)")]):
    """Obtiene un documento por _id."""
    doc = None
    for candidate in _id_candidates(id_):
        doc = client()[db][coll].find_one({"_id": candidate})
        if doc:
            break
    if not doc:
        raise MangostaError(f"No hay ningún documento con _id {id_}")
    print_json(doc)


def _id_candidates(text: str) -> list:
    from bson import ObjectId
    from bson.errors import InvalidId

    out: list = []
    try:
        out.append(ObjectId(text))
    except InvalidId:
        pass
    try:
        out.append(int(text))
    except ValueError:
        pass
    out.append(text)
    return out


@app.command()
def insert(
    db: Db,
    coll: Coll,
    data: Annotated[str, typer.Argument(help="Documento JSON, array de documentos, o @fichero.json")],
):
    """Inserta uno o varios documentos."""
    docs = parse_json(data, "El documento")
    if isinstance(docs, dict):
        res = client()[db][coll].insert_one(docs)
        success(f"Insertado _id={res.inserted_id}")
    elif isinstance(docs, list) and all(isinstance(d, dict) for d in docs):
        res = client()[db][coll].insert_many(docs)
        success(f"Insertados {len(res.inserted_ids)} documentos")
    else:
        raise MangostaError("Se esperaba un objeto JSON o un array de objetos")


@app.command()
def update(
    db: Db,
    coll: Coll,
    filter_: Filter = None,
    set_: Annotated[Optional[str], typer.Option("--set", help='Campos a fijar, p.ej. \'{"activo": false}\'')] = None,
    unset: Annotated[Optional[list[str]], typer.Option("--unset", help="Campo a eliminar (repetible)")] = None,
    update_: Annotated[Optional[str], typer.Option("--update", "-u", help='Update completo con operadores, p.ej. \'{"$inc": {"n": 1}}\'')] = None,
    many: Annotated[bool, typer.Option("--many", help="Actualizar todos los que coincidan (por defecto solo uno)")] = False,
    upsert: Annotated[bool, typer.Option("--upsert", help="Insertar si no existe")] = False,
    all_: Annotated[bool, typer.Option("--all", help=ALL_HELP)] = False,
):
    """Actualiza documentos."""
    flt = _filter(filter_, all_)
    upd = parse_json_object(update_, "El update", default={}) or {}
    if set_:
        upd.setdefault("$set", {}).update(parse_json_object(set_, "--set"))
    if unset:
        upd.setdefault("$unset", {}).update({f: "" for f in unset})
    if not upd:
        raise MangostaError("Indica qué cambiar con --set, --unset o --update")
    collection = client()[db][coll]
    if many:
        n = collection.count_documents(flt)
        confirm(f"Se actualizarán {n} documentos de {db}.{coll}. ¿Continuar?")
        res = collection.update_many(flt, upd, upsert=upsert)
    else:
        res = collection.update_one(flt, upd, upsert=upsert)
    msg = f"Coincidencias: {res.matched_count}, modificados: {res.modified_count}"
    if res.upserted_id is not None:
        msg += f", insertado _id={res.upserted_id}"
    success(msg)


@app.command()
def delete(
    db: Db,
    coll: Coll,
    filter_: Filter = None,
    many: Annotated[bool, typer.Option("--many", help="Borrar todos los que coincidan (por defecto solo uno)")] = False,
    all_: Annotated[bool, typer.Option("--all", help=ALL_HELP)] = False,
):
    """Borra documentos."""
    flt = _filter(filter_, all_)
    collection = client()[db][coll]
    if many:
        n = collection.count_documents(flt)
        if n == 0:
            info("No hay documentos que coincidan")
            return
        confirm(f"Se BORRARÁN {n} documentos de {db}.{coll}. ¿Continuar?")
        res = collection.delete_many(flt)
    else:
        res = collection.delete_one(flt)
    success(f"Borrados {res.deleted_count} documentos")


@app.command()
def aggregate(
    db: Db,
    coll: Coll,
    pipeline: Annotated[str, typer.Argument(help='Pipeline JSON, p.ej. \'[{"$group": {"_id": "$pais", "n": {"$sum": 1}}}]\' o @fichero.json')],
):
    """Ejecuta un pipeline de agregación."""
    stages = parse_json(pipeline, "El pipeline")
    if not isinstance(stages, list):
        raise MangostaError("El pipeline debe ser un array JSON")
    print_json(list(client()[db][coll].aggregate(stages)))


@app.command("export")
def export_(
    db: Db,
    coll: Coll,
    output: Annotated[Path, typer.Option("--output", "-o", help="Fichero destino (.jsonl = una línea por doc, .json = array)")],
    filter_: Filter = None,
):
    """Exporta documentos a JSON (Extended JSON canónico, conserva tipos)."""
    flt = parse_json_object(filter_, "El filtro", default={})
    n = 0
    with output.open("w", encoding="utf-8") as f:
        as_array = output.suffix.lower() == ".json"
        if as_array:
            f.write("[\n")
        for doc in client()[db][coll].find(flt):
            line = json_util.dumps(doc, json_options=json_util.CANONICAL_JSON_OPTIONS, ensure_ascii=False)
            if as_array:
                f.write((",\n" if n else "") + line)
            else:
                f.write(line + "\n")
            n += 1
        if as_array:
            f.write("\n]\n")
    success(f"Exportados {n} documentos a {output}")


@app.command("import")
def import_(
    db: Db,
    coll: Coll,
    file: Annotated[Path, typer.Argument(help="Fichero .jsonl o .json (array)", exists=True, dir_okay=False)],
    drop: Annotated[bool, typer.Option("--drop", help="Vaciar la colección antes de importar")] = False,
):
    """Importa documentos desde JSON / JSONL."""
    collection = client()[db][coll]
    text = file.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        docs = json_util.loads(text)
    else:
        docs = [json_util.loads(line) for line in text.splitlines() if line.strip()]
    if drop:
        confirm(f"Se borrarán todos los documentos actuales de {db}.{coll} antes de importar. ¿Continuar?")
        collection.delete_many({})
    for i in range(0, len(docs), 1000):
        collection.insert_many(docs[i:i + 1000])
    success(f"Importados {len(docs)} documentos en {db}.{coll}")
