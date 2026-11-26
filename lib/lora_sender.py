import os

import board
import busio
import digitalio
import msgpack
from io import BytesIO

import adafruit_rfm9x

# Any non-broadcast address works: the gateway keeps the library's default node
# address (0xFF), so it accepts every packet and ACKs from the address we sent to.
# Device numbers start at 1, so 0 never collides with a node.
GATEWAY_ADDRESS = 0


class LoraSender:
    def __init__(self, device_num: int, frequency: int = 915):
        # The radio address is one byte; 0 is the gateway and 255 is broadcast.
        if not 1 <= device_num <= 254:
            raise ValueError("device_num must be 1-254")
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
        self.rfm9x.ack_retries = 3  # total attempts, not extra retries
        self.rfm9x.ack_wait = 0.7

        # Without these, packets are broadcast and send_with_ack() returns True
        # after one attempt without waiting for an ACK.
        self.rfm9x.node = device_num
        self.rfm9x.destination = GATEWAY_ADDRESS

        # The library starts at 0 on every boot. The gateway drops a retry whose
        # number matches the last one it saw from this node, so a fixed start
        # could make it ACK and discard new data after a deep sleep.
        self.rfm9x.sequence_number = os.urandom(1)[0]

    def send_data(self, data: dict) -> bool:
        """Send data to the gateway. True means the gateway's radio ACKed it."""
        try:
            buffer = BytesIO()
            msgpack.pack({"device_num": self.device_num, "data": data}, stream=buffer)
            ack = self.rfm9x.send_with_ack(buffer.getvalue())
            return ack
        except Exception as er:
            print(f"Error sending data: {er}")
            return False
        finally:
            self._sleep_radio()

    def _sleep_radio(self):
        # send_with_ack() leaves the radio receiving, which would continue through
        # deep sleep. The next send wakes it.
        try:
            self.rfm9x.sleep()
        except Exception as er:
            print(f"Error sleeping radio: {er}")
