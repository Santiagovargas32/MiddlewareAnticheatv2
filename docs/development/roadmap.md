# Roadmap por paquetes

Base contrastada: `0c3dc77bd8e4aa12112e95d7bb7877620be89334`, igual a origin/main
tras fetch al iniciar MA-000. Propuesta inicial de la guía de 16-09-2026, revalidada
por lectura del código; no es certificación runtime. [Estado y evidencia](project-state.md).
P0 bloquea el hito protegido, no implica vulnerabilidad explotable. S/M/L es
complejidad relativa. Cada ID representa una rama/PR, no una issue ya creada.

Único paquete activo: [MA-000](tasks/MA-000.md). Siguiente: [MA-010](tasks/MA-010.md)
tras integración y encargo. Todos los demás están BACKLOG; no se implementan en
esta entrega. READY requiere dependencias integradas y ficha revisada según el
[workflow](workflow.md). Las ramas siguientes conservan los nombres propuestos;
se revalidan al encargar cada paquete.

## Preparación y P0 — Admisión

| ID / rama | Dependencias | Aceptación principal | Tamaño / estado |
| --- | --- | --- | --- |
| MA-000 · `docs/ma-000-development-workflow` | Ninguna | Instrucciones públicas, workflow, roadmap, estado, plantillas y guías presentes en clone/paquete limpios; privados excluidos | M / IN_REVIEW |
| MA-010 · `docs/ma-010-admission-design` | MA-000 | ADR de identidad/posesión, transporte/IPC, estados, renovación, presupuesto de revocación y pruebas negativas | M / BACKLOG |
| MA-011 · `refactor/ma-011-admission-boundary` | MA-010 | Extraer sólo frontera necesaria; development equivalente y protegido rechazado | M / BACKLOG |
| MA-012 · `feat/ma-012-authenticated-peer-binding` | MA-011 | Binding con peer real; certificado ajeno, sustitución, replay y reconexión; protegido cerrado hasta lifecycle | L / BACKLOG |
| MA-013 · `feat/ma-013-admission-enforcement` | MA-012 | Permiso server-side para ready/spawn/intenciones; limpiar efectos pendientes; ausente/negado/expirado/servicio caído no concede juego | L / BACKLOG |
| MA-014 · `feat/ma-014-trust-lifecycle` | MA-013 | Renovación/suspensión/revocación, restart/timeout/instancia, límite absoluto; respuestas tardías descartadas y ventana medida; protegido sólo tras E2E | L / BACKLOG |
| MA-015 · `test/ma-015-fedora-lan-attestation` | MA-014 | Dos Fedora físicos, identidad configurada, Quote/IMA según política y revocación en partida; aceptación física BLOCKED si falta hardware | M / BACKLOG |

H1: protegido experimental con contrato comprobado en software; aceptación física
separada. El registro mTLS de admisión ya existe: no rehacer PR #1. En la base,
lease 30 s, desafío 10 s y binding absoluto 300 s; renovar suspende el permiso y
no hay push de revocación. Resolverlos explícitamente en MA-010/014. Si L es
demasiado amplio, subdividir con nuevos IDs antes de implementar.

## P1 — Fiabilidad, red y detector

| ID / rama | Dependencias | Aceptación principal | Tamaño |
| --- | --- | --- | --- |
| MA-020 · `fix/ma-020-round-state-lifecycle` | MA-000 | Reproducir dos rondas; definir alcance de score/previous/alert_sent, respawn/revancha/desconexión y replay; no reset arbitrario | M |
| MA-021 · `test/ma-021-network-baseline` | MA-000 | RTT/jitter/pérdida/bytes y coste tick/detector con 2/4/8 clientes automatizados; LAN humana separada y matriz repetible | M |
| MA-022 · `fix/ma-022-rpc-resource-bounds` | MA-021 | Caracterizar tráfico sin permiso, ráfagas y agotamiento; límites de coste/frecuencia/tamaño/colas/logs | M |
| MA-023 · `feat/ma-023-client-prediction` | MA-021 y contrato de movimiento estable | Secuencia/ack, historial limitado, reconciliación, colisión/salto/muerte/respawn/pérdida; autoridad conservada | L |
| MA-024 · `feat/ma-024-snapshot-interpolation` | MA-021; coordinar contrato MA-023 | Buffer temporal, discontinuidades y extrapolación limitada; comparación medida | M |
| MA-025 · `test/ma-025-human-detector-evaluation` | MA-020 y MA-021 | Ronda/tick rate, etiquetas externas, sesiones consentidas, calibración/evaluación separadas por jugador/sesión; incertidumbre y falsos negativos | L |
| MA-026 · `fix/ma-026-host-readiness` | MA-000 | Reproducir carrera; si existe, readiness acotado/cancelable; puerto ocupado, inicio lento y cierre del anfitrión | S |
| MA-027 · `ci/ma-027-validation-evidence` | MA-000 | Evidencia nueva por SHA/configuración, smoke desde extracción limpia e integración/Fedora viable conservando gates | M |

