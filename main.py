import logging
from flight_bot.flight_bot import FlightBot, ROUTES_TO_MONITOR, send_telegram_message

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
                msg = (
                    f"✈️ Oferta #{i}\n"
                    f"{d.origin} → {d.destination}\n"
                    f"💲 Precio: {d.price}\n"
                    f"🛫 Aerolínea: {d.airline}\n"
                    f"📅 Fecha: {d.departure_date}"
                )
                logger.info(msg)
                send_telegram_message(msg)  # ✅ Envío a Telegram
        else:
            msg = "ℹ️ No se encontraron ofertas en esta ejecución."
            logger.info(msg)
            send_telegram_message(msg)

        logger.info("=== EJECUCIÓN FINALIZADA ===")
    except Exception as e:
        logger.error(f"Error en main: {e}")
        send_telegram_message(f"❌ Error en el bot: {e}")
        raise

if __name__ == "__main__":
    main()
