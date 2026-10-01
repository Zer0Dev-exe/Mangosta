<p align="center">
  <img src="docs/banner.png" alt="mangosta — gestiona MongoDB desde la terminal">
</p>

Gestiona MongoDB desde la terminal, igual que desde el panel de MongoDB Atlas:
bases de datos, colecciones, documentos, índices, **usuarios y permisos**,
**qué IPs pueden conectarse**, **quién tiene acceso al proyecto**, clusters,
y quién está conectado ahora mismo.

Funciona con:

- **MongoDB self-hosted** (o cualquier servidor al que te conectes con una URI).
- **MongoDB Atlas**, usando la Atlas Admin API para lo que Atlas no deja hacer
  por conexión directa (usuarios, IP access list, clusters, miembros del proyecto).

Un mismo perfil puede tener las dos cosas: la URI del cluster (para los datos)
y las credenciales de la Admin API (para la seguridad y la infraestructura).

## Instalación

```bash
pip install -e .          # desde esta carpeta
# o, con pipx, para tenerlo global:
pipx install .
```

Se instalan dos comandos equivalentes: `mangosta` y el atajo `mgs`.

## Interfaz interactiva

```bash
mangosta
```

Sin argumentos se abre una interfaz a pantalla completa, al estilo del panel de Atlas:

- **Lateral**: tus conexiones → organizaciones → proyectos (y tus servidores propios).
- **Pestañas** según lo que elijas:
  - proyecto: *Clusters · Datos · Usuarios BD · Acceso IP · Miembros*
  - organización: *Proyectos · Miembros*
  - servidor propio: *Datos · Usuarios BD · Acceso IP · Conexiones*
- **Datos**: árbol de bases de datos/colecciones, tabla de documentos y el documento completo
  en JSON; filtrar, insertar, editar y borrar documentos, crear y borrar colecciones/BDs.
- Lo que eliges queda como contexto también para los comandos de la terminal.

| Tecla | Acción |
|-------|--------|
| `1`…`5` | Cambiar de pestaña |
| `/` | Buscar en la tabla |
| `n` | Nuevo (cluster, usuario, IP, invitación, proyecto, colección o documento) |
| `e` | Editar (roles de usuario, rol de miembro, documento) |
| `k` | Cambiar contraseña de un usuario de BD |
| `c` | Conectar a los datos del cluster seleccionado |
| `p` | Pausar / reanudar cluster |
| `m` | Añadir tu IP actual a la access list |
| `f` | Filtrar documentos (`{"estado": "pendiente"}`) |
| `y` | Copiar (cadena de conexión, usuario, IP, documento…) |
| `x` | Borrar (siempre con confirmación; lo irreversible pide escribir el nombre) |
| `r` | Refrescar |
| `l` | Iniciar sesión con tu cuenta de MongoDB |
| `?` | Acerca de (logo y versión) |
| `q` | Salir |

## Primeros pasos

### Atlas: entra con tu cuenta de MongoDB (recomendado)

```bash
mangosta login
```

1. Se abre el navegador en `account.mongodb.com/account/connect` y la terminal muestra un código.
2. Inicias sesión con tu cuenta de MongoDB (email, Google, GitHub, SSO…) e introduces el código.
3. Eliges la organización, el proyecto y, si quieres, un cluster para gestionar también sus datos.

Y ya puedes usarlo todo con tus permisos de Atlas:

```bash
mangosta cluster list
mangosta access list
mangosta user list
mangosta db list
```

```bash
mangosta auth status          # cuenta, proyecto, cluster y caducidades
mangosta org use "Otra org"   # cambiar de organización
mangosta project use "Otro"   # cambiar de proyecto
mangosta cluster connect      # gestionar los datos de otro cluster
mangosta logout               # revoca la sesión y borra el usuario temporal
```

**Cómo funciona:**
- Es el mismo flujo OAuth (*device authorization*) que usa `atlas auth login`, el CLI oficial.
- El token caduca a las pocas horas y mangosta lo renueva solo.
- Tu sesión da acceso a la **Admin API** (usuarios, IPs, clusters…), pero no a los **datos**.
  Para eso, `cluster connect` (o el paso final de `login`):
  - añade tu IP actual a la access list si no está, preguntando antes;
  - crea un usuario de base de datos temporal `mangosta-<usuario>-<equipo>`
    (rol `atlasAdmin`, solo ese cluster, caduca a los 6 días: Atlas no admite más de 7);
  - mangosta renueva su contraseña y caducidad automáticamente antes de que expire.
  
  Cambia el rol con `cluster connect --role readWriteAnyDatabase@admin`.
