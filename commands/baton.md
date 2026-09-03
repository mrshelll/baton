---
description: Escribe el traspaso de contexto de esta sesión — documento de tamaño acotado, listo para arrancar la siguiente sin perder el hilo.
argument-hint: "[memoria|continuacion] [nota corta opcional]"
allowed-tools: Bash, Read, Write, Glob, Grep
---

Escribe el traspaso de esta sesión siguiendo **exactamente** el procedimiento de
la skill `baton` (`skills/baton/SKILL.md` de este plugin). No improvises un
formato propio: el documento lo compone y valida el código, no tú.

Argumentos recibidos: $ARGUMENTS

Si los argumentos empiezan por `memoria` o `continuacion`, ese es el modo y no
tienes que decidirlo. El resto del texto, si lo hay, es una nota del usuario
sobre qué quiere que quede recogido.
