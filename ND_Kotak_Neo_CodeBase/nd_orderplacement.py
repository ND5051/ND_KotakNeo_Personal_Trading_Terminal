import os
import sys
import getpass

# ---------------------------------------------------------
# EDITABLE ORDER PAYLOAD
# Modify the parameters below to customize your order
# ---------------------------------------------------------
ORDER_PAYLOAD = {
    "exchange_segment": "nse_cm",      # e.g., nse_cm, nse_fo, bse_cm, bse_fo, mcx_fo
    "trading_symbol": "RELIANCE-EQ",   # Trading symbol of the scrip
    "transaction_type": "B",           # B for Buy, S for Sell
    "quantity": "1",                   # Quantity to buy or sell (as string)
    "price": "1500",                      # Limit price. For market orders, set to "0"
    "order_type": "L",               # MKT (Market), L (Limit), SL, SL-M
    "product": "CNC",                  # CNC, MIS (Intraday), NRML, MTF
    "validity": "DAY",                 # DAY, IOC
}
# ---------------------------------------------------------

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

    # Prompt user or load from environment
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

def main():
    # 1. Authenticate Client
    client = authenticate_and_get_client()

    # 2. Place Order
    print("\n=========================================")
    print("  Placing Order with Kotak Neo")
    print("=========================================")
    print(f"Payload: {ORDER_PAYLOAD}")

    try:
        order_response = client.place_order(
            exchange_segment=ORDER_PAYLOAD["exchange_segment"],
            product=ORDER_PAYLOAD["product"],
            price=ORDER_PAYLOAD["price"],
            order_type=ORDER_PAYLOAD["order_type"],
            quantity=ORDER_PAYLOAD["quantity"],
            validity=ORDER_PAYLOAD["validity"],
            trading_symbol=ORDER_PAYLOAD["trading_symbol"],
            transaction_type=ORDER_PAYLOAD["transaction_type"]
        )
        print(f"\nOrder Placement Response:\n{order_response}")
    except Exception as e:
        print(f"\n✗ Error placing order: {e}")

if __name__ == "__main__":
    main()
