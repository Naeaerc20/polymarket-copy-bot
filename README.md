# Polymarket Copy Trading Bot

Bot automatizado de copy-trading para Polymarket que replica las operaciones de traders específicos en tiempo real.

## 🚀 Características

- **Seguimiento múltiple de traders**: Monitorea varios traders desde un archivo JSON
- **Copia flexible**: Monto fijo o porcentaje del trade original
- **Tipos de orden**: Soporte para FOK (Fill or Kill) y FAK (Fill and Kill/market)
- **Autenticación L2**: Firma EIP-712 para transacciones seguras
- **Monitoreo en tiempo real**: Polling de la Data API para detectar trades nuevos
- **Configuración granular**: Control por trader de buys/sells y límites
- **Logging completo**: Archivos de log y estadísticas

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

### 1. Variables de entorno (.env)

Copia el archivo `.env.example` a `.env` y configura:

```bash
cp .env.example .env
```

Edita `.env`:

```env
# Tu private key (con prefijo 0x)
# NUNCA compartas este archivo ni lo subas a git
PRIVATE_KEY=0x...

# Tu dirección proxy de Polymarket
# Esta es la dirección que ves en tu perfil de polymarket.com
FUNDER_ADDRESS=0x...

# Tipo de firma:
# 0 = EOA (MetaMask estándar)
# 1 = POLY_PROXY (Magic Link / email login) - más común
# 2 = GNOSIS_SAFE (Gnosis Safe multisig)
SIGNATURE_TYPE=1

# Cantidad fija en USDC a copiar por trade
AMOUNT_TO_COPY=50

# Copiar ventas (true/false)
COPY_SELL=true

# Porcentaje del trade original a copiar (1-100)
# Si es "null", usa AMOUNT_TO_COPY
PERCENTAGE_TO_COPY=100

# Tipo de orden:
# FOK = Fill or Kill (límite, se ejecuta completa o no)
# FAK = Fill and Kill (mercado, ejecuta lo que pueda)
TYPE_ORDER=FOK
```

### 2. Configurar traders a seguir (config/traders.json)

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
3. Haz clic en un trader y copia su wallet address de la URL

## 🏃 Uso

### Modo normal
```bash
python main.py
```

### Modo de prueba (sin ejecutar trades)
```bash
python main.py --dry-run
```

### Con opciones
```bash
# Cantidad fija de $100 por trade
python main.py --amount 100

# Copiar 50% del tamaño del trade original
python main.py --percentage 50

# Usar órdenes de mercado
python main.py --order-type FAK

# Con archivo de log
python main.py --log-file logs/bot.log --log-level DEBUG
```

## 📁 Estructura del Proyecto

```
polymarket-copy-bot/
├── main.py                 # Punto de entrada principal
├── requirements.txt        # Dependencias Python
├── .env.example           # Template de configuración
├── config/
│   └── traders.json       # Lista de traders a seguir
├── src/
│   ├── auth.py            # Autenticación L1/L2
│   ├── trader_monitor.py  # Monitoreo de actividad
│   ├── order_executor.py  # Ejecución de órdenes
│   └── websocket_client.py # Cliente WebSocket
└── logs/                  # Archivos de log (opcional)
```

## 🔐 Autenticación

El bot usa un sistema de autenticación de dos niveles:

### Nivel 1 (L1) - Private Key
- Se usa una sola vez para derivar credenciales API
- Firma un mensaje EIP-712 para probar propiedad
- Las credenciales se guardan localmente

### Nivel 2 (L2) - API Credentials
- Credenciales HMAC-SHA256 (apiKey, secret, passphrase)
- Se usan para todas las operaciones de trading
- El private key sigue siendo necesario para firmar órdenes

## 📊 APIs de Polymarket

| API | Endpoint | Uso |
|-----|----------|-----|
| **Gamma API** | `https://gamma-api.polymarket.com` | Metadata de mercados, eventos |
| **CLOB API** | `https://clob.polymarket.com` | Trading, orderbook, precios |
| **Data API** | `https://data-api.polymarket.com` | Actividad de usuarios, posiciones |
| **WebSocket** | `wss://ws-subscriptions-clob.polymarket.com/ws/` | Datos en tiempo real |

## ⚠️ Riesgos y Advertencias

1. **Riesgo financiero**: El copy trading puede resultar en pérdidas
2. **Pérdida de fondos**: Errores en configuración pueden causar trades no deseados
3. **Latencia**: Puede haber delay entre el trade original y la copia
4. **Private key**: Nunca compartas tu private key
5. **Dinero real**: Siempre prueba con `--dry-run` primero

## 🛠️ Troubleshooting

### Error: "INVALID_SIGNATURE"
- Verifica que tu PRIVATE_KEY sea correcta
- Asegúrate de que empiece con `0x`
- Confirma que SIGNATURE_TYPE sea correcto

### Error: "Invalid Funder Address"
- Tu FUNDER_ADDRESS debe ser la dirección proxy de Polymarket
- Ve a polymarket.com/settings para verla
- Si no tienes proxy, debes loguearte primero en Polymarket

### Error: "Insufficient balance"
- Necesitas USDC en la red Polygon
- Verifica que tienes suficientes fondos en tu wallet proxy

### No se detectan trades
- Verifica que los traders estén habilitados en traders.json
- Los traders deben tener trades recientes (el bot monitorea actividad nueva)

## 📝 Logs

Los logs incluyen:
- Trades detectados con detalles completos
- Ejecuciones (exitosas y fallidas)
- Errores y stack traces
- Estadísticas al finalizar

## 🔄 Flujo de Trabajo

```
1. Bot inicia → Carga traders.json
2. Autentica con L1 → Deriva credenciales L2
3. Inicializa estado de traders → Obtiene últimos trades
4. Loop principal:
   ├── Poll Data API cada X segundos
   ├── Detecta nuevos trades
   ├── Calcula tamaño de copia
   └── Ejecuta orden (si aplica)
5. Al detener → Muestra estadísticas
```

## 🤝 Contribuir

1. Fork el repositorio
2. Crea una rama para tu feature
3. Envía un pull request

## 📄 Licencia

MIT License - ver archivo LICENSE

## 🔗 Recursos

- [Documentación de Polymarket](https://docs.polymarket.com/)
- [py-clob-client (Python SDK)](https://github.com/Polymarket/py-clob-client)
- [Polymarket Discord](https://discord.gg/polymarket)

---

**⚠️ Disclaimer**: Este bot es para fines educativos. El trading de predicciones implica riesgos significativos. Nunca inviertas más de lo que puedes permitirte perder. Los desarrolladores no se hacen responsables de pérdidas financieras.
