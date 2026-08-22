import os
import sys
import logging
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

if __name__ == '__main__':
    # Run the server locally
    app.run(host='127.0.0.1', port=5000, debug=True)
