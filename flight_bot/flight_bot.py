import requests
import sqlite3
import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List
import logging
import os

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
    """Envía un mensaje simple a Telegram"""
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
            logger.info("Mensaje enviado a Telegram")
        else:
            logger.error(f"Error enviando mensaje a Telegram: {resp.text}")
    except Exception as e:
        logger.error(f"Excepción enviando a Telegram: {e}")


class FlightBot:
    def __init__(self):
        self.db_path = os.getenv('DATABASE_PATH', '/tmp/flight_deals.db')
        self.init_database()
        
        # Credenciales de Amadeus
        self.amadeus_api_key = os.getenv('AMADEUS_API_KEY')
        self.amadeus_api_secret = os.getenv('AMADEUS_API_SECRET')
        self.amadeus_token = None

        # Configuración de búsqueda
        self.scan_days = int(os.getenv("SCAN_DAYS", "730"))   # 2 años por defecto
        self.step_days = int(os.getenv("STEP_DAYS", "7"))     # paso de 7 días
        self.top_n = int(os.getenv("TOP_N", "5"))             # top 5 ofertas

    def init_database(self):
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
        if not self.amadeus_api_key or not self.amadeus_api_secret:
            logger.warning("Credenciales de Amadeus no configuradas")
            return None
            
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
                logger.info("Token de Amadeus obtenido exitosamente")
                return self.amadeus_token
            else:
                logger.error(f"Error obteniendo token: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error obteniendo token de Amadeus: {e}")
        return None

    def search_flights_amadeus(self, origin: str, destination: str, departure_date: str) -> List[FlightDeal]:
        """Busca vuelos en Amadeus para una fecha concreta"""
        if not self.amadeus_token:
            self.get_amadeus_token()
        if not self.amadeus_token:
            return []
        
        url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
        headers = {'Authorization': f'Bearer {self.amadeus_token}'}
        params = {
            'originLocationCode': origin,
            'destinationLocationCode': destination,
            'departureDate': departure_date,
            'adults': 1,
            'max': 5
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                deals = []
                for offer in data.get('data', []):
                    try:
                        price = float(offer['price']['total'])
                        itinerary = offer['itineraries'][0]
                        segment = itinerary['segments'][0]
                        airline = segment.get('carrierCode', 'Unknown')

                        # Link a Google Flights
                        google_url = (
                            f"https://www.google.com/travel/flights?q=flights+from+{origin}+to+{destination}"
                            f"+on+{departure_date}"
                        )

                        deals.append(FlightDeal(
                            origin=origin,
                            destination=destination,
                            departure_date=departure_date,
                            return_date="",
                            price=price,
                            airline=airline,
                            source="Amadeus",
                            url=google_url,
                            found_at=datetime.now()
                        ))
                    except Exception as e:
                        logger.error(f"Error procesando oferta: {e}")
                return deals
            else:
                logger.error(f"Error API Amadeus: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error buscando en Amadeus: {e}")
        return []

    def run_search(self, routes: List[tuple]):
        logger.info("=== INICIANDO ESCANEO DE OFERTAS ===")
        today = datetime.now().date()
        all_deals = []

        for origin, destination in routes:
            logger.info(f"Buscando {origin} → {destination}")
            current = today
            end_date = today + timedelta(days=self.scan_days)

            while current <= end_date:
                dep_date = current.strftime('%Y-%m-%d')
                deals = self.search_flights_amadeus(origin, destination, dep_date)
                if deals:
                    all_deals.extend(deals)
                current += timedelta(days=self.step_days)
                time.sleep(1)  # evitar rate-limit

        if all_deals:
            # ordenar por precio
            cheapest = sorted(all_deals, key=lambda d: d.price)[:self.top_n]
            for deal in cheapest:
                msg = (
                    f"🛫 *Oferta barata*\n"
                    f"{deal.origin} → {deal.destination}\n"
                    f"💲 {deal.price}\n"
                    f"✈️ {deal.airline}\n"
                    f"📅 {deal.departure_date}\n"
                    f"[🔗 Ver en Google Flights]({deal.url})"
                )
                send_telegram_message(msg)
        else:
            logger.info("No se encontraron ofertas")


# Configuración de rutas (ahora fijo a Montevideo → Madrid)
ROUTES_TO_MONITOR = [
    ('MVD', 'MAD'),
    ('MAD', 'MVD'),
    ('MVD', 'BCN'),
    ('BCN', 'MVD'),
]
