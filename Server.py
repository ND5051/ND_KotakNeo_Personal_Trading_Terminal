from threading import _DummyThread
import os
import sys
import logging
import json
import threading
import asyncio
import websockets
from flask import Flask, request, jsonify, send_from_directory

# Add SDK path to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SDK_PATH = os.path.join(BASE_DIR, "ND_Kotak_Neo_CodeBase", "kotak-neo-python")
if os.path.exists(SDK_PATH) and SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)

try:
    import pyotp
except ImportError:
    pyotp = None

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Global NeoAPI client reference for local single-user environment
neo_client = None

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'Index.html')

@app.route('/api/initiate_login', methods=['POST'])
def initiate_login():
    global neo_client
    try:
        data = request.json or {}
        consumer_key = data.get('consumer_key')
        mobile_number = data.get('mobile_number')
        ucc = data.get('ucc')
        totp_code = data.get('totp_code', '').strip()
        totp_secret = data.get('totp_secret', '').strip()

        if not (consumer_key and mobile_number and ucc):
            return jsonify({'success': False, 'error': 'Missing required credentials'}), 400

        # Auto-generate TOTP code if secret is provided instead of code
        if not totp_code and totp_secret:
            if pyotp is None:
                return jsonify({'success': False, 'error': 'pyotp package is not installed on the server to auto-generate TOTP'}), 400
            try:
                totp_code = pyotp.TOTP(totp_secret).now()
            except Exception as e:
                return jsonify({'success': False, 'error': f'Failed to generate TOTP: {str(e)}'}), 400

        if not totp_code:
            return jsonify({'success': False, 'error': 'TOTP Code or Secret Key is required'}), 400

        # Import NeoAPI client
        from neo_api_client import NeoAPI
        
        logging.info("Initializing NeoAPI client with prod environment...")
        neo_client = NeoAPI(
            consumer_key=consumer_key,
            environment="prod"
        )

        logging.info("Sending TOTP login request...")
        login_response = neo_client.totp_login(
            mobile_number=mobile_number,
            ucc=ucc,
            totp=totp_code
        )
        
        logging.info(f"Login Response: {login_response}")
        
        # Check if successful
        if login_response.get("data") and "token" in login_response["data"]:
            return jsonify({
                'success': True,
                'message': 'TOTP verified successfully. Proceed to MPIN validation.',
                'response': login_response
            })
        else:
            error_msg = login_response.get('message', 'TOTP login failed (invalid credentials or expired TOTP)')
            return jsonify({'success': False, 'error': error_msg}), 400

    except Exception as e:
        logging.error(f"Error during initiate login: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/validate_mpin', methods=['POST'])
def validate_mpin():
    global neo_client
    try:
        if neo_client is None:
            return jsonify({'success': False, 'error': 'Session not initialized. Please initiate login first.'}), 400

        data = request.json or {}
        mpin = data.get('mpin')

        if not mpin:
            return jsonify({'success': False, 'error': 'MPIN is required'}), 400

        logging.info("Validating MPIN...")
        validate_response = neo_client.totp_validate(mpin=mpin)
        logging.info(f"Validate Response: {validate_response}")

        if validate_response.get("data") and "token" in validate_response["data"]:
            return jsonify({
                'success': True,
                'message': 'Login and session validation successful!',
                'response': validate_response
            })
        else:
            error_msg = validate_response.get('message', 'MPIN validation failed')
            return jsonify({'success': False, 'error': error_msg}), 400

    except Exception as e:
        logging.error(f"Error during MPIN validation: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/limits', methods=['GET'])
def get_limits():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        logging.info("Fetching trading limits...")
        limits_response = neo_client.limits()
        logging.info(f"Limits Response: {limits_response}")
        return jsonify({
            'success': True,
            'limits': limits_response
        })
    except Exception as e:
        logging.error(f"Error fetching limits: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/place_order', methods=['POST'])
def place_order():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        data = request.json or {}
        exchange_segment = data.get('exchange_segment')
        product = data.get('product')
        price = data.get('price')
        order_type = data.get('order_type')
        quantity = data.get('quantity')
        validity = data.get('validity', 'DAY')
        trading_symbol = data.get('trading_symbol')
        transaction_type = data.get('transaction_type')
        trigger_price = data.get('trigger_price', '0')

        if not (exchange_segment and product and price is not None and order_type and quantity and trading_symbol and transaction_type):
            return jsonify({'success': False, 'error': 'Missing required fields for placing order'}), 400

        logging.info(f"Placing order for symbol {trading_symbol} ({transaction_type})...")
        order_response = neo_client.place_order(
            exchange_segment=exchange_segment,
            product=product,
            price=str(price),
            order_type=order_type,
            quantity=str(quantity),
            validity=validity,
            trading_symbol=trading_symbol,
            transaction_type=transaction_type,
            trigger_price=str(trigger_price)
        )
        logging.info(f"Order Placement Response: {order_response}")
        return jsonify({
            'success': True,
            'response': order_response
        })
    except Exception as e:
        logging.error(f"Error placing order: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/subscribe_active_symbol', methods=['POST'])
def subscribe_active_symbol():
    data = request.json or {}
    token = str(data.get('token', '')).strip()
    segment = data.get('segment', '').strip()
    if not token or not segment:
        return jsonify({'success': False, 'error': 'Missing token or segment'}), 400
    
    subscribe_scrip_in_background(segment, token)
    return jsonify({'success': True})

@app.route('/api/unsubscribe_active_symbol', methods=['POST'])
def unsubscribe_active_symbol():
    data = request.json or {}
    token = str(data.get('token', '')).strip()
    segment = data.get('segment', '').strip()
    if not token or not segment:
        return jsonify({'success': False, 'error': 'Missing token or segment'}), 400
    
    unsubscribe_scrip_in_background(segment, token)
    return jsonify({'success': True})

@app.route('/api/place_basket_order', methods=['POST'])
def place_basket_order():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        data = request.json or {}
        orders = data.get('orders', [])
        if not orders:
            return jsonify({'success': False, 'error': 'No orders in basket'}), 400

        results = []
        for index, order in enumerate(orders):
            exchange_segment = order.get('exchange_segment')
            product = order.get('product')
            price = order.get('price')
            order_type = order.get('order_type')
            quantity = order.get('quantity')
            validity = order.get('validity', 'DAY')
            trading_symbol = order.get('trading_symbol')
            transaction_type = order.get('transaction_type')
            trigger_price = order.get('trigger_price', '0')

            try:
                logging.info(f"Placing basket leg {index+1}: {trading_symbol} ({transaction_type})...")
                order_response = neo_client.place_order(
                    exchange_segment=exchange_segment,
                    product=product,
                    price=str(price),
                    order_type=order_type,
                    quantity=str(quantity),
                    validity=validity,
                    trading_symbol=trading_symbol,
                    transaction_type=transaction_type,
                    trigger_price=str(trigger_price)
                )
                results.append({
                    'success': True,
                    'trading_symbol': trading_symbol,
                    'transaction_type': transaction_type,
                    'response': order_response
                })
            except Exception as leg_e:
                logging.error(f"Error placing basket leg {index+1}: {str(leg_e)}")
                results.append({
                    'success': False,
                    'trading_symbol': trading_symbol,
                    'transaction_type': transaction_type,
                    'error': str(leg_e)
                })

        return jsonify({
            'success': True,
            'results': results
        })
    except Exception as e:
        logging.error(f"Error placing basket: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/orders', methods=['GET'])
def get_orders():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        logging.info("Fetching order book...")
        order_response = neo_client.order_report()
        return jsonify({
            'success': True,
            'orders': order_response
        })
    except Exception as e:
        logging.error(f"Error fetching order book: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trades', methods=['GET'])
def get_trades():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        logging.info("Fetching trade report...")
        trade_response = neo_client.trade_report()
        return jsonify({
            'success': True,
            'trades': trade_response
        })
    except Exception as e:
        logging.error(f"Error fetching trade report: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/positions', methods=['GET'])
def get_positions():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        logging.info("Fetching positions...")
        positions_response = neo_client.positions()
        return jsonify({
            'success': True,
            'positions': positions_response
        })
    except Exception as e:
        logging.error(f"Error fetching positions: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/holdings', methods=['GET'])
def get_holdings():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        logging.info("Fetching portfolio holdings...")
        holdings_response = neo_client.holdings()
        return jsonify({
            'success': True,
            'holdings': holdings_response
        })
    except Exception as e:
        logging.error(f"Error fetching holdings: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cancel_order', methods=['POST'])
def cancel_order():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        data = request.json or {}
        order_id = data.get('order_id')
        amo = data.get('amo', 'NO')
        if not order_id:
            return jsonify({'success': False, 'error': 'order_id is required'}), 400

        logging.info(f"Cancelling order {order_id}...")
        response = neo_client.cancel_order(order_id=str(order_id), amo=amo)
        return jsonify({
            'success': True,
            'response': response
        })
    except Exception as e:
        logging.error(f"Error cancelling order {order_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/modify_order', methods=['POST'])
def modify_order():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        data = request.json or {}
        order_id = data.get('order_id')
        price = data.get('price')
        order_type = data.get('order_type')
        quantity = data.get('quantity')
        validity = data.get('validity', 'DAY')
        trigger_price = data.get('trigger_price', '0')
        disclosed_quantity = data.get('disclosed_quantity', '0')
        amo = data.get('amo', 'NO')

        if not (order_id and price is not None and order_type and quantity):
            return jsonify({'success': False, 'error': 'Missing required fields for order modification'}), 400

        logging.info(f"Modifying order {order_id}...")
        response = neo_client.modify_order(
            order_id=str(order_id),
            price=str(price),
            order_type=order_type,
            quantity=str(quantity),
            validity=validity,
            trigger_price=str(trigger_price),
            disclosed_quantity=str(disclosed_quantity),
            amo=amo
        )
        return jsonify({
            'success': True,
            'response': response
        })
    except Exception as e:
        logging.error(f"Error modifying order {order_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/option_chain_instruments', methods=['GET'])
def option_chain_instruments():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        symbol = request.args.get('symbol', '').strip().upper()
        if not symbol:
            return jsonify({'success': False, 'error': 'symbol parameter is required'}), 400

        logging.info(f"Fetching option chain instruments for symbol {symbol}...")
        
        raw_options = neo_client.search_scrip(
            exchange_segment="nse_fo",
            symbol=symbol,
            option_type="CE,PE",
            ignore_50multiple=False
        )

        if isinstance(raw_options, dict) and "error" in raw_options:
            return jsonify({'success': False, 'error': raw_options["error"]}), 400
        
        if not isinstance(raw_options, list):
            return jsonify({'success': True, 'options': [], 'expiries': []})

        clean_options = []
        expiries = set()
        
        for scrip in raw_options:
            sym_name = scrip.get('pSymbolName', '').strip().upper()
            if sym_name == symbol:
                opt_type = scrip.get('pOptionType', '').strip().upper()
                if opt_type in ['CE', 'PE']:
                    exp = scrip.get('pExpiryDate', '').strip()
                    if exp:
                        expiries.add(exp)
                    
                    strike_raw = scrip.get('dStrikePrice;', scrip.get('dStrikePrice', 0))
                    try:
                        strike = float(strike_raw) / 100.0
                    except (ValueError, TypeError):
                        strike = 0.0

                    clean_options.append({
                        'token': scrip.get('pSymbol') or scrip.get('pContractId'),
                        'trading_symbol': scrip.get('pTrdSymbol'),
                        'segment': scrip.get('pExchSeg', 'nse_fo'),
                        'symbol_name': sym_name,
                        'option_type': opt_type,
                        'strike': strike,
                        'expiry': exp
                    })

        from datetime import datetime
        def parse_exp(e_str):
            try:
                return datetime.strptime(e_str, "%d%b%Y")
            except Exception:
                return datetime.max

        sorted_expiries = sorted(list(expiries), key=parse_exp)

        # Determine spot info
        spot_token = None
        spot_segment = "nse_cm"
        spot_symbol = ""
        
        if symbol == "NIFTY":
            spot_token = "Nifty 50"
            spot_symbol = "Nifty 50"
        elif symbol == "BANKNIFTY":
            spot_token = "Nifty Bank"
            spot_symbol = "Nifty Bank"
        elif symbol == "FINNIFTY":
            spot_token = "Nifty Fin Services"
            spot_symbol = "Nifty Fin Services"
        else:
            try:
                stock_res = neo_client.search_scrip(exchange_segment="nse_cm", symbol=symbol)
                if isinstance(stock_res, list) and len(stock_res) > 0:
                    exact_stock = None
                    for s in stock_res:
                        if s.get('pSymbolName', '').strip().upper() == symbol:
                            exact_stock = s
                            break
                    if not exact_stock:
                        exact_stock = stock_res[0]
                    spot_token = exact_stock.get('pSymbol') or exact_stock.get('pContractId')
                    spot_symbol = exact_stock.get('pTrdSymbol') or exact_stock.get('pSymbolName')
            except Exception as e:
                logging.error(f"Error searching spot stock: {e}")
        
        return jsonify({
            'success': True,
            'options': clean_options,
            'expiries': sorted_expiries,
            'spot': {
                'token': spot_token,
                'segment': spot_segment,
                'symbol': spot_symbol
            }
        })

    except Exception as e:
        logging.error(f"Error in option chain fetch: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/fno_symbols', methods=['GET'])
def get_fno_symbols():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        from neo_api_client.utils import scrip_cache
        import pandas as pd
        import io

        csv_content = scrip_cache.read_csv("nse_fo")
        if csv_content is None:
            # Trigger quick search to force download and cache of NSE_FO.csv
            try:
                neo_client.search_scrip(exchange_segment="nse_fo", symbol="NIFTY", option_type="CE")
                csv_content = scrip_cache.read_csv("nse_fo")
            except Exception as e:
                logging.error(f"Error downloading F&O CSV: {e}")

        if csv_content is None:
            return jsonify({'success': True, 'symbols': ['NIFTY', 'BANKNIFTY', 'FINNIFTY']})

        df = pd.read_csv(io.BytesIO(csv_content), low_memory=False)
        df = df.rename(columns=lambda x: x.strip())

        unique_symbols = df['pSymbolName'].dropna().str.strip().str.upper().unique().tolist()
        unique_symbols.sort()

        indices = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
        other_symbols = [s for s in unique_symbols if s not in indices]
        final_list = indices + other_symbols

        return jsonify({
            'success': True,
            'symbols': final_list
        })
    except Exception as e:
        logging.error(f"Error fetching FnO symbols: {str(e)}")
        return jsonify({'success': True, 'symbols': ['NIFTY', 'BANKNIFTY', 'FINNIFTY']})


# =====================================================================
# Watchlist, Search and Live WebSocket Streaming implementation
# =====================================================================

WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading watchlist: {e}")
    return []

def save_watchlist(watchlist):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(watchlist, f, indent=4)
    except Exception as e:
        logging.error(f"Error saving watchlist: {e}")

@app.route('/api/search', methods=['GET'])
def search_symbols():
    global neo_client
    if neo_client is None:
        return jsonify({'success': False, 'error': 'Please log in first before searching'}), 401

    query = request.args.get('query', '').strip()
    segment = request.args.get('segment', 'nse_cm').strip()

    if not query:
        return jsonify({'success': False, 'error': 'Query parameter is required'}), 400

    try:
        logging.info(f"Searching for {query} in {segment}...")
        results = neo_client.search_scrip(exchange_segment=segment, symbol=query)
        if isinstance(results, list):
            # Limit results to 20 to avoid large payload
            return jsonify({'success': True, 'results': results[:20]})
        else:
            return jsonify({'success': True, 'results': []})
    except Exception as e:
        logging.error(f"Error in search: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/watchlist', methods=['GET'])
def get_watchlist():
    return jsonify({'success': True, 'watchlist': load_watchlist()})

@app.route('/api/watchlist/add', methods=['POST'])
def add_to_watchlist():
    data = request.json or {}
    token = str(data.get('token', '')).strip()
    segment = data.get('segment', '').strip()
    trading_symbol = data.get('trading_symbol', '').strip()
    symbol_name = data.get('symbol_name', '').strip()
    description = data.get('description', '').strip()

    if not token or not segment or not trading_symbol:
        return jsonify({'success': False, 'error': 'Missing token, segment, or trading_symbol'}), 400

    watchlist = load_watchlist()
    if any(item.get('token') == token and item.get('segment') == segment for item in watchlist):
        return jsonify({'success': True, 'message': 'Item already in watchlist', 'watchlist': watchlist})

    new_item = {
        'token': token,
        'segment': segment,
        'trading_symbol': trading_symbol,
        'symbol_name': symbol_name,
        'description': description
    }
    watchlist.append(new_item)
    save_watchlist(watchlist)
    
    subscribe_scrip_in_background(segment, token)
    return jsonify({'success': True, 'watchlist': watchlist})

@app.route('/api/watchlist/delete', methods=['POST'])
def delete_from_watchlist():
    data = request.json or {}
    token = str(data.get('token', '')).strip()
    segment = data.get('segment', '').strip()

    if not token or not segment:
        return jsonify({'success': False, 'error': 'Missing token or segment'}), 400

    watchlist = load_watchlist()
    original_len = len(watchlist)
    watchlist = [item for item in watchlist if not (item.get('token') == token and item.get('segment') == segment)]
    
    if len(watchlist) == original_len:
        return jsonify({'success': False, 'error': 'Item not found in watchlist'}), 404

    save_watchlist(watchlist)
    
    unsubscribe_scrip_in_background(segment, token)
    return jsonify({'success': True, 'watchlist': watchlist})

# Active local websocket clients connected to our local broadcast server
local_clients = set()
# Latest cache of prices: { "segment|token": { ltp: ..., change: ..., change_percent: ..., volume: ... } }
price_cache = {}

bg_loop = None
kotak_ws = None

async def broadcast_to_local_clients(message):
    if not local_clients:
        return
    data_str = json.dumps(message)
    websockets_to_remove = set()
    for client in local_clients:
        try:
            await client.send(data_str)
        except Exception:
            websockets_to_remove.add(client)
    if websockets_to_remove:
        local_clients.difference_update(websockets_to_remove)

async def local_ws_handler(websocket):
    local_clients.add(websocket)
    logging.info(f"Local WebSocket client connected. Total: {len(local_clients)}")
    try:
        if price_cache:
            await websocket.send(json.dumps({"type": "initial_prices", "prices": price_cache}))
        async for message in websocket:
            pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if websocket in local_clients:
            local_clients.remove(websocket)
        logging.info(f"Local WebSocket client disconnected. Total: {len(local_clients)}")

async def start_local_websocket_server():
    logging.info("Starting local WebSocket server on port 5001...")
    try:
        async with websockets.serve(local_ws_handler, "127.0.0.1", 5001):
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                pass
    except OSError as e:
        if e.errno == 10048:
            logging.error("Port 5001 is already in use. A previous instance of the server might still be running. Please close it.")
        else:
            logging.error(f"OSError when starting local WebSocket server: {e}")
    except Exception as e:
        logging.error(f"Error starting local WebSocket server: {e}")

async def kotak_sfeed_loop():
    global kotak_ws, neo_client
    from neo_api_client.websocket.feed import WsToken, SFeedScrip
    
    while True:
        if neo_client is None:
            await asyncio.sleep(1)
            continue
        
        logging.info("Starting Kotak Neo SFeed WebSocket client...")
        try:
            async with neo_client.create_websocket() as ws:
                kotak_ws = ws
                logging.info("Connected to Kotak Neo SFeed!")
                
                watchlist = load_watchlist()
                tokens_to_sub = []
                for item in watchlist:
                    tokens_to_sub.append(WsToken(item['segment'], str(item['token'])))
                
                if tokens_to_sub:
                    logging.info(f"Subscribing to {len(tokens_to_sub)} watchlist items (depth)...")
                    await ws.subscribe_depth(tokens_to_sub)
                
                async for message in ws:
                    if isinstance(message, SFeedScrip):
                        key = f"{message.exchange_segment}|{message.instrument_token}"
                        update_data = {
                            "ltp": message.last_traded_price,
                            "change": message.net_change,
                            "change_percent": message.net_change_percent,
                            "volume": getattr(message, 'volume_traded_today', 0),
                            "oi": getattr(message, 'open_interest', 0),
                            "bid_qty": message.buy[0].quantity if (message.buy and len(message.buy) > 0) else 0,
                            "bid_price": message.buy[0].price if (message.buy and len(message.buy) > 0) else 0.0,
                            "ask_qty": message.sell[0].quantity if (message.sell and len(message.sell) > 0) else 0,
                            "ask_price": message.sell[0].price if (message.sell and len(message.sell) > 0) else 0.0,
                            "buy": [{"quantity": b.quantity, "price": b.price, "orders": b.orders} for b in message.buy] if message.buy else [],
                            "sell": [{"quantity": s.quantity, "price": s.price, "orders": s.orders} for s in message.sell] if message.sell else []
                        }
                        price_cache[key] = update_data
                        await broadcast_to_local_clients({
                            "type": "tick",
                            "key": key,
                            "data": update_data
                        })
        except Exception as e:
            logging.error(f"Error in Kotak Neo SFeed connection: {e}")
            kotak_ws = None
            await asyncio.sleep(5)

import atexit

def run_async_loop():
    global bg_loop
    import websockets
    bg_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bg_loop)
    
    bg_loop.create_task(kotak_sfeed_loop())
    bg_loop.create_task(start_local_websocket_server())
    
    try:
        bg_loop.run_forever()
    finally:
        pending = asyncio.all_tasks(bg_loop)
        for task in pending:
            task.cancel()
        if pending:
            bg_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        bg_loop.close()
        logging.info("Background asyncio event loop closed cleanly.")

def stop_async_loop():
    global bg_loop
    if bg_loop and bg_loop.is_running():
        logging.info("Stopping background event loop on exit...")
        bg_loop.call_soon_threadsafe(bg_loop.stop)

atexit.register(stop_async_loop)

def subscribe_scrip_in_background(segment, token):
    global bg_loop, kotak_ws
    from neo_api_client.websocket.feed import WsToken
    if bg_loop and kotak_ws and bg_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            kotak_ws.subscribe_depth([WsToken(segment, str(token))]),
            bg_loop
        )
        logging.info(f"Requested background depth subscription for {segment}|{token}")

def unsubscribe_scrip_in_background(segment, token):
    global bg_loop, kotak_ws
    from neo_api_client.websocket.feed import WsToken
    if bg_loop and kotak_ws and bg_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            kotak_ws.unsubscribe_depth([WsToken(segment, str(token))]),
            bg_loop
        )
        logging.info(f"Requested background depth unsubscription for {segment}|{token}")

# Prevent thread duplication when Flask runs in debug mode with reloader enabled
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
    bg_thread = threading.Thread(target=run_async_loop, daemon=True)
    bg_thread.start()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
