import requests
import time
import sys

URL = "http://localhost:5000/whatsapp/incoming"
PHONE_NUMBER = "254700000001"

def send_message(body):
    print(f"\n[You -> System]: {body}")
    
    try:
        response = requests.post(URL, data={
            'From': f'whatsapp:{PHONE_NUMBER}',
            'Body': body
        })
        
        # Parse XML response to show chatbot reply
        import xml.etree.ElementTree as ET
        if response.status_code == 200:
            root = ET.fromstring(response.text)
            message = root.find('Message')
            if message is not None and message.text:
                print(f"[System -> You]:\n{message.text}")
            else:
                print(f"[System -> You]: (Empty/No message tag)")
        else:
            print(f"[Error]: Status Code {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print(f"[Error]: Could not connect to {URL}.")
        print("Please ensure the Flask app is running on port 5000.")
        sys.exit(1)
        
    time.sleep(1)

def main():
    print("==============================================")
    print(" SMS WhatsApp Simulator CLI")
    print("==============================================")
    print("This script simulates a member sending texts.")
    print("Press Ctrl+C to exit at any time.")
    print("\nWait! Only run this AFTER you have:")
    print("1. Started MariaDB")
    print("2. Started Flask (`python run.py`)")
    print("==============================================\n")
    
    while True:
        try:
            user_input = input("\nType message and press Enter (or 'quit' to exit): ")
            if user_input.strip().lower() in ['quit', 'exit', 'q']:
                break
            if user_input.strip() == "":
                continue
                
            send_message(user_input)
            
        except KeyboardInterrupt:
            print("\nExiting simulator...")
            break

if __name__ == "__main__":
    main()
