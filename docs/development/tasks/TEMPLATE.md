# MA-xxx — Título concreto

- Estado: BACKLOG (READY sólo con dependencias integradas).
- Prioridad / tamaño: P0–P3 / S–L.
- Objetivo observable:
- Rama: tipo/ma-xxx-descripcion-kebab-case.
- Base: origin/main actualizado; SHA completo al iniciar.
- Dependencias: IDs y evidencia de integración.
- Git: commit local y PR preparada; sin push/PR remota/merge/release salvo autorización explícita.

## Alcance

Incluir comportamiento, pruebas y docs necesarios. Excluir mejoras independientes.
Registrar qué existe ya en HEAD y qué falta; no rehacer trabajo incorporado.

## Criterios de aceptación

1. Resultado observable y prueba del camino normal.
2. Errores, límites y regresión relevantes.
3. Contratos, inventario, documentación y límites de evidencia coherentes.

## Plan y validación

Entorno/dependencias disponibles; comandos con timeout cuando corresponda.
Por comprobación: revisión/base + diff, fecha, entorno, resultado PASS/FAIL/BLOCKED,
artefacto saneado y alcance (lectura, software, headless, render, LAN o TPM físico).
No atribuir resultados históricos a este diff.

## Decisiones y entrega

ADR afectadas, cambios y motivos; evidencia comprobada, inferencias y pendientes.
Riesgos, rollback, bloqueos con acción concreta. Rama/commit y PR real o título/cuerpo
preparados. Próxima acción. Actualizar estado/roadmap; DONE sólo después de merge.
