# baton

Traspaso de contexto entre sesiones de Claude Code **con un documento que no crece**.

> Estado: en construcción (v0.1.0). El esqueleto y los hooks ya se instalan y
> disparan; la redacción y la inyección llegan en la siguiente fase.

## El problema

Cuando una sesión de Claude Code se alarga, la calidad se degrada y toca abrir una
nueva. El traspaso hoy es manual, y los plugins que lo automatizan comparten un
fallo medido: **el documento crece sin límite**. Un caso real llegó a **931 líneas
≈ 14.200 tokens**. El documento que existía para *ahorrar* contexto acabó siendo el
mayor consumidor de contexto del arranque.

Y hay algo peor. Claude Code trunca el contexto que un hook inyecta a **8.000
caracteres o 200 líneas, lo que ocurra primero**, y lo hace **en silencio**. Un
traspaso de 14.200 tokens no es solo caro: no cabe. Llega cortado y nadie avisa.

## Qué hace baton distinto

- **Se reescribe entero, nunca se añade.** Un solo fichero, sin entradas apiladas.
- **Presupuesto duro verificado por código**: 120 líneas / 6.000 caracteres. Si el
  traspaso no cabe, el comando **falla y obliga a recortar** — no trunca a media
  frase, porque un traspaso cortado miente.
- **Secciones opcionales de verdad.** Si no hay bloqueos, la sección *no existe*.
  Nada de «Bloqueos: ninguno»: los huecos son por donde engordan los demás.
- **Dos modos**, y este es el diferenciador:
  - `continuacion` — hay tarea a medias; la sesión nueva la retoma.
  - `memoria` — hay progreso pero **nada que continuar**. La sesión nueva recibe el
    contexto y se le dice explícitamente *«no inicies trabajo, espera instrucciones»*.

  Ningún plugin equivalente distingue los dos casos: todos asumen que siempre hay
  trabajo a medias, así que la sesión nueva arranca sola y toca lo que nadie pidió.
- **Los datos de git los pone el código**, no el modelo: rama, commit, ficheros sin
  commitear, fecha. Gratis, exactos y sin gastar presupuesto.
- **Aviso de frescura, sin caducidad.** Al inyectar compara con git y avisa: *«esto
  es de hace 6 días y hay 14 commits desde entonces»*. Nunca descarta contexto solo
  por ser viejo.

## Instalación

```bash
claude plugin marketplace add mrshelll/baton
claude plugin install baton@baton
```

**Reinicia Claude Code después de instalar.** Los hooks se cargan al arrancar: sin
reinicio no disparan, y un hook que no dispara no da error — no da nada. Es el
error número uno.

Comprueba que quedó bien:

```
/hooks                       # baton debe salir en SessionStart, PostCompact y Stop
python3 scripts/baton.py doctor
```

## Cómo funciona

| Momento | Qué pasa |
|---|---|
| Escribes `/baton` | El modelo redacta el traspaso; el código lo valida, lo mide y lo escribe |
| El harness compacta | `PostCompact` guarda el resumen de la compactación y arma una bandera |
| Terminas el siguiente intercambio | `Stop` pide el traspaso: el contexto acaba de vaciarse, es el momento más barato de la sesión |
| Abres sesión nueva | `SessionStart` inyecta el traspaso con su modo y su aviso de frescura |

## Dónde vive todo

| Qué | Dónde | Se commitea |
|---|---|---|
| El traspaso | `<proyecto>/.baton/TRASPASO.md` | sí |
| Histórico, borradores, registros | `<proyecto>/.baton/local/` | no (`.gitignore`) |
| Config global | `~/.claude/baton.json` | — |
| Config del proyecto | `<proyecto>/.claude/baton.json` | según tú |

Añade **una sola línea** a tu `.gitignore`:

```
.baton/local/
```

**Instalas una vez, a nivel de usuario, y funciona en todos tus proyectos.** baton
no lleva un registro de proyectos: cada hook recibe el directorio de la sesión y
trabaja ahí. En un proyecto donde nunca corriste `/baton`, el plugin está instalado
pero **inerte**: no crea ficheros ni escribe nada. El primer `/baton` lo activa.

Y no necesitas git. Si el proyecto es un repo, baton aprovecha rama y commits. Si
no lo es, funciona igual, sin esos datos.

## Requisitos

Python 3 (stdlib, cero dependencias) y Claude Code. `git` es opcional.

## Desarrollo

```bash
./tests/run.sh
```

Los tests corren con `unittest` de la stdlib: **sin Claude Code y sin instalar
nada**. Los de hooks invocan el script como subproceso con stdin JSON, igual que
el harness, porque es la única forma de cubrir el contrato real.

## Lo que baton no hará nunca

Añadir al final del documento en vez de reescribirlo · escribir secciones con
«ninguno» · caducar un traspaso · abrir la sesión nueva por ti · hooks
`PostToolUse` o `UserPromptSubmit` · un `Stop` que te interrumpa fuera del momento
posterior a una compactación · una segunda implementación en bash.

## Licencia

MIT
