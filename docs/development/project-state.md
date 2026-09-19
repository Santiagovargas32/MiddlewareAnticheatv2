# Estado del proyecto

Registro MA-000, 2026-09-19. Rama `docs/ma-000-development-workflow`.
Base/último runtime examinado: `0c3dc77bd8e4aa12112e95d7bb7877620be89334`;
origin/main coincide tras fetch. No se modifica runtime ni etiqueta v0.1.0.
La revisión de metodología es el commit que incorpora este documento, no un SHA
inventado de sí mismo. CI histórica no valida este diff.

Paquete activo: [MA-000](tasks/MA-000.md), IN_REVIEW. Siguiente candidato:
[MA-010](tasks/MA-010.md), BACKLOG hasta integrar MA-000 y recibir el encargo.
[Roadmap](roadmap.md) es la única lista de prioridades; el juego sigue development.

## Contraste de la guía con la base

Lectura de código actual, no aceptación física ni auditoría exhaustiva:

| Hallazgo | Evidencia / clasificación | Consecuencia |
| --- | --- | --- |
| Admisión existente sin aplicación al FPS | [registro](../../scripts/session_admission.py) y `host`/`hello` en [network](../../game/scripts/network.gd): protegido rechazado | Confirmado por lectura; MA-010–014 integran, no rehacen |
| mTLS no autentica automáticamente ENet | Registro Python TLS y peer Godot independientes; [contrato](../game-network-protocol.md) | Falta diseño attestor–conexión; MA-010 |
| Lease/renovación/revocación | `AdmissionRegistry`: lease 30 s desde challenge, binding 300 s, CHALLENGED suspende; status por consulta sin push | Confirmado por lectura; ventana de aplicación FPS aún sin medir |
| Autoridad y movimiento | `network.gd`, [pawn](../../game/scripts/pawn.gd): servidor simula/raycast; cliente interpola | Sin predicción/reconciliación; medir en MA-021 antes de MA-023/024 |
| Detector entre rondas | `ready_request` reinicia kills/deaths/respawn sin recrear detector; score/previous/alert_sent por peer | Persistencia observable en código; reproducción de dos rondas y decisión en MA-020, no bug certificado |
| Inicio HOST | [main](../../game/scripts/main.gd): espera fija 0,8 s | Riesgo inferido; carrera pendiente de reproducir en MA-026 |
| Ventana estadística | [análisis](../../tools/analyze_match.py): exclusión de 12 ticks, tick rate configurable | Confirmado por lectura; metadatos temporales/evaluación en MA-025 |
| Detector y datasets | [aim_detector](../../game/scripts/aim_detector.gd) sin toggle; [humanos pendientes](../../datasets/normal/README.md) | Sin precisión humana demostrada; LOG_ONLY/WARN |
| Visuales/arquitectura | [pawn](../../game/scripts/pawn.gd) usa cápsula/arma prismática; Godot y laboratorio C independientes | Descripción por lectura, sin nueva evaluación estética |
| Inventario y continuidad | [release_files](../../tools/release_files.py), .gitignore en base: AGENTS privado, game sin PNG/GLB/OGG/WAV/TRES | MA-000 publica sólo guías; formatos de assets quedan para MA-042 |
| CI y licencia | [workflow CI](../../.github/workflows/ci.yml) conserva gates; [README](../../README.md) sin licencia de reutilización | No se consulta CI remota nueva ni se elige licencia |

## Cambios y evidencia de MA-000

Instrucciones públicas saneadas, workflow, roadmap, fichas MA-000/MA-010,
plantillas de tarea/PR/ADR y registro ADR. Próximos pasos enlaza la planificación.
AGENTS original conservado íntegro en almacenamiento local ignorado, fuera del
inventario público. Sólo se retira su exclusión concreta y se añaden dos rutas
explícitas al inventario; no se amplían formatos de assets.

Validación local del cambio MA-000 sobre la base anterior, Fedora 44, Python
3.14.7 y Godot 4.7.2 estable:

| Comprobación | Resultado real / alcance |
| --- | --- |
| `python3 scripts/verificar-documentacion.py` | PASS: 137 archivos públicos, 90 enlaces locales |
| `python3 tools/verify_release.py` | PASS: 6/6 grupos; incluye 29 checks Godot y 6 casos de red con procesos loopback headless |
| Intento inicial en sandbox | BLOCKED por socket UDP EPERM; resuelto al ejecutar el mismo gate con permisos locales, sin modificar pruebas |
| `python3 tools/package_game.py --output <temporal>/review.tar.gz` y extracción vacía | PASS: 137 fuentes + PACKAGE.json; hashes SHA256, guías, lanzadores ejecutables y ausencia de privados comprobados |
| Clone local del commit MA-000, sin hardlinks | PASS: árbol limpio, 137 fuentes iguales al inventario y verificador documental aprobado; no prueba descarga de GitHub |
| Inventario/staging/ignores y `git diff --check` | PASS: sólo 13 rutas del paquete; original privado íntegro por SHA256; sin cambios de runtime/CI |

Logs locales del gate en `results/release-checks/`; el intento bloqueado se
conserva por separado en almacenamiento ignorado. Los cambios finales de estado
son documentales: se comprueban nuevamente enlaces, paquete y clone, sin repetir
la suite runtime ya verde. No se ejecutaron nuevas pruebas C/TPM, render, LAN
física ni campaña humana; no son necesarias para este diff y no se afirma esa
evidencia. No hay bloqueo pendiente de MA-000 ni CI remota nueva.

## Riesgos, rollback y próximo paso

Riesgo principal: guías o plantillas omitidas de clones/paquetes, o publicación
accidental de material local. Verificar inventario, ignores y contenido staged.
Rollback: revertir el commit MA-000 en una rama de corrección, previa autorización
si ya integrado; restaurar conjuntamente inventario y documentación. No cambia
estado del juego/TPM ni exige migración. No borrar la copia privada original.

MA-000 queda IN_REVIEW con commit local (consultar `git log -1 --oneline`) y
[título/cuerpo de PR preparados](tasks/MA-000.md#pr-preparada). No se hizo
push, PR remota ni merge; main y v0.1.0 conservan sus referencias.
Próximo paso de revisión: `git diff origin/main...HEAD`. Después de integración
autorizada, encargar MA-010; su primer comando Git será `git fetch origin main`.
No se ha empezado su ADR ni ningún otro paquete.
