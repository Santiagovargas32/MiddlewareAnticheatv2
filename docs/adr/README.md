# Decisiones de arquitectura

Usar `NNNN-titulo-kebab-case.md` con la [plantilla](TEMPLATE.md) cuando cambien
contratos, responsabilidades o fronteras de confianza. Estados: propuesta,
aceptada o sustituida; una ADR propuesta no autoriza habilitar protegido.

| ADR | Estado | Paquete |
| --- | --- | --- |
| [0010 — Enlace attestor–peer](0010-attestor-peer-binding.md) | Propuesta para revisión; sin implementación protegida | [MA-010](../development/tasks/MA-010.md) |

MA-000 estableció este registro. MA-010 propone túnel mTLS para todo ENet,
correlación de peer real, IPC y lifecycle. La propuesta no habilita protegido.
Contratos públicos existentes: [red Godot](../game-network-protocol.md),
[admisión](../session-admission.md), [UDP C / decisión 0002](../lab-udp-protocol.md)
y [TPM](../tpm-attestation.md). Conservarlos; no copiar decisiones locales privadas.
El prefijo 0010 evita colisión con la decisión histórica 0002; el número de ADR
no implica aceptación ni integración del paquete.
