#!/usr/bin/env python3

"""
LSD: Liquid Server Display

"""
import click
import http.server
from ipaddress import IPv4Network, IPv6Address, IPv6Network, ip_address
import json
import logging
from nanpy import SerialManager, Lcd, ArduinoApi
import socket
import socketserver
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


class LSDRequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = 'HTTP/0.1'
    sys_version = 'LiquidServerDisplay/0.1'

    def get_root(self):
        preferred_content_type = 'application/json'
        output = json.dumps({
            'message': self.server.get_last_acked_message(),
        })

        self.send_response(200, 'OK')
        self.send_header('Content-Type', preferred_content_type)
        self.end_headers()

        self.wfile.write(output.encode())

    def do_GET(self):
        if not self.server.is_src_ip_allowed(ip_address(self.client_address[0])):
            self.send_error(401)
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

        self.server.set_current_message(message)

        self.send_response(200, 'OK')
        self.send_header('Content-Type', preferred_content_type)
        self.end_headers()

        self.wfile.write(output.encode())

    def do_POST(self):
        if not self.server.is_src_ip_allowed(ip_address(self.client_address[0])):
            self.send_error(401)
        if self.path == '/':
            self.post_root()
        else:
            self.send_error(404)


class LSDServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    # from HTTPServer
    address_family = socket.AF_INET6

    # LSDServer
    acked_message = ''
    current_message = ''
    led_blinker = None
    button_watcher = None

    def __init__(
            self, server_address, RequestHandlerClass,
            api, lcd, led_pin, button_pin,
            ipv4_allowed_prefixes, ipv6_allowed_prefixes
    ):
        super().__init__(server_address, RequestHandlerClass)
        self.api = api
        self.lcd = lcd
        self.led_pin = led_pin
        self.button_pin = button_pin
        self.ipv4_allowed_prefixes = ipv4_allowed_prefixes
        self.ipv6_allowed_prefixes = ipv6_allowed_prefixes

    def is_src_ip_allowed(self, ip: IPv6Address):
        # consider ip to be an IPv6Address
        prefixes = self.ipv6_allowed_prefixes
        subnet = IPv6Network(ip)
        if ip.ipv4_mapped is not None:
            prefixes = self.ipv4_allowed_prefixes
            subnet = IPv4Network(ip.ipv4_mapped)

        for prefix in prefixes:
            if prefix.overlaps(subnet):
                return True

        return False

    def get_last_acked_message(self):
        logger.info('The stored message was retrieved: [%s].', self.acked_message)
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
        logger.info('The button was pressed, ack the message: [%s].', self.current_message)
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
        logger.info('A new message has been set: [%s].', message)

        self.start_button_watcher()
        self.start_led_blinker()



DEFAULT_DEVICE = '/dev/cu.usbmodem1421'
DEFAULT_PORT = 8081
DEFAULT_LOGLEVEL = 'INFO'
DEFAULT_INET = ['127.0.0.1/32', '127.0.0.2/32']
DEFAULT_INET6 = ['::1/128', ]


@click.command()
@click.option(
    '--device', '-d', help='Communicate with Arduino using device TEXT.', default=DEFAULT_DEVICE, show_default=True
)
@click.option(
    '--port', '-p', type=int, help='Bind and listen to this TCP port.', default=DEFAULT_PORT, show_default=True
)
@click.option('--loglevel', '-l', help='Set the log level to TEXT.', default=DEFAULT_LOGLEVEL, show_default=True)
@click.option(
    '--inet', '-4', help='Allowed source ipv4 prefixes.', default=DEFAULT_INET, show_default=True, multiple=True
)
@click.option(
    '--inet6', '-6', help='Allowed source ipv6 prefixes.', default=DEFAULT_INET6, show_default=True, multiple=True
)
def main(device, port, loglevel, inet, inet6):
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
    logger.info('Starting LSD on port %s ...', port)
    LSDServer(
        ("", port), LSDRequestHandler,
        api=api, lcd=lcd, led_pin=6, button_pin=2,
        ipv4_allowed_prefixes=[IPv4Network(x) for x in inet],
        ipv6_allowed_prefixes=[IPv6Network(x) for x in inet6],
    ).serve_forever()


if __name__ == '__main__':
    main()
