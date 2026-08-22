import os
import sys
import getpass
import asyncio
from datetime import datetime

# Add the SDK directory to sys.path so we can import neo_api_client directly
sdk_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kotak-neo-python")
if os.path.exists(sdk_path) and sdk_path not in sys.path:
    sys.path.insert(0, sdk_path)

# Try importing pyotp to generate TOTP code if secret is provided
try:
    import pyotp
except ImportError:
    pyotp = None

# Simple dotenv parser to load .env variables
def load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and val:
                        os.environ[key] = val

load_dotenv()

def get_input(prompt_text, env_var, is_secret=False):
    default_val = os.environ.get(env_var, "")
    prompt_suffix = f" [{default_val[:4]}...{default_val[-4:]}]" if default_val and len(default_val) > 8 else (f" [{default_val}]" if default_val else "")
    
    if is_secret:
        if default_val:
            val = getpass.getpass(f"{prompt_text}{prompt_suffix} (Press Enter to use default): ")
            return val if val else default_val
        else:
            return getpass.getpass(f"{prompt_text}: ")
    else:
        val = input(f"{prompt_text}{prompt_suffix}: ")
        return val if val else default_val

def authenticate_and_get_client():
    print("=========================================")
    print("  Kotak Neo Authentication Setup")
    print("=========================================")

    consumer_key = get_input("1. Enter Consumer Key", "NEO_CONSUMER_KEY")
    mobile_number = get_input("2. Enter Mobile Number", "NEO_MOBILE_NUMBER")
    ucc = get_input("3. Enter UCC", "NEO_UCC")
    mpin = get_input("4. Enter MPIN", "NEO_MPIN", is_secret=True)

    # TOTP is asked last in the sequence:
    totp_code = ""
    totp_secret = os.environ.get("NEO_TOTP_SECRET", "")

    # We ask for the live TOTP code or secret key
    totp_input = input("5. Enter live 6-digit TOTP code (or press Enter to use/input a TOTP Secret Key): ").strip()

    if not totp_input:
        if not totp_secret:
            totp_secret = getpass.getpass("Enter TOTP Secret Key (for auto-generation): ").strip()
        
        if totp_secret:
            if pyotp is None:
                print("\nError: 'pyotp' package is not installed. Cannot auto-generate TOTP.")
                print("Please run: pip install pyotp")
                sys.exit(1)
            try:
                totp_code = pyotp.TOTP(totp_secret).now()
                print(f"Generated TOTP Code: {totp_code}")
            except Exception as e:
                print(f"\nError generating TOTP: {e}")
                sys.exit(1)
        else:
            print("\nError: No TOTP code or TOTP Secret Key provided.")
            sys.exit(1)
    else:
        totp_code = totp_input

    if not (consumer_key and mobile_number and ucc and mpin and totp_code):
        print("\nError: All fields are required to login.")
        sys.exit(1)

    print("\nInitializing NeoAPI client and logging in...")
    from neo_api_client import NeoAPI

    client = NeoAPI(
        consumer_key=consumer_key,
        environment="prod"
    )

    try:
        login_response = client.totp_login(
            mobile_number=mobile_number,
            ucc=ucc,
            totp=totp_code
        )
        
        if login_response.get("data") and "token" in login_response["data"]:
            validate_response = client.totp_validate(mpin=mpin)
            if validate_response.get("data") and "token" in validate_response["data"]:
                print("✓ Login and validation successful!")
                return client
            else:
                print(f"✗ MPIN validation failed. Response: {validate_response}")
                sys.exit(1)
        else:
            print(f"✗ TOTP login failed. Response: {login_response}")
            sys.exit(1)
    except Exception as e:
        print(f"✗ Exception during login: {e}")
        sys.exit(1)

def get_current_month_future(client):
    print("\n=========================================")
    print("  Searching for Current Month Nifty Future")
    print("=========================================")
    print("Downloading and searching master scrip files...")
    
    # Query Nifty Futures
    results = client.search_scrip(
        exchange_segment="nse_fo",
        symbol="NIFTY",
        option_type="FUT"
    )

    if not results or "error" in results or not isinstance(results, list):
        print(f"Error searching scrips or no data found: {results}")
        sys.exit(1)

    futures_list = []
    for item in results:
        expiry_str = item.get("pExpiryDate")
        symbol_name = item.get("pSymbolName")
        if expiry_str and symbol_name == "NIFTY":
            futures_list.append(item)

    if not futures_list:
        print("No Nifty future contracts found in F&O scrip master.")
        sys.exit(1)

    # Sort F&O contracts by their expiry dates to pick the nearest month (current month)
    def parse_expiry(item):
        try:
            # Parse expiry date formatted like '27Jun2024' or '27JUN2024'
            return datetime.strptime(item["pExpiryDate"].strip(), "%d%b%Y")
        except Exception:
            return datetime.min

    futures_list.sort(key=parse_expiry)

    # Pick the nearest month contract
    current_future = futures_list[0]
    print(f"✓ Found current month Nifty Future:")
    print(f"  - Trading Symbol: {current_future.get('pTrdSymbol')}")
    print(f"  - Instrument Token: {current_future.get('pSymbol')}")
    print(f"  - Expiry Date: {current_future.get('pExpiryDate')}")
    return current_future

async def stream_ltp(client, instrument_token, trading_symbol):
    from neo_api_client.websocket.feed import WsToken, SFeedScrip

    print("\n=========================================")
    print(f"  Connecting to WebSocket for Nifty LTP")
    print("=========================================")

    # Create the websocket instance and subscribe
    async with client.create_websocket() as ws:
        print("✓ Connected to WebSocket feed server!")
        
        # Build subscription token
        token = WsToken("nse_fo", str(instrument_token))
        print(f"Subscribing to {trading_symbol} (Token: {instrument_token})...")
        await ws.subscribe_scrips([token])
        print("✓ Subscribed successfully! Listening for live price feeds...\n")

        try:
            async for message in ws:
                if isinstance(message, SFeedScrip):
                    # Ensure it is the token we subscribed to
                    if str(message.instrument_token) == str(instrument_token):
                        ltp = message.last_traded_price
                        change = message.net_change
                        change_percent = message.net_change_percent
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] {trading_symbol} LTP: ₹{ltp:.2f} | Change: {change:+.2f} ({change_percent:+.2f}%)")
        except asyncio.CancelledError:
            print("\nStream cancelled.")
        except Exception as e:
            print(f"\nError in WebSocket loop: {e}")

def main():
    # 1. Login to Kotak Neo API
    client = authenticate_and_get_client()

    # 2. Get current month future token details
    nifty_fut = get_current_month_future(client)
    token = nifty_fut["pSymbol"]
    symbol = nifty_fut["pTrdSymbol"]

    # 3. Run the async websocket client to stream LTP
    try:
        asyncio.run(stream_ltp(client, token, symbol))
    except KeyboardInterrupt:
        print("\n\nStopping script...")

if __name__ == "__main__":
    main()
