# Changelog

## 0.2.0 — 2026-09-03

Primera versión con el ciclo completo funcionando de punta a punta.

### Añadido
- `/baton` escribe el traspaso: el modelo redacta solo el cuerpo, el código
  valida, mide, compone y escribe de forma atómica.
- Inyección al arrancar (`SessionStart`) por `hookSpecificOutput.additionalContext`.
- Los dos modos, `continuacion` y `memoria`, con instrucciones distintas para la
  sesión que recibe el traspaso.
- Ciclo automático: `PostCompact` guarda el resumen de la compactación y `Stop`
  pide la redacción en el primer momento libre.
- Aviso de frescura contra git: edad, cambio de rama, commits nuevos y detección
  de rebase. Nunca caduca.
- Presupuesto duro (120 líneas / 6.000 caracteres) derivado del techo real del
  harness, con informe de qué sección sobra y anti-bucle de tres intentos.
- Histórico rotado con retención de 10, que solo borra ficheros propios.
- `baton.py contexto|escribir|ver|doctor`.
- Configuración en `~/.claude/baton.json` y `<proyecto>/.claude/baton.json`.
- 193 tests con `unittest` de la stdlib.

## 0.1.0 — 2026-09-03

Esqueleto instalable: manifiestos, los tres hooks registrados, `doctor` y la
bitácora que demuestra que el hook disparó.
