# Próximos pasos

La planificación vigente está en el [roadmap](development/roadmap.md), con
[estado comprobado](development/project-state.md) y [workflow](development/workflow.md).
MA-000 está integrado en `648ff3c`. [MA-010](development/tasks/MA-010.md) deja
la [ADR 0010](adr/0010-attestor-peer-binding.md) propuesta para revisión. El siguiente
trabajo recomendado es MA-011, extraer la frontera mínima de admisión, después
de integrar MA-010 y recibir su encargo. No iniciar automáticamente los siguientes
paquetes ni habilitar protegido a partir de una ADR sin implementación.

El [registro arena-admission/1](session-admission.md) ya está integrado en la base
`0c3dc77`; no hay que reimplementarlo. Su aplicación al FPS y el vínculo
attestor–peer siguen pendientes. Development continúa como único modo jugable,
sin fallback silencioso desde protegido. Pérdida de admisión no es sanción por cheat.

La etiqueta v0.1.0 y su [informe](validation-v0.1.0.json) son históricos. Nuevos
cambios necesitan evidencia propia; no reescribir la etiqueta ni usar ese informe
para certificarlos. LAN física, Quote/IMA y campaña humana tienen aceptación
separada de CI, pruebas locales y fixtures software.
