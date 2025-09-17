import requests
import sqlite3
import time
import logging
import os
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional

# Configuración
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class FlightDeal:
    origin: str
    destination: str
    departure_date: str
    return_date: str
    price: float
    airline: str
    source: str
    url: str
    found_at: datetime


def send_telegram_message(text: str):
    """Envía un mensaje a Telegram"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en variables de entorno")
        return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        resp = requests.post(url, json=payload)
        if resp.status_code == 200:
            logger.info("Mensaje enviado a Telegram ✅")
        else:
            logger.error(f"Error enviando mensaje a Telegram: {resp.text}")
    except Exception as e:
        logger.error(f"Excepción enviando a Telegram: {e}")


class FlightBot:
    def __init__(self):
        # Base de datos
        self.db_path = os.getenv('DATABASE_PATH', '/tmp/flight_deals.db')
        self.init_database()
        
        # Amadeus
        self.amadeus_api_key = os.getenv('AMADEUS_API_KEY')
        self.amadeus_api_secret = os.getenv('AMADEUS_API_SECRET')
        self.amadeus_token = None

        # Telegram
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

    def init_database(self):
        """Inicializa la base de datos SQLite"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS flight_deals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    origin TEXT,
                    destination TEXT,
                    departure_date TEXT,
                    return_date TEXT,
                    price REAL,
                    airline TEXT,
                    source TEXT,
                    url TEXT,
                    found_at TIMESTAMP,
                    notified BOOLEAN DEFAULT FALSE
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info(f"Base de datos inicializada en: {self.db_path}")
        except Exception as e:
            logger.error(f"Error inicializando base de datos: {e}")

    def get_amadeus_token(self):
        """Obtiene token de acceso de Amadeus API"""
        url = "https://test.api.amadeus.com/v1/security/oauth2/token"
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data = {
            'grant_type': 'client_credentials',
            'client_id': self.amadeus_api_key,
            'client_secret': self.amadeus_api_secret
        }
        try:
            response = requests.post(url, headers=headers, data=data, timeout=30)
            if response.status_code == 200:
                self.amadeus_token = response.json()['access_token']
                logger.info("Token de Amadeus obtenido exitosamente ✅")
                return self.amadeus_token
            else:
                logger.error(f"Error obteniendo token: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error obteniendo token de Amadeus: {e}")
        return None

    def search_cheapest_dates(self, origin: str, destination: str) -> Optional[FlightDeal]:
        """Busca el precio más barato disponible para una ruta usando Amadeus Cheapest Dates"""
        if not self.amadeus_token:
            self.get_amadeus_token()
        if not self.amadeus_token:
            logger.error("No se pudo obtener token de Amadeus")
            return None

        url = "https://test.api.amadeus.com/v1/shopping/flight-dates"
        headers = {'Authorization': f'Bearer {self.amadeus_token}'}
        params = {'origin': origin, 'destination': destination, 'currency': 'USD'}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if "data" in data and data["data"]:
                    cheapest = min(data["data"], key=lambda x: float(x["price"]["total"]))
                    price = float(cheapest["price"]["total"])
                    dep_date = cheapest["departureDate"]

                    return FlightDeal(
                        origin=origin,
                        destination=destination,
                        departure_date=dep_date,
                        return_date="",
                        price=price,
                        airline="N/A",
                        source="Amadeus Cheapest Dates",
                        url=f"https://www.google.com/flights?hl=es#flt={origin}.{destination}.{dep_date}",
                        found_at=datetime.now()
                    )
                else:
                    logger.info(f"No se encontraron resultados para {origin}-{destination}")
            else:
                logger.error(f"Error API Amadeus: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error buscando fechas más baratas: {e}")
        return None

    def run_search(self, routes: List[tuple]):
        """Ejecuta la búsqueda de rutas y envía resultados a Telegram"""
        logger.info("=== INICIANDO BÚSQUEDA DE OFERTAS MÁS BARATAS ===")

        for origin, destination in routes:
            logger.info(f"Buscando la fecha más barata para: {origin} → {destination}")
            deal = self.search_cheapest_dates(origin, destination)
            time.sleep(2)

            if deal:
                msg = (
                    f"🌍 *Oferta detectada*\n\n"
                    f"🛫 {deal.origin} → {deal.destination}\n"
                    f"📅 {deal.departure_date}\n"
                    f"💲 {deal.price} USD\n\n"
                    f"🔗 [Ver en Google Flights]({deal.url})"
                )
                send_telegram_message(msg)
            else:
                logger.info(f"No se encontraron ofertas para {origin}-{destination}")


# ======================
# CONFIGURACIÓN DE RUTAS
# ======================
ROUTES_TO_MONITOR = [
    ('MVD', 'MAD'),   # Montevideo → Madrid
    # ('EZE', 'FCO'), # Ejemplo: Buenos Aires → Roma
    # ('BOG', 'MIA')  # Ejemplo: Bogotá → Miami
]
