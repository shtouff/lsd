
### Firmware

Nanpy needs to upload a firmware to the Arduino. This firmware is configured using a .h file. Clone the firmware, copy the .h file into it, then copy this specific firmware as a sketch file to your Arduino app. Compile then upload it.
```
$ git clone git@github.com:nanpy/nanpy-firmware.git
$ cp lsd.cfg.h nanpy-firmware/Nanpy/cfg.h
```

### Virtualenv

LSD uses two dependencies: click and nanpy. The easiest is to use a virtualenv:

```
$ python3 -mvenv .virtualenv
$ source .virtualenv/bin/actovate
(.virtualenv) $ pip install -r requirements.txt
```

