import os
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, render_template_string
import logging

# Importar tu bot
from flight_bot.flight_bot import FlightBot, ROUTES_TO_MONITOR

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Variables globales
bot_instance = None
last_run = None
total_deals = 0
last_deals = []

# Template HTML simple
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Flight Deal Bot Status</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .status {
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
            font-weight: bold;
        }
        .running { background: #d4edda; color: #155724; }
        .stopped { background: #f8d7da; color: #721c24; }
        .deal {
            background: #f8f9fa;
            padding: 15px;
            margin: 10px 0;
            border-radius: 8px;
            border-left: 4px solid #007bff;
        }
        .price { font-size: 1.2em; font-weight: bold; color: #28a745; }
        .route { font-size: 1.1em; color: #007bff; }
        h1 { color: #333; text-align: center; }
        h2 { color: #666; border-bottom: 2px solid #eee; padding-bottom: 10px; }
        .refresh { 
            text-align: center; 
            margin: 20px 0;
        }
        .refresh a {
            background: #007bff;
            color: white;
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 5px;
        }
    </style>
    <script>
        // Auto refresh cada 30 segundos
        setTimeout(() => location.reload(), 30000);
    </script>
</head>
<body>
    <div class="container">
        <h1>🛫 Flight Deal Bot Dashboard</h1>
        
        <div class="status {{ 'running' if bot_running else 'stopped' }}">
            Status: {{ 'RUNNING' if bot_running else 'STOPPED' }}
        </div>
        
        <div class="refresh">
            <a href="/">🔄 Refresh</a>
            <a href="/run-now">▶️ Run Now</a>
            <a href="/api/status">📊 API Status</a>
        </div>
        
        <h2>📈 Statistics</h2>
        <p><strong>Last Run:</strong> {{ last_run or 'Never' }}</p>
        <p><strong>Total Deals Found:</strong> {{ total_deals }}</p>
        <p><strong>Monitored Routes:</strong> {{ routes|length }}</p>
        
        <h2>🎯 Monitored Routes</h2>
        <ul>
        {% for route in routes %}
            <li>{{ route[0] }} → {{ route[1] }}</li>
        {% endfor %}
        </ul>
        
        {% if last_deals %}
        <h2>🔥 Recent Deals</h2>
        {% for deal in last_deals %}
        <div class="deal">
            <div class="route">{{ deal.origin }} → {{ deal.destination }}</div>
            <div class="price">${{ deal.price }}</div>
            <div>✈️ {{ deal.airline }} | 📅 {{ deal.departure_date }}</div>
            <div>🔍 {{ deal.source }} | ⏰ {{ deal.found_at.strftime('%H:%M:%S') }}</div>
        </div>
        {% endfor %}
        {% endif %}
        
        <div style="text-align: center; margin-top: 30px; color: #666;">
            <small>Auto-refresh in 30 seconds | Deployed on Railway</small>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def dashboard():
    """Dashboard principal"""
    global bot_instance, last_run, total_deals, last_deals
    
    return render_template_string(HTML_TEMPLATE,
        bot_running=bot_instance is not None,
        last_run=last_run,
        total_deals=total_deals,
        routes=ROUTES_TO_MONITOR,
        last_deals=last_deals[:5]  # Mostrar solo los últimos 5
    )

@app.route('/api/status')
def api_status():
    """API endpoint para status"""
    return jsonify({
        'status': 'running' if bot_instance else 'stopped',
        'last_run': last_run,
        'total_deals': total_deals,
        'monitored_routes': len(ROUTES_TO_MONITOR),
        'recent_deals_count': len(last_deals)
    })

@app.route('/run-now')
def run_now():
    """Ejecutar bot manualmente"""
    global last_run, total_deals, last_deals
    
    try:
        bot = FlightBot()
        deals = bot.run_search(ROUTES_TO_MONITOR)
        
        last_run = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total_deals += len(deals)
        last_deals = deals[-10:]  # Últimos 10 deals
        
        return jsonify({
            'success': True,
            'message': f'Bot executed successfully. Found {len(deals)} deals.',
            'deals_count': len(deals),
            'timestamp': last_run
        })
    except Exception as e:
        logger.error(f"Error running bot manually: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def run_bot_periodically():
    """Ejecuta el bot cada 30 minutos"""
    global bot_instance, last_run, total_deals, last_deals
    
    logger.info("Iniciando bot en segundo plano...")
    bot_instance = FlightBot()
    
    while True:
        try:
            logger.info("Ejecutando búsqueda programada...")
            deals = bot_instance.run_search(ROUTES_TO_MONITOR)
            
            last_run = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            total_deals += len(deals)
            last_deals = deals[-10:] if deals else last_deals
            
            logger.info(f"Búsqueda completada. Encontradas {len(deals)} ofertas.")
            
            # Esperar 30 minutos
            time.sleep(1800)  # 30 minutos = 1800 segundos
            
        except Exception as e:
            logger.error(f"Error en ejecución programada: {e}")
            time.sleep(300)  # Esperar 5 minutos si hay error

@app.route('/health')
def health_check():
    """Health check para Railway"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'flight-deal-bot'
    })

if __name__ == '__main__':
    # Iniciar bot en thread separado
    bot_thread = threading.Thread(target=run_bot_periodically, daemon=True)
    bot_thread.start()
    
    # Iniciar servidor web
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)