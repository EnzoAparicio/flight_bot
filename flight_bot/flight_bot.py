import requests
import sqlite3
import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List
import logging
import os
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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
    """Envía un mensaje a Telegram usando el bot y el chat configurados"""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "7960227385:AAGuslq7wseRDIlpC7SqYRsHEM8YR4fo7UY")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "5257227274")
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
        # Base de datos en Railway
        self.db_path = os.getenv('DATABASE_PATH', '/tmp/flight_deals.db')
        self.init_database()
        
        # Variables de entorno para Railway
        self.amadeus_api_key = os.getenv('AMADEUS_API_KEY', 'BZh3CGKHgfo0LdZF88AFyu31IRUb5g0s')
        self.amadeus_api_secret = os.getenv('AMADEUS_API_SECRET', 'HVH0nIDXwV13BYm6')
        self.amadeus_token = None
        
        # Telegram desde variables de entorno
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '7960227385:AAGuslq7wseRDIlpC7SqYRsHEM8YR4fo7UY')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '5257227274')

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

    def search_flights_amadeus(self, origin: str, destination: str, departure_date: str, return_date: str = None) -> List[FlightDeal]:
        """Busca vuelos usando Amadeus API"""
        if not self.amadeus_token:
            self.get_amadeus_token()
        
        if not self.amadeus_token:
            logger.warning("No se pudo obtener token de Amadeus")
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
        if return_date:
            params['returnDate'] = return_date
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                deals = []
                for offer in data.get('data', [])[:5]:
                    try:
                        price = float(offer['price']['total'])
                        itinerary = offer['itineraries'][0]
                        segment = itinerary['segments'][0]
                        airline = segment.get('carrierCode', 'Unknown')

                        # 🔗 Generar link dinámico de Google Flights
                        google_url = (
                            f"https://www.google.com/travel/flights?q=flights+from+{origin}+to+{destination}"
                            f"+on+{departure_date}"
                        )

                        deal = FlightDeal(
                            origin=origin,
                            destination=destination,
                            departure_date=departure_date,
                            return_date=return_date or "",
                            price=price,
                            airline=airline,
                            source="Amadeus",
                            url=google_url,
                            found_at=datetime.now()
                        )
                        deals.append(deal)
                    except Exception as e:
                        logger.error(f"Error procesando oferta: {e}")
                        continue
                logger.info(f"Encontradas {len(deals)} ofertas en Amadeus para {origin}-{destination}")
                return deals
            else:
                logger.error(f"Error API Amadeus: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error buscando en Amadeus: {e}")
        
        return []

    def run_search(self, routes: List[tuple]):
        """Ejecuta búsqueda completa para las rutas especificadas"""
        logger.info("=== INICIANDO BÚSQUEDA DE OFERTAS ===")
        all_deals = []
        today = datetime.now()
        
        for origin, destination in routes:
            logger.info(f"Buscando vuelos: {origin} → {destination}")
            for days in [7, 14, 21]:
                departure_date = (today + timedelta(days=days)).strftime('%Y-%m-%d')
                return_date = (today + timedelta(days=days+7)).strftime('%Y-%m-%d')
                
                amadeus_deals = self.search_flights_amadeus(origin, destination, departure_date, return_date)
                all_deals.extend(amadeus_deals)
                time.sleep(2)
        
        if all_deals:
            logger.info(f"Total ofertas encontradas: {len(all_deals)}")
            for deal in all_deals:
                msg = (
                    f"🛫 *Oferta detectada*\n"
                    f"{deal.origin} → {deal.destination}\n"
                    f"💲 {deal.price}\n"
                    f"✈️ {deal.airline}\n"
                    f"📅 {deal.departure_date}\n"
                    f"[🔗 Ver en Google Flights]({deal.url})"
                )
                send_telegram_message(msg)
        else:
            logger.info("No se encontraron ofertas")
        
        return all_deals


# Configuración de rutas
ROUTES_TO_MONITOR = [
    ('MAD', 'JFK'),
    ('BCN', 'LHR'),
    ('MEX', 'CDG'),
    ('EZE', 'FCO'),
    ('BOG', 'MIA'),
]