- MongoDB no permite registrar aplicaciones OAuth de terceros, así que mangosta usa el
  client ID público del Atlas CLI (`--client-id` permite cambiarlo). Es lo mismo que hace
  el CLI oficial, pero no es una integración soportada oficialmente por MongoDB para otras herramientas.

### Atlas con API key o service account (para scripts / CI)

En Atlas: *Organization → Access Manager → Applications*, crea una API key o una service account
con rol `Project Owner` y añade la IP desde la que la usarás.

```bash
mangosta profile add ci   --atlas-public-key abcdefgh   --atlas-private-key env:ATLAS_PRIVATE_KEY      # o deja que te la pida oculta
#  (o --atlas-client-id ... --atlas-client-secret ... para service accounts)
mangosta -p ci project use "Mi proyecto"
mangosta -p ci cluster connect Cluster0
```

### Servidor propio (self-hosted)

```bash
mangosta profile add local --uri "mongodb://admin:secreto@localhost:27017"
mangosta profile test
mangosta db list
```

Los secretos y tokens se guardan en `~/.mangosta/config.json` (permisos 600). Cualquier valor
puede ser `env:NOMBRE_VARIABLE` para leerlo de una variable de entorno en vez de guardarlo.

## Comandos

| Grupo      | Para qué                                     | Equivale en Atlas a       |
|------------|----------------------------------------------|---------------------------|
| `login` / `logout` / `auth` | Sesión con tu cuenta de MongoDB    | Iniciar sesión            |
| `profile`  | Conexiones guardadas                          | —                         |
| `db`       | Bases de datos                                | Data Explorer             |
| `coll`     | Colecciones, validación de esquema            | Data Explorer             |
| `doc`      | Buscar / insertar / actualizar / borrar / exportar | Data Explorer         |
| `index`    | Índices                                       | Data Explorer → Indexes   |
| `user`     | Usuarios de BD y sus permisos                 | **Database Access**       |
| `role`     | Roles personalizados                          | Database Access → Custom Roles |
| `access`   | IPs que pueden conectarse                     | **Network Access**        |
| `members`  | Personas con acceso al proyecto               | **Project Access Manager** |
| `org`      | Organizaciones y su gente                     | Organization Access Manager |
| `project`  | Proyectos: listar, elegir, crear, borrar      | Selector de proyecto      |
| `cluster`  | Conectar, crear, pausar, escalar, borrar clusters | Clusters → Connect    |
| `server`   | Estado, quién está conectado, ops lentas      | Real Time / Metrics       |
| `shell`    | Abre `mongosh` con el perfil activo           | —                         |

Todo tiene ayuda: `mangosta --help`, `mangosta user --help`, `mangosta user create --help`...

### Opciones globales

- `-p, --profile NOMBRE` usa otro perfil solo para este comando.
- `--uri URI` conexión puntual sin perfil.
- `--json` salida JSON (para scripts y `jq`).
- `-y, --yes` no pedir confirmaciones (pueden ir en cualquier posición).

### Ejemplos

**Bases de datos y colecciones**

```bash
mangosta db list
mangosta db stats tienda
mangosta db create tienda --collection pedidos
mangosta db copy tienda tienda_backup
mangosta db rename tienda_vieja tienda_2025
mangosta db drop tienda_vieja                  # pide escribir el nombre para confirmar

mangosta coll list tienda
mangosta coll create tienda logs --capped --size 10000000
mangosta coll rename tienda pedidos orders
mangosta coll validator tienda clientes --set @schema.json --level strict
mangosta coll drop tienda logs
```

**Documentos**

```bash
mangosta doc find tienda clientes -f '{"pais": "ES"}' -s '{"alta": -1}' -n 10
mangosta doc find tienda clientes --table
mangosta doc get tienda clientes 665f1c...
mangosta doc count tienda pedidos -f '{"estado": "pendiente"}'
mangosta doc insert tienda clientes '{"nombre": "Ana", "pais": "ES"}'
mangosta doc insert tienda clientes @clientes.json
mangosta doc update tienda clientes -f '{"nombre": "Ana"}' --set '{"vip": true}'
mangosta doc update tienda pedidos -f '{"estado": "pendiente"}' -u '{"$inc": {"intentos": 1}}' --many
mangosta doc delete tienda pedidos -f '{"estado": "cancelado"}' --many
mangosta doc aggregate tienda pedidos '[{"$group": {"_id": "$estado", "n": {"$sum": 1}}}]'
mangosta doc export tienda clientes -o clientes.jsonl
mangosta doc import tienda clientes clientes.jsonl --drop
```

