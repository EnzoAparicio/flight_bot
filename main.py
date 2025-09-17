import logging
from flight_bot.flight_bot import FlightBot, ROUTES_TO_MONITOR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Punto de entrada principal del bot"""
    try:
        logger.info("=== INICIANDO BOT DE VUELOS ===")
        bot = FlightBot()
        deals = bot.run_search(ROUTES_TO_MONITOR)

        if deals:
            logger.info(f"Ofertas encontradas: {len(deals)}")
            best = sorted(deals, key=lambda d: d.price)[:3]
            for i, d in enumerate(best, 1):
                logger.info(f"{i}. {d.origin} → {d.destination} ${d.price} ({d.airline})")
        else:
            logger.info("No se encontraron ofertas en esta ejecución.")

        logger.info("=== EJECUCIÓN FINALIZADA ===")
    except Exception as e:
        logger.error(f"Error en main: {e}")
        raise

if __name__ == "__main__":
    main()
