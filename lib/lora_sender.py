import board
import busio
import digitalio
import msgpack
from io import BytesIO

import adafruit_rfm9x


class LoraSender:
    def __init__(self, device_num: int, frequency: int = 915):
        self.device_num = device_num

        spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
        cs = digitalio.DigitalInOut(board.RFM_CS)
        reset = digitalio.DigitalInOut(board.RFM_RST)

        self.rfm9x = adafruit_rfm9x.RFM9x(spi, cs, reset, frequency)
        self.rfm9x.tx_power = 23
        self.rfm9x.spreading_factor = 7
        self.rfm9x.signal_bandwidth = 125000
        self.rfm9x.coding_rate = 5
        self.rfm9x.enable_crc = True
        self.rfm9x.ack_retries = 3
        self.rfm9x.ack_wait = 0.7

    def send_data(self, data: dict) -> bool:
        try:
            buffer = BytesIO()
            msgpack.pack({"device_num": self.device_num, "data": data}, stream=buffer)
            ack = self.rfm9x.send_with_ack(buffer.getvalue())
            return ack
        except Exception as er:
            print(f"Error sending data: {er}")
            return False