Los filtros aceptan Extended JSON (`{"_id": {"$oid": "..."}}`, `{"$date": "..."}`)
y `@fichero.json` en lugar del JSON en línea. `update` y `delete` exigen `--filter`
(o `--all` para afectar a toda la colección).

**Índices**

```bash
mangosta index list tienda clientes
mangosta index create tienda clientes "email:1" --unique
mangosta index create tienda sesiones "creada:1" --ttl 3600
mangosta index create tienda productos "nombre:text,descripcion:text"
mangosta index hide tienda clientes email_1     # probar el impacto antes de borrar
mangosta index drop tienda clientes email_1
```

**Usuarios (Database Access)**

```bash
mangosta user list
mangosta user create app --role readWrite@tienda --generate-password
mangosta user create analista --role read@tienda --role read@logs
mangosta user grant analista readWrite@informes
mangosta user revoke analista read@logs
mangosta user passwd app -g
mangosta user delete analista
mangosta user whoami

# Solo Atlas:
mangosta user create soporte --role read@tienda.pedidos --cluster Cluster0 --expires 7d
```

**Acceso por IP (Network Access)**

En **Atlas** es la IP access list del proyecto:

```bash
mangosta access list
mangosta access add me --comment "mi portátil"   # tu IP pública actual
mangosta access add 203.0.113.0/24 --comment "oficina"
mangosta access add 198.51.100.7 --expires 6h        # entrada temporal
mangosta access remove 198.51.100.7
```

En **MongoDB self-hosted** no existe una lista global de IPs (eso se hace con `bindIp`
en `mongod.conf` y el firewall), pero sí se puede limitar **desde qué IPs puede
autenticarse cada usuario**; mangosta lo gestiona con `--user`:

```bash
mangosta access list                         # IPs permitidas por usuario
mangosta access add 10.0.0.0/24 --user app   # app solo podrá entrar desde esa red
mangosta access remove 10.0.0.0/24 --user app
mangosta access clear --user app             # sin restricciones
```

Si intentas restringir el usuario con el que estás conectado a IPs que no incluyen
la tuya, mangosta te avisa antes de dejarte fuera.

**Roles personalizados**

```bash
mangosta role list
mangosta role create lector-pedidos -P "tienda.pedidos:find" -P "tienda:listCollections"
mangosta role create soporte --inherit read@tienda -P "tienda.tickets:find,insert,update"
mangosta user grant soporte-ana soporte@admin
mangosta role drop lector-pedidos
```

**Gente con acceso al proyecto (Atlas)**

```bash
mangosta members list
mangosta members invite ana@empresa.com --role read_only
mangosta members set-roles ana@empresa.com --role data_access_read_write --role read_only
mangosta members remove ana@empresa.com
```

**Organizaciones y proyectos (Atlas)**

```bash
mangosta org list
mangosta org use "Astra Community"
mangosta org members list
mangosta org members invite ana@empresa.com --role read_only
mangosta org members remove ana@empresa.com
mangosta project list            # los de la organización activa (--all: todos)
mangosta project create "Nuevo"
mangosta project delete "Viejo"  # Atlas exige que no tenga clusters
```

**Clusters (Atlas)**

```bash
mangosta cluster list
mangosta cluster show Cluster0
mangosta cluster create pruebas --tier M0 --provider AWS --region EU_WEST_1
mangosta cluster scale produccion --tier M30
mangosta cluster pause staging
mangosta cluster resume staging
mangosta cluster delete pruebas
```

**Monitorización**

```bash
mangosta server status
mangosta server who               # conexiones agrupadas por IP / usuario / app
mangosta server ops --min-secs 5  # operaciones lentas
mangosta server kill 12345
```

## Seguridad

- Las operaciones destructivas (`drop`, `delete`, `rename` de BD, borrar usuarios/clusters...)
  piden escribir el nombre del recurso, como en Atlas. `--yes` se lo salta: úsalo con cuidado
  en scripts.
- `db drop`/`db rename` se niegan a tocar `admin`, `local` y `config` sin `--force`.
- `access add 0.0.0.0/0` pide confirmación explícita.

## Créditos

Logotipo con la fuente [Exo 2](https://fonts.google.com/specimen/Exo+2) (Black Italic),
de Natanael Gama, bajo licencia SIL Open Font License. El logo y el nombre se dibujan
también en la propia terminal (con medios bloques de color) a partir de `src/mangosta/assets/`.
