#!/usr/bin/env python3

"""
LSD: Liquid Server Display

"""
import click
import http.server
import json
import logging
from nanpy import SerialManager, Lcd, ArduinoApi
import socket
import socketserver
import sys
import time
import threading

logger = logging.getLogger()


class StoppableThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self._stopevent = threading.Event()

    def stop(self):
        self._stopevent.set()

    def wait(self, delay=0.5):
        self._stopevent.wait(delay)

    def should_stop(self):
        return self._stopevent.is_set()


class LedBLinker(StoppableThread):
    def __init__(self, api, pin):
        StoppableThread.__init__(self)
        self.api = api
        self.pin = pin
        self.api.pinMode(pin, self.api.OUTPUT)

    def run(self):
        while not self.should_stop():
            self.api.digitalWrite(self.pin, self.api.HIGH)
            self.wait()
            self.api.digitalWrite(self.pin, self.api.LOW)
            self.wait()

        self.api.digitalWrite(self.pin, self.api.LOW)


class ButtonWatcher(StoppableThread):
    def __init__(self, api, pin, callback):
        StoppableThread.__init__(self)
        self.api = api
        self.pin = pin
        self.api.pinMode(pin, self.api.INPUT)
        self.callback = callback

    def run(self):
        while not self.should_stop():
            if self.api.digitalRead(self.pin):
                self.callback()
            self.wait()


class LSDContext(object):
    __instance = None

    acked_message = ''
    current_message = ''
    led_blinker = None
    button_watcher = None

    @classmethod
    def create_instance(cls, api, lcd, led_pin, button_pin):
        LSDContext.__instance = LSDContext(api, lcd, led_pin, button_pin)

    @classmethod
    def get_instance(cls):
        if LSDContext is None:
            raise Exception("please, instantiate first.")
        return LSDContext.__instance

    def __init__(self, api, lcd, led_pin, button_pin):
        self.api = api
        self.lcd = lcd
        self.led_pin = led_pin
        self.button_pin = button_pin

    def get_last_acked_message(self):
        return self.acked_message

    def lcd_print(self, message='', clear=True):
        if clear:
            self.lcd.clear()

        self.lcd.printString(message[0:16], 0, 0)
        if len(message) > 16:
            if message[16] == ' ':
                self.lcd.printString(message[17:33], 0, 1)
            else:
                self.lcd.printString(message[16:32], 0, 1)

    def ack_message(self):
        self.stop_led_blinker()
        self.stop_button_watcher()
        self.acked_message = self.current_message
        self.lcd_print('OK ;-)')
        time.sleep(1)
        self.lcd_print()

    def stop_button_watcher(self):
        if self.button_watcher is not None:
            self.button_watcher.stop()
            self.button_watcher = None

    def stop_led_blinker(self):
        if self.led_blinker is not None:
            self.led_blinker.stop()
            self.led_blinker = None

    def start_led_blinker(self):
        self.led_blinker = LedBLinker(api=self.api, pin=self.led_pin)
        self.led_blinker.start()

    def start_button_watcher(self):
        self.button_watcher = ButtonWatcher(
            api=self.api,
            pin=self.button_pin,
            callback=self.ack_message,
        )
        self.button_watcher.start()

    def set_current_message(self, message):
        self.stop_button_watcher()
        self.stop_led_blinker()

        self.lcd_print(message)
        self.current_message = message

        self.start_button_watcher()
        self.start_led_blinker()


class LSDRequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = 'HTTP/0.1'
    sys_version = 'LiquidServerDisplay/0.1'

    def __init__(self, request, client_address, cls):
        super().__init__(request, client_address, cls)

    def get_root(self):
        preferred_content_type = 'application/json'
        output = json.dumps({
            'message': LSDContext.get_instance().get_last_acked_message()
        })

        self.send_response(200, 'OK')
        self.send_header('Content-Type', preferred_content_type)
        self.end_headers()

        self.wfile.write(output.encode())

    def do_GET(self):
        if self.path == '/':
            self.get_root()
        else:
            self.send_error(404)

    def post_root(self):
        body = self.rfile.read(int(self.headers['Content-Length'])).decode()
        message = json.loads(body)['message']

        preferred_content_type = 'application/json'
        output = json.dumps({
            'message': message
        })

        LSDContext.get_instance().set_current_message(message)

        self.send_response(200, 'OK')
        self.send_header('Content-Type', preferred_content_type)
        self.end_headers()

        self.wfile.write(output.encode())

    def do_POST(self):
        if self.path == '/':
            self.post_root()
        else:
            self.send_error(404)


class LSDServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    address_family = socket.AF_INET6


DEFAULT_DEVICE = '/dev/cu.usbmodem1421'
DEFAULT_PORT = 8081
DEFAULT_LOGLEVEL = 'INFO'


@click.command()
@click.option(
    '--device', '-d', help='Communicate with Arduino using device TEXT.', default=DEFAULT_DEVICE, show_default=True
)
@click.option(
    '--port', '-p', type=int, help='Bind and listen to this TCP port.', default=DEFAULT_PORT, show_default=True
)
@click.option('--loglevel', '-l', help='Set the log level to TEXT.', default=DEFAULT_LOGLEVEL, show_default=True)
def main(device, port, loglevel):
    """
    An HTTP server, which will accept JSON-formatted messages and print them to a LCD display. The message can be 
    acknowledged by the reader, using a key switch. LCD and key switch are accessed via an Arduino UNO.
    """
    logging.basicConfig(level=loglevel)
    connection = SerialManager(device=device)
    api = ArduinoApi(connection=connection)
    """
    pins: [rs, enable, d4, d5, d6, d7]
    LCD : color : ARDUINO
    rs: yellow: 7
    enable: white: 8
    d4: blue: 9
    d5: red: 10
    d6: orange: 11
    d7: green/yellow: 12
    """
    lcd = Lcd([7, 8, 9, 10, 11, 12], [16, 2], connection=connection)
    LSDContext.create_instance(api=api, lcd=lcd, led_pin=6, button_pin=2)
    logger.info('Starting LSD on port %s ...', port)
    LSDServer(("", port), LSDRequestHandler).serve_forever()


if __name__ == '__main__':
    main()
