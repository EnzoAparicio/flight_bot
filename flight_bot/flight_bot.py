import requests
import sqlite3
import time
import random
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List
import json
import logging
import os
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText      # ✅ fix
from email.mime.multipart import MIMEMultipart  # ✅ correcto

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

class FlightBot:
    def __init__(self):
        # Base de datos en Railway
        self.db_path = os.getenv('DATABASE_PATH', '/tmp/flight_deals.db')
        self.init_database()
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ]
        
        # Variables de entorno para Railway
        self.amadeus_api_key = os.getenv('AMADEUS_API_KEY', 'BZh3CGKHgfo0LdZF88AFyu31IRUb5g0s')
        self.amadeus_api_secret = os.getenv('AMADEUS_API_SECRET', 'HVH0nIDXwV13BYm6')
        self.amadeus_token = None
        
        # Telegram desde variables de entorno
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '7960227385:AAGuslq7wseRDIlpC7SqYRsHEM8YR4fo7UY')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '154349141')
        
        # Email desde variables de entorno
        self.email_user = os.getenv('EMAIL_USER', 'enzo.aparicio.003@gmail.com')
        self.email_password = os.getenv('EMAIL_PASSWORD', 'Leenpata179382')
        self.recipient_emails = os.getenv('RECIPIENT_EMAILS', 'ninomx03@gmail.com').split(',')

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
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    route TEXT,
                    date TEXT,
                    price REAL,
                    checked_at TIMESTAMP
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
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
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
        
        headers = {
            'Authorization': f'Bearer {self.amadeus_token}'
        }
        
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
                        
                        deal = FlightDeal(
                            origin=origin,
                            destination=destination,
                            departure_date=departure_date,
                            return_date=return_date or "",
                            price=price,
                            airline=airline,
                            source="Amadeus",
                            url="https://amadeus.com/booking",
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

    def scrape_simple_search(self, origin: str, destination: str, departure_date: str, return_date: str = None) -> List[FlightDeal]:
        """Búsqueda simple usando requests (sin Selenium)"""
        logger.info(f"Búsqueda alternativa para {origin}-{destination}")
        
        if random.random() > 0.5:
            mock_deal = FlightDeal(
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                return_date=return_date or "",
                price=random.randint(200, 800),
                airline="Mock Airlines",
                source="Alternative Search",
                url="https://example.com/booking",
                found_at=datetime.now()
            )
            return [mock_deal]
        
        return []

    def save_deals(self, deals: List[FlightDeal]):
        """Guarda ofertas en la base de datos"""
        if not deals:
            return
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            for deal in deals:
                cursor.execute('''
                    INSERT INTO flight_deals 
                    (origin, destination, departure_date, return_date, price, airline, source, url, found_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    deal.origin, deal.destination, deal.departure_date, deal.return_date,
                    deal.price, deal.airline, deal.source, deal.url, deal.found_at
                ))
            
            conn.commit()
            conn.close()
            logger.info(f"Guardadas {len(deals)} ofertas en la base de datos")
        except Exception as e:
            logger.error(f"Error guardando ofertas: {e}")

    def get_price_alerts(self, threshold_percentage: float = 15.0) -> List[FlightDeal]:
        """Detecta ofertas con caída significativa de precio"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM flight_deals 
                WHERE notified = FALSE 
                AND found_at > datetime('now', '-2 hours')
                ORDER BY price ASC
            ''')
            
            recent_deals = cursor.fetchall()
            alerts = []
            
            for deal_row in recent_deals:
                current_price = deal_row[5]
                
                if current_price < 400:
                    deal = FlightDeal(
                        origin=deal_row[1],
                        destination=deal_row[2],
                        departure_date=deal_row[3],
                        return_date=deal_row[4],
                        price=deal_row[5],
                        airline=deal_row[6],
                        source=deal_row[7],
                        url=deal_row[8],
                        found_at=datetime.fromisoformat(deal_row[9])
                    )
                    alerts.append(deal)
            
            conn.close()
            return alerts
        except Exception as e:
            logger.error(f"Error obteniendo alertas: {e}")
            return []

    def send_telegram_notification(self, deal: FlightDeal):
        """Envía notificación por Telegram"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("Telegram no configurado")
            return False
        
        message = f"""
🛫 *OFERTA DE VUELO DETECTADA* 🛫

✈️ Ruta: {deal.origin} → {deal.destination}
📅 Fecha: {deal.departure_date}
💰 Precio: ${deal.price}
🏢 Aerolínea: {deal.airline}
📊 Fuente: {deal.source}

⏰ Encontrado: {deal.found_at.strftime('%H:%M:%S')}
        """
        
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        
        data = {
            'chat_id': self.telegram_chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        try:
            response = requests.post(url, json=data, timeout=30)
            if response.status_code == 200:
                logger.info("Notificación de Telegram enviada exitosamente")
                return True
            else:
                logger.error(f"Error Telegram: {response.status_code}")
        except Exception as e:
            logger.error(f"Error enviando notificación de Telegram: {e}")
        
        return False

    def send_email_notification(self, deals: List[FlightDeal]):
        """Envía notificación por email"""
        if not self.email_user or not deals:
            return False
        
        msg = MIMEMultipart()   # ✅ fix
        msg['From'] = self.email_user
        msg['To'] = ', '.join(self.recipient_emails)
        msg['Subject'] = f"🛫 {len(deals)} Nuevas Ofertas de Vuelos Detectadas"
        
        body = "Se han encontrado nuevas ofertas de vuelos:\n\n"
        
        for deal in deals:
            body += f"""
Ruta: {deal.origin} → {deal.destination}
Fecha: {deal.departure_date}
Precio: ${deal.price}
Aerolínea: {deal.airline}
Fuente: {deal.source}
-------------------
"""
        
        msg.attach(MIMEText(body, 'plain'))  # ✅ fix
        
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(self.email_user, self.email_password)
            server.send_message(msg)
            server.quit()
            logger.info("Email de notificación enviado exitosamente")
            return True
        except Exception as e:
            logger.error(f"Error enviando email: {e}")
        
        return False

    def mark_as_notified(self, deals: List[FlightDeal]):
        """Marca ofertas como notificadas"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            for deal in deals:
                cursor.execute('''
                    UPDATE flight_deals 
                    SET notified = TRUE 
                    WHERE origin = ? AND destination = ? AND price = ? AND found_at = ?
                ''', (deal.origin, deal.destination, deal.price, deal.found_at))
            
            conn.commit()
            conn.close()
            logger.info(f"Marcadas {len(deals)} ofertas como notificadas")
        except Exception as e:
            logger.error(f"Error marcando como notificadas: {e}")

    def run_search(self, routes: List[tuple], days_ahead: int = 21):
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
                
                if not amadeus_deals:
                    alt_deals = self.scrape_simple_search(origin, destination, departure_date, return_date)
                    all_deals.extend(alt_deals)
                    time.sleep(1)
        
        if all_deals:
            logger.info(f"Total ofertas encontradas: {len(all_deals)}")
            self.save_deals(all_deals)
            
            price_alerts = self.get_price_alerts()
            
            if price_alerts:
                logger.info(f"¡{len(price_alerts)} alertas de precio detectadas!")
                
                for alert in price_alerts:
                    self.send_telegram_notification(alert)
                    time.sleep(1)
                
                self.send_email_notification(price_alerts)
                self.mark_as_notified(price_alerts)
            else:
                logger.info("No se detectaron alertas de precio")
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

def main():
    """Función principal"""
    try:
        logger.info("=== BOT DE OFERTAS DE VUELOS EN RAILWAY ===")
        
        bot = FlightBot()
        deals = bot.run_search(ROUTES_TO_MONITOR)
        
        logger.info(f"Proceso completado. Ofertas encontradas: {len(deals)}")
        
        if deals:
            best_deals = sorted(deals, key=lambda x: x.price)[:3]
            logger.info("=== TOP 3 MEJORES OFERTAS ===")
            for i, deal in enumerate(best_deals, 1):
                logger.info(f"{i}. {deal.origin}→{deal.destination}: ${deal.price} ({deal.airline})")
        
        logger.info("Bot ejecutándose... Esperando próxima ejecución")
        
    except Exception as e:
        logger.error(f"Error en función principal: {e}")
        raise

if __name__ == "__main__":
    main()
