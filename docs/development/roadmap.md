# Roadmap por paquetes

Base actual de planificación: `648ff3c06efbadd554cf199c05e16b0663c11af0`,
origin/main actualizado al iniciar MA-010. MA-000 está integrado por ancestry Git;
no se infiere una PR. La propuesta inicial de 16-09-2026 se contrastó con código,
y MA-010 concreta admisión en la [ADR 0010](../adr/0010-attestor-peer-binding.md).
[Estado y evidencia](project-state.md). P0 bloquea el hito protegido, no implica
vulnerabilidad explotable. S/M/L es complejidad relativa, no duración.

MA-010 documental está DONE: `9c4f787` integrado, con aceptación experimental del
titular y cierre integrado por PR #2 (`54c80f4`). [MA-011](tasks/MA-011.md) está
DONE por PR #3 (`1f86af9`), integración comprobada. [MA-012](tasks/MA-012.md) es el
siguiente candidato READY con dependencias/ficha, sin iniciar y sin autorización
de implementación en este encargo. Los posteriores quedan BACKLOG.
READY exige dependencias integradas y ficha según el [workflow](workflow.md).
Los IDs representan paquetes/rama/PR previstos, no issues ya creadas.

## Preparación y P0 — Admisión

| ID / rama | Dependencias | Aceptación principal | Tamaño / estado |
| --- | --- | --- | --- |
| MA-000 · `docs/ma-000-development-workflow` | Ninguna | Instrucciones públicas, workflow, roadmap, estado, plantillas y guías presentes en clone/paquete limpios; privados excluidos | M / DONE |
| MA-010 · `docs/ma-010-admission-design` | MA-000 | ADR de identidad/posesión, transporte/IPC, estados, renovación, presupuesto de revocación y pruebas negativas | M / DONE |
| [MA-011](tasks/MA-011.md) · `refactor/ma-011-admission-boundary` | MA-010 | Extraer frontera de permiso/transporte y contexto; development equivalente, protegido rechazado (ADR 0010) | M / DONE |
| [MA-012](tasks/MA-012.md) · `feat/ma-012-authenticated-peer-binding` | MA-010/011 integrados | Túnel mTLS completo, IPC y binding con endpoint real; certificado ajeno, replay, reconexión y recursos; protegido cerrado | L / READY, sin iniciar |
| MA-013 · `feat/ma-013-admission-enforcement` | MA-012 | Barrera inicial, RPC protegido, guard/epoch para ready/spawn/intenciones y limpieza; fallo cerrado; sin apertura pública aún | L / BACKLOG |
| MA-014 · `feat/ma-014-trust-lifecycle` | MA-013 | Renovación/suspensión/revocación, restart/timeout/instancia, límite absoluto; respuestas tardías descartadas y ventana medida; protegido sólo tras E2E | L / BACKLOG |
| MA-015 · `test/ma-015-fedora-lan-attestation` | MA-014 | Dos Fedora físicos, identidad configurada, Quote/IMA según política y revocación en partida; aceptación física BLOCKED si falta hardware | M / BACKLOG |

H1: protegido experimental con contrato comprobado en software; aceptación física
separada. El registro mTLS de admisión ya existe: no rehacer PR #1. En la base,
lease 30 s, desafío 10 s y binding absoluto 300 s; renovar suspende el permiso y
no hay push de revocación. ADR 0010 propone renovación suspendida con barrera
CHALLENGED, rollover a 270 s
y frescura local de 750 ms con objetivo de retirada ≤800 ms; implementación y
medición pendientes en MA-014. No son resultados runtime. Si L es
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
