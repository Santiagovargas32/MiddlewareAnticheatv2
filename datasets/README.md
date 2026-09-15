# Sesiones controladas

`aimbot/` contiene trazas reales del servidor Godot con dos clientes automatizados
locales. **No son sesiones humanas ni pruebas LAN física/TPM.** El ground truth se
guarda separado y sólo se une después de ejecutar el detector.

- `continuous`: ambos clientes con seguimiento continuo interno. No hubo alerta;
  máximos ~18/100 con umbral 75. Es un negativo del detector, no una prueba de
  ausencia de simulación. Se conserva únicamente el prefijo JSONL completo.
- `snap-cycle`: ambos con adquisición repetida habilitada (0.25 s fuera de objetivo
  por ciclo de 0.8 s), además de seguimiento. Ambos alcanzaron 100 y se emitieron
  alertas. Latencias aproximadas observadas: 540 y 780 ticks a 60 Hz (9 y 13 s),
  incluyendo adquisición/movimiento y la incertidumbre de snapshots.

`normal/` está pendiente de sesiones humanas etiquetadas. No presentar FP=0 por
falta de negativos como una tasa validada de falsos positivos. Se debe separar
calibración de evaluación y conservar tamaño muestral y configuración.

Reproducir análisis:

```bash
python3 tools/analyze_match.py datasets/aimbot/snap-cycle.jsonl \
 --ground-truth datasets/aimbot/snap-cycle-A.jsonl \
 --ground-truth datasets/aimbot/snap-cycle-B.jsonl
```

Configuración usada: Godot 4.7.2, 60 Hz, snapshots 20 Hz, aim-v1, threshold 75,
WARN, clientes automatizados. Detector observa únicamente yaw/pitch, error,
objetivo visible y delta; el replay ignora el score almacenado y lo recalcula.
Los IDs son aleatorios de sesión; no se incluyen nombres de usuario del host ni
claves. Son muestras mínimas de ingeniería, no evidencia estadística general.
