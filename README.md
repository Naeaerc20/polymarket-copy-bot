# Polymarket Copy Trading Bot

Bot automatizado de copy-trading para Polymarket que replica las operaciones de traders específicos en tiempo real.

## 🚀 Características

- **Seguimiento múltiple de traders**: Monitorea varios traders desde un archivo JSON
- **Copia flexible**: Monto fijo o porcentaje del trade original
- **Tipos de orden**: Soporte para FOK (Fill or Kill) y FAK (Fill and Kill/market)
- **Autenticación L2**: Firma EIP-712 para transacciones seguras
- **Monitoreo en tiempo real**: Solo copia trades NUEVOS (posteriores al inicio del bot)
- **Configuración granular**: Control por trader de buys/sells y límites
- **Setup automatizado**: Script de configuración que genera credenciales API

## 📋 Requisitos

- Python 3.9+
- Cuenta en Polymarket con USDC en Polygon
- Wallet address (proxy) y private key

## 🔧 Instalación

```bash
cd polymarket-copy-bot
pip install -r requirements.txt
```

## ⚙️ Configuración

### Paso 1: Ejecutar el Setup Wizard

```bash
python setup.py
```

El wizard te pedirá:
1. **Private Key**: Tu clave privada de wallet (con o sin 0x)
2. **Proxy Address**: Tu dirección de Polymarket (la que ves en tu portfolio)
3. **Signature Type**: 
   - `1` = Email/Google login (más común)
   - `0` = MetaMask estándar
   - `2` = Gnosis Safe
4. **Configuración de copy trading**: Monto fijo, porcentaje, tipo de orden, etc.

El setup automáticamente:
- ✓ Valida tus credenciales
- ✓ Deriva las API keys de Polymarket
- ✓ Guarda todo en `.env`
- ✓ Verifica la conexión

### Paso 2: Configurar traders a seguir

Edita `config/traders.json`:

```json
{
  "traders": [
    {
      "address": "0xdireccion_del_trader",
      "nickname": "TraderExperto",
      "enabled": true,
      "copy_buys": true,
      "copy_sells": true,
      "max_position_size": 500,
      "notes": "Top performer en mercados políticos"
    }
  ]
}
```