H2: partidas reproducibles y evaluación medible. MA-020/021/026/027 son candidatos
independientes si MA-015 queda bloqueado por hardware, sólo con nuevo encargo.
Matriz propuesta (no medida): RTT añadido 0/40/100 ms, jitter 0/10/30 ms, pérdida
0/1/3 %, duplicación/reordenación. Perturbar recursos de prueba, nunca la interfaz
de administración. Medir antes de optimizar. No interpretar siempre 12 ticks como
200 ms. Conservar LOG_ONLY/WARN y separar ground truth del detector.

## P2 — Opcionales tras los hitos anteriores

| ID / rama | Dependencia o condición | Aceptación principal |
| --- | --- | --- |
| MA-030 · `feat/ma-030-bounded-lag-compensation` | MA-021/023/024 | Historial y rewind servidor acotados; validar tiempos/cobertura/paredes sin aceptar hits del cliente |
| MA-031 · `feat/ma-031-operator-diagnostics` | Necesidad operativa medida; fijar dependencias al encargar | Cuotas/rotación, estado y razones de rechazo, recuperación y correlación sin identidades privadas |
| MA-032 · `feat/ma-032-session-usability` | Elegir subpaquete y dependencias al encargar | Una mejora: reconexión con identidad nueva, favoritos LAN o lobby; sin matchmaking/Internet implícitos |
| MA-033 · `refactor/ma-033-match-domain` | Fricción demostrada y baseline | Extracción mínima de combate/partida/telemetría conservando contratos |
| MA-034 · `build/ma-034-release-distribution` | Fijar revisión objetivo y dependencias al encargar | Paquete versionado, extracción limpia, lanzadores, actualización y dependencias fijadas; binario opcional posterior |

## P3 — HUD, feedback, assets, físicas y una arena

| ID / rama | Dependencias | Aceptación principal |
| --- | --- | --- |
| MA-040 · `docs/ma-040-art-direction` | MA-000 | Proponer arena industrial de entrenamiento, paleta/contraste/señalética y presupuestos; dirección aún no aprobada |
| MA-041 · `feat/ma-041-hud-and-menus` | MA-040 | Vida/munición/retícula/recarga/resultados, diagnóstico opcional, alerta comprensible, perfil inequívoco; teclado/resize y capturas 1080p/720p |
| MA-042 · `build/ma-042-asset-pipeline` | MA-040 | Formatos explícitos necesarios, licencia/origen/autor/cambios/peso; pruebas de omisiones/symlinks/privados y separación caché |
| MA-043 · `feat/ma-043-weapon-feedback` | MA-041/042 | Una malla/arma, animaciones y audio propios/licenciados; efectos no alteran cadencia/impactos |
| MA-044 · `feat/ma-044-movement-physics` | MA-021/023 | Ajuste acotado y coherente con servidor/predicción; bordes/colisión/salto/pendientes y ventaja FPS/tick rate |
| MA-045 · `feat/ma-045-map-resource-contract` | MA-042 | ID/versión, colisión y spawns autoritativos, rechazo mismatch y arena original como fixture |
| MA-046 · `feat/ma-046-training-arena` | MA-040/042/044/045 | Una arena cuidada, cobertura/rutas/luz/audio; recorridos/spawns/visibilidad/física con 2–8 jugadores |
| MA-047 · `perf/ma-047-visual-performance` | MA-043/046 | Frame p50/p95/p99, draw calls, memoria y coste servidor; partículas/luces/colisión acotadas |

H3: arrancar, jugar, entender alertas y repetir ronda con una arena/arma terminadas.
UI funcional necesaria para un paquete se corrige dentro de él; rediseño estético
va separado. Objetivos provisionales: 60 FPS a 1080p y 60 ticks/s con margen sobre
16,67 ms; requieren hardware de referencia/baseline, no son garantías actuales.
No exigir determinismo bit a bit sin evidencia. Licencia del código propio queda
a decisión del titular; origen/licencia de assets se registra por separado.

Fuera de estos hitos: ranking/cuentas globales, backend distribuido, ML sin dataset,
mundo abierto, vehículos, muchos modos, cambio de motor, compatibilidad con
anticheats ajenos y runtime Windows como requisito Linux.
