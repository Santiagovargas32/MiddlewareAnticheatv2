# Flujo de desarrollo

La entrada es [AGENTS](../../AGENTS.md); el [roadmap](roadmap.md) prioriza y el
[estado](project-state.md) registra evidencia. Una ficha basada en la
[plantilla](tasks/TEMPLATE.md) delimita cada encargo. Planificación no autoriza
implementar los siguientes paquetes. Los IDs MA son internos, no issues de GitHub.

## Inicio y Git

Inspecciona instrucciones, WIP y remotos sin mostrar secretos. Lee el mapa inicial
indicado en AGENTS. Contrasta cada hallazgo de auditorías con HEAD y distingue
lectura de código, inferencia y reproducción. Comprueba herramientas y criterios
antes de editar; no asumas GPU, TPM ni dos equipos.

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git fetch origin main
git rev-parse origin/main
```

Registra SHA base completo en la ficha y verifica que las dependencias estén
integradas. Con árbol limpio crea la rama desde `origin/main`. Si hay WIP ajeno,
usa un worktree nuevo sin reset/stash; conserva instrucciones locales y no
copies secretos al nuevo árbol. Un bloqueo de permisos se resuelve mediante el
mecanismo del entorno, nunca desactivando controles.

Ramas: `<tipo>/ma-<id>-<descripcion-kebab-case>`, con tipo `feat`, `fix`,
`refactor`, `test`, `perf`, `docs`, `ci`, `build` o `chore`. Una rama y una PR por
objetivo coherente, incluidos sus tests y documentación. Commits:
`tipo(area): cambio concreto`. Ejemplo de inicio, sólo al encargar MA-010 tras
integrar MA-000:

```bash
git switch -c docs/ma-010-admission-design origin/main
```

Resuelve decisiones rutinarias y completa el flujo autorizado. No mezcles arreglos
independientes: registra una ficha BACKLOG con reproducción, prioridad y posible
dependencia. Si bloquea el paquete, deja BLOCKED con acción concreta. Sólo cambia
a otro paquete independiente si está autorizado. Subdivide paquetes demasiado
grandes antes de implementarlos. No hay delegación automática.

## Verificación por riesgo

| Cambio | Comandos y evidencia exigida |
| --- | --- |
| Documentación | `python3 scripts/verificar-documentacion.py`; contenido, enlaces, rutas y coherencia |
| Entregable/inventario | `python3 tools/verify_release.py`; paquete y extracción limpia con hashes, fuentes requeridos y exclusión de privados |
| Visuales o flujo real | `python3 tools/verify_game.py --graphical`; teclado/ratón, ventanas reales, resolución y capturas comparables; headless no valida estética |
| C/contratos | Release `-Werror` y CTest (abajo); `python3 scripts/verificar-build.py` según cambio |
| Admisión/TPM | `LAB_TPM=ON`, CTest `session_admission` y `python3 scripts/verificar-admision.py --inspector build-tpm/lab_quote_inspect`; fixtures software separadas de hardware |
| Transporte/recursos C | `python3 scripts/verificar-integracion.py --direct`; `--via-adapter` si comparte transporte; `--sanitize` para memoria/ciclo de recursos |
| Supervisión/TLS/CLI | `python3 scripts/verificar-capacidades.py`, `python3 scripts/verificar-puente.py`, `python3 scripts/verificar-cli.py` según subsistema; requieren `build/` |

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS=-Werror
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
# Cuando cambie admisión/TPM:
cmake -S . -B build-tpm -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS=-Werror -DLAB_TPM=ON
cmake --build build-tpm --parallel 2
ctest --test-dir build-tpm --output-on-failure
```

Para un paquete fuente de revisión (no una nueva release):

```bash
mkdir -p results
python3 tools/package_game.py --output results/ma-000-review.tar.gz
```

El empaquetador no sobrescribe archivos: usa un nombre nuevo si ya existe. Extrae
en directorio temporal vacío; comprueba PACKAGE.json, todos sus hashes, ejecutables
y documentación con el verificador desde esa copia. Comprueba también un clone
local del commit: debe contener AGENTS, workflow, fichas y plantillas sin depender
de archivos ignorados. Inventario: [release_files.py](../../tools/release_files.py).
Añade rutas explícitas o formatos necesarios, no extensiones globales sin control.

En nuevas fronteras de admisión exige E2E de permiso ausente/expirado, certificado
incorrecto, sustitución/replay, revocación concurrente, servicio caído, restart y
reconexión; mide tiempo máximo hasta bloquear acciones y limpiar intenciones.
No bloquear el tick. Reutiliza [tests existentes](../../tests/README.md) y el
[contrato de admisión](../session-admission.md); no rehagas el registro integrado.

Registra revisión o base + diff, entorno, comando, resultado y alcance. Usa plazos
y limpia sólo procesos propios. Repite suites por cambios, fallos o dudas nuevos;
no añadas tests que sólo reflejen la implementación. Si falta entorno: BLOCKED y
comando para completarlo, nunca PASS. CI previa y validation-v0.1.0.json son
históricos. Ventanas locales no acreditan LAN física; firmas software no son TPM.

## Estados y cierre

`BACKLOG → READY → IN_PROGRESS → IN_REVIEW → DONE`; `BLOCKED` exige causa y
siguiente acción. READY requiere alcance/aceptación definidos y dependencias
integradas; IN_REVIEW significa listo localmente o PR abierta. DONE requiere merge
en la rama objetivo. Una aceptación física pendiente se registra por separado.

Para dejar IN_REVIEW: cumple criterios observables, prueba caminos normal/error,
conserva o versiona contratos, registra límites y actualiza ficha/estado/roadmap y
ADR cuando corresponda. Revisa dependencias, licencias, diff y rollback. Staging
por rutas, nunca `git add .` indiscriminado:

```bash
git diff --check
git diff --cached
# Después del commit; sustituye BASE por el SHA anotado en la ficha:
git diff BASE...HEAD
```

Haz commit local con identidad existente; no la inventes. Prepara título/cuerpo
con la [plantilla de PR](../../.github/pull_request_template.md). Push y creación de
PR requieren autorización de la ficha; merge, tags y releases no se infieren de
«terminar». No cambies main ni reescribas v0.1.0. Sin autorización de publicación,
entrega commit y texto preparado sin inventar URL.

Actualiza [project-state](project-state.md) al cerrar: objetivo, rama, SHA base,
cambios, evidencia, bloqueos, riesgos, rollback y próximo comando. No incrustes el
hash del mismo commit que contiene el documento; la revisión se identifica por
el commit que lo incorpora y su base. No publiques tokens, rutas del operador ni
trazas crudas TPM/IMA privadas. La continuidad compartida vive en Git, no en chat.
