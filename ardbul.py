import serial
import time

# Replace with the COM port assigned to your ESP32 Bluetooth connection
# On Windows it will look like "COM5", on Linux/Mac something like "/dev/rfcomm0"
PORT = "COM4"   # <-- change this to your Bluetooth COM port
BAUD_RATE = 115200

def main():
    try:
        # Open serial connection
        ser = serial.Serial(PORT, BAUD_RATE, timeout=1)
        print(f"Connected to {PORT} at {BAUD_RATE} baud.")
        time.sleep(2)  # wait for connection to stabilize

        while True:
            # Read a line of data
            line = ser.readline().decode('utf-8').strip()
            if line:
                # Print received data in terminal
                print(f"Received: {line}")

    except serial.SerialException as e:
        print(f"Serial error: {e}")
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Serial connection closed.")

if __name__ == "__main__":
    main()