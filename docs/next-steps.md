# Próximos pasos

La planificación vigente está en el [roadmap](development/roadmap.md), con
[estado comprobado](development/project-state.md) y [workflow](development/workflow.md).
MA-000 está integrado en `648ff3c`. [MA-010](development/tasks/MA-010.md) y su
aceptación de la [ADR 0010](adr/0010-attestor-peer-binding.md) como base experimental
están integrados (cierre PR #2, `54c80f4`). [MA-011](development/tasks/MA-011.md)
también está integrado (PR #3, `1f86af9`): extrae la frontera development y el
contexto por conexión, con CI del HEAD y postmerge PASS.

[MA-012](development/tasks/MA-012.md) está IN_REVIEW: transporte interno mTLS/IPC
con endpoint ENet real, todavía sin permiso de juego. Ver su
[evidencia](development/ma-012-validation.md). No se ha publicado ni integrado.
El siguiente candidato es [MA-013](development/tasks/MA-013.md), después de integrar
MA-012 y recibir encargo: barrera inicial, aplicación de admisión y guard/epoch.
[MA-014](development/tasks/MA-014.md) completa lifecycle y mide revocación/pausas;
[MA-015](development/tasks/MA-015.md) valida LAN/TPM físicos. Sus fichas indican
pasos, dependencias y criterios. No arrancarlos automáticamente ni abrir protegido.

El [registro arena-admission/1](session-admission.md) ya está integrado en la base
`0c3dc77`; no hay que reimplementarlo. Su aplicación al FPS sigue pendiente; MA-012
demuestra sólo la asociación de transporte en un harness interno. Development continúa como único modo jugable,
sin fallback silencioso desde protegido. Pérdida de admisión no es sanción por cheat.

La etiqueta v0.1.0 y su [informe](validation-v0.1.0.json) son históricos. Nuevos
cambios necesitan evidencia propia; no reescribir la etiqueta ni usar ese informe
para certificarlos. LAN física, Quote/IMA y campaña humana tienen aceptación
separada de CI, pruebas locales y fixtures software.
