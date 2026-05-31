# ADR-004: Proveedor de datos de mercado

**Estado:** propuesto (se firma en Fase 1)
**Fecha:** <YYYY-MM-DD>
**Tags:** tools, proveedores, datos-de-mercado

## Contexto y problema

La tool `get_market_data(ticker)` devuelve datos de mercado precisos de la empresa: precio, variación del día, market cap, PER, forward PER, EPS, dividend yield, rango de 52 semanas. Son números volátiles y precisos que `web_search` no resuelve bien (devuelve prosa que puede estar desactualizada o ser inconsistente entre fuentes). La elección del proveedor afecta a la fricción de credenciales, al coste, a la cobertura y a la estabilidad.

## Drivers de la decisión

- Fricción mínima: el repo es de referencia didáctica; una API key añade fricción al alumno que lo clona.
- Coste cero o muy bajo para un proyecto de referencia.
- Cobertura de empresas cotizadas, USA y europeas.
- Datos homogéneos: una sola estructura de salida.

## Opciones consideradas

- A. `yfinance` (Yahoo Finance no oficial): librería de Python, sin API key, gratis. Cubre precio, PER, forward PER, EPS, market cap, dividend yield, máximos/mínimos de 52 semanas.
- B. Financial Modeling Prep (FMP): fundamentos, ratios, históricos. Plan de pago, requiere API key.
- C. Alpha Vantage: market data e indicadores. Free tier limitado con API key, premium caro.

## Decisión

Opción A. `yfinance`. Cero fricción de credenciales y coste cero, que es lo que pide un repo de referencia. Cubre todos los campos del `MarketData` del schema del dossier. La tool `get_market_data(ticker)` filtra `Ticker.info` a un objeto homogéneo y compacto; los campos sin dato van `null`.

Que `yfinance` sea no oficial y pueda romper o limitar se asume como riesgo conocido: motiva el manejo de "error del proveedor como dato" (ver Spec 02 y Spec 04). Un fallo de `yfinance` devuelve `{"error": ..., "recoverable": true}` y el loop sigue.

En CI, el set de evaluación no llama a `yfinance` en vivo: las llamadas a datos de mercado se graban como fixtures deterministas (cassettes o un dataset cacheado de `MarketData`), para que el gate de cada PR no dependa de que Yahoo Finance esté disponible ni aplique rate limiting ese día. Las llamadas en vivo se reservan a un job programado (ver Spec 07 y Spec 08).

## Consecuencias

### Positivas

- Sin API key: el alumno clona y ejecuta sin dar de alta cuentas ni gestionar secretos.
- Coste cero en datos de mercado; el coste del proyecto queda en la API del modelo.
- Datos homogéneos para empresas de distintas geografías.

### Negativas

- `yfinance` es no oficial: puede romper, cambiar campos o aplicar rate limiting sin aviso. Mitigado con errores como dato y manejo de fallo del proveedor.
- Calidad y cobertura dependen de Yahoo Finance, sin SLA.
- Cobertura europea desigual: para empresas no estadounidenses, campos como `forward_pe` o `dividend_yield` vienen `null` más a menudo. El schema ya los hace opcionales, y las expectativas de completitud del dossier y del set de evaluación para empresas europeas cuentan con más `null`.

## Alternativas descartadas

- FMP: datos más completos y con SLA, descartado por la fricción de API key de pago en un repo de referencia. Queda como upgrade documentado si el caso pasa a producción real.
- Alpha Vantage: free tier demasiado limitado para el set de evaluación; premium caro frente a `yfinance` gratis.