**Cómo encontrar traders para seguir:**
1. Ve a [Polymarket Leaderboard](https://polymarket.com/leaderboard)
2. Ordena por Profit o Volume
3. Haz clic en un trader y copia su wallet address de la URL o perfil

### Variables de entorno (.env)

El setup crea automáticamente este archivo:

```env
# === WALLET CREDENTIALS ===
PRIVATE_KEY=0x...

# Tu dirección proxy de Polymarket
FUNDER_ADDRESS=0x...

# Tipo de firma: 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE
SIGNATURE_TYPE=1

# === API CREDENTIALS (Auto-generated) ===
POLY_API_KEY=...
POLY_API_SECRET=...
POLY_API_PASSPHRASE=...

# === COPY TRADING SETTINGS ===
AMOUNT_TO_COPY=50          # Cantidad fija en USDC
COPY_SELL=true             # Copiar ventas
PERCENTAGE_TO_COPY=100     # Porcentaje del trade original (o "null")
TYPE_ORDER=FOK             # FOK o FAK
MIN_TRADE_SIZE=10          # Mínimo en USDC
MAX_TRADE_SIZE=1000        # Máximo en USDC
POLL_INTERVAL=5            # Segundos entre verificaciones
```

## 🏃 Uso

### Modo de prueba (recomendado primero)
```bash
python main.py --dry-run
```

### Modo normal
```bash
python main.py
```

### Con opciones
```bash
# Cantidad fija de $100 por trade
python main.py --amount 100

# Copiar 50% del tamaño del trade original
python main.py --percentage 50

# Usar órdenes de mercado (FAK)
python main.py --order-type FAK

# Con logging detallado
python main.py --log-level DEBUG
```

## 📁 Estructura del Proyecto

```
polymarket-copy-bot/
├── setup.py               # Setup wizard (ejecutar primero)
├── main.py                # Punto de entrada principal
├── requirements.txt       # Dependencias Python
├── .env                   # Configuración (generado por setup.py)
├── config/
│   └── traders.json       # Lista de traders a seguir
├── src/
│   ├── auth.py            # Autenticación L1/L2
│   ├── trader_monitor.py  # Monitoreo de actividad
│   ├── order_executor.py  # Ejecución de órdenes
│   ├── websocket_client.py # Cliente WebSocket
│   └── utils.py           # Utilidades
└── logs/                  # Archivos de log
```

## 🔐 Autenticación

El bot usa un sistema de dos niveles:

### Nivel 1 (L1) - Private Key
- Se usa una sola vez para derivar credenciales API
- Firma un mensaje EIP-712 para probar propiedad
- Las credenciales se guardan en `.env` y `credentials.json`

### Nivel 2 (L2) - API Credentials
- Credenciales HMAC-SHA256 (apiKey, secret, passphrase)
- Se usan para todas las operaciones de trading
- El private key sigue siendo necesario para firmar órdenes

## 📊 APIs de Polymarket

| API | Endpoint | Uso |
|-----|----------|-----|
| **Gamma API** | `https://gamma-api.polymarket.com` | Metadata de mercados |
| **CLOB API** | `https://clob.polymarket.com` | Trading, orderbook |
| **Data API** | `https://data-api.polymarket.com` | Actividad de usuarios |

## ⚠️ Riesgos y Advertencias

1. **Riesgo financiero**: El copy trading puede resultar en pérdidas
2. **Private key**: Nunca compartas tu private key ni subas `.env` a git
3. **Latencia**: Puede haber delay entre el trade original y la copia
4. **Dinero real**: Siempre prueba con `--dry-run` primero

## 🛠️ Troubleshooting

### Error: "Could not create/derive api key"
- Verifica que tu PRIVATE_KEY sea correcta
- Asegúrate de que el FUNDER_ADDRESS sea tu dirección proxy de Polymarket
- Confirma que SIGNATURE_TYPE sea correcto (1 para Email/Google login)

### Error: "Invalid signature"
- SIGNATURE_TYPE incorrecto: usa 1 para cuentas de Email/Google

### Error: "Insufficient balance"
- Necesitas USDC en la red Polygon en tu wallet proxy

### El bot detecta trades antiguos
- El bot solo copia trades NUEVOS (posteriores a su inicio)
- Los trades existentes se marcan como "vistos" durante la inicialización

### No se detectan trades nuevos
- Verifica que los traders tengan `enabled: true` en traders.json
- Revisa que los traders tengan actividad reciente

## 📝 Logs

```bash
# Ver logs en tiempo real
tail -f logs/bot.log

# Con nivel DEBUG para más detalle
python main.py --log-level DEBUG
```

## 🔄 Flujo de Trabajo

```
1. Ejecutar setup.py → Genera .env con credenciales
2. Editar traders.json → Agregar traders a seguir
3. Ejecutar main.py --dry-run → Probar sin ejecutar trades
4. Ejecutar main.py → Bot en funcionamiento
   ├── Bot marca trades existentes como "vistos"
   ├── Loop: Poll Data API cada X segundos
   ├── Detecta trades NUEVOS (timestamp > inicio)
   ├── Calcula tamaño según configuración
   └── Ejecuta orden (si aplica)
```

## 🤝 Contribuir

1. Fork el repositorio
2. Crea una rama para tu feature
3. Envía un pull request

## 📄 Licencia

MIT License

## 🔗 Recursos

- [Documentación de Polymarket](https://docs.polymarket.com/)
- [py-clob-client (Python SDK)](https://github.com/Polymarket/py-clob-client)
- [Polymarket Discord](https://discord.gg/polymarket)

---

**⚠️ Disclaimer**: Este bot es para fines educativos. El trading de predicciones implica riesgos significativos. Nunca inviertas más de lo que puedes permitirte perder.
