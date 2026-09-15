# Continuación desde v0.1.0

La base publicada conserva un commit inicial y la etiqueta `v0.1.0`. Los siguientes
incrementos se desarrollan en ramas cortas con diff revisable, pruebas pertinentes
y propuesta de cambio hacia `main`; no reescribir esa versión. Etiquetar otra
versión cuando cumpla sus criterios, con evidencia propia. El informe
[validation-v0.1.0.json](validation-v0.1.0.json) describe exclusivamente la base
publicada y no se reutiliza como certificación de nuevos fuentes.

| Orden | Incremento | Estado / criterio de aceptación |
| --- | --- | --- |
| 1 | Registro de admisión por conexión y TLS mutuo | Implementado en esta rama; probar aislamiento por certificado, partida, peer y conexión, caducidad, replay y revocación concurrente. Ver [protocolo](session-admission.md). |
| 2 | Integración attestor–servidor–Godot | Pendiente. Vincular la identidad del attestor a una conexión autenticada del juego; un jugador sin permiso no puede entrar ni enviar intenciones válidas. Probar suplantación y sustitución de conexión. |
| 3 | Renovación y pérdida de confianza durante partida | El registro ya caduca/revoca; falta aplicación en el juego. Probar vencimiento, verificador caído, desconexión, reinicio y revocación durante una partida; ninguna respuesta tardía debe reactivar un peer anterior. |
| 4 | Atestación física y LAN en dos Fedora | Pendiente del entorno del operador. Capturar Quote/IMA real, decidir política de mediciones y enrollment, y ejecutar la guía LAN con ambos hosts. Separar firma válida, referencia aprobada e identidad hardware. |
| 5 | Calidad de red y movimiento | Medir primero RTT, jitter, pérdida y bytes/s; después predicción/reconciliación y compensación de latencia conservando autoridad del servidor. Pruebas con pérdida, retraso y reordenación controlados. |
| 6 | Detector y campaña humana | Recoger sesiones normales consentidas y etiquetadas fuera de las entradas del detector. Medir falsos positivos y negativos, latencia y coste; mantener LOG_ONLY/WARN hasta tener evidencia suficiente. |

Antes de completar 2 y 3, `--development` sigue siendo el único modo jugable.
Un permiso del servicio es una decisión del experimento de AK fijada por operador;
no demuestra integridad completa del host ni ausencia de cheats. La integración
no debe convertir un fallo TPM en sanción automática ni degradar silenciosamente
una sesión protegida a development.

Para contribuir: mantener cambios pequeños por comportamiento, conservar contratos
y no añadir credenciales o resultados privados. Ejecutar la suite afectada y
documentar tanto el resultado como lo que falta comprobar. La revisión deberá
incluir problema, comportamiento nuevo y pruebas; CI complementa las pruebas
locales y no sustituye la aceptación física o humana.
