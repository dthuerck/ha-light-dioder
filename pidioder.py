# Copyright (c) 2017, Daniel Thuerck
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from math import *
import smbus
import time
import logging
import voluptuous as vol

# Home assistant stuff - use class from above to setup light access
from homeassistant.components.light import (
    ATTR_RGB_COLOR, ATTR_HS_COLOR, SUPPORT_COLOR, Light, PLATFORM_SCHEMA)
from homeassistant.const import CONF_NAME
import homeassistant.helpers.config_validation as cv
import homeassistant.util.color as color_util

_LOGGER = logging.getLogger(__name__)

SUPPORT_PILIGHT = (SUPPORT_COLOR)

# Configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default='PiDioder'): cv.string
})

# HA hook
def setup_platform(hass, config, add_devices_callback, discovery_info=None):
    # Just add one default PiDioder light with default address
    add_devices_callback([PiDioderLight(0x40, _LOGGER, config.get(CONF_NAME))])

# Representation of a polling-type light for HA, using the PiDioder class
class PiDioderLight(Light):

    def __init__(self, addr, log, name):
        # initialize PiDioder light at I2C address and put to sleep
        self._dev = PiDioder(addr, log)
        self._dev.set_freq(1000)
        self._is_sleep = True
        self._dev.sleep(self._is_sleep)

        # HA attributes
        self._name = name
        self._state = not self._is_sleep
        self._rgb = (255, 0, 10)

    @property
    def should_poll(self):
        return False

    @property
    def name(self):
        return self._name

    @property
    def available(self):
        return True

    @property
    def is_on(self):
        return not self._is_sleep

    @property
    def rgb_color(self):
        return self._rgb

    @property
    def supported_features(self):
        return SUPPORT_PILIGHT

    def turn_on(self, **kwargs):
        # turn on and set to chosen color (or all white)
        self._is_sleep = False
        self._dev.sleep(self._is_sleep)
        self._state = not self._is_sleep
        print(kwargs)
        if ATTR_RGB_COLOR in kwargs:
            self._rgb = kwargs[ATTR_RGB_COLOR]
        if ATTR_HS_COLOR in kwargs:
            self._rgb = color_util.color_hsv_to_RGB(kwargs[ATTR_HS_COLOR][0], kwargs[ATTR_HS_COLOR][1], 100)
        self._dev.set_color((self._rgb[0] / 255.0, self._rgb[1] / 255.0, self._rgb[2] / 255.0))

        # inform HA about state update
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        self._dev.set_all_pwm(0)
        self._is_sleep = True
        self._dev.sleep(self._is_sleep)
        self._state = not self._is_sleep

        # inform HA about state update
        self.schedule_update_ha_state()

# Basic library - Access an IKEA dioder attached to pins 0-2 on a PCA9685 via I2C
class PiDioder:

    def __init__(self, addr, log):
        self._bus = smbus.SMBus(1)
        self._log = log

        # Maximum value - should not be 4096, since that results in errors!
        # 3900 \approx 0.99 * 4096, that works in my experience
        self._maxval = 3900

        # I2C stuff
        self._DEVICE_ADDRESS = addr
        self._SWRST = 0x06

        # bit masks
        self._SLEEP = 0x10
        self._ALLCALL = 0x01

        # PCA9685 register (LEDn register off/on are split in 2 x 8bit regs)
        self._PRESCALE = 0xFE
        self._MODE1 = 0x00
        self._MODE2 = 0x01
        self._LED0_ON_L = 0x06
        self._LED0_ON_H = 0x07
        self._LED0_OFF_L = 0x08
        self._LED0_OFF_H = 0x09
        self._ALL_LED_ON_L = 0xFA
        self._ALL_LED_ON_H = 0xFB
        self._ALL_LED_OFF_L = 0xFC
        self._ALL_LED_OFF_H = 0xFD

        # perform SW reset
        self._bus.write_byte(0x00, self._SWRST)

    def sleep(self, sleep_status):
        # set register MODE1 to sleep and wait for activation
        old_mode = self._bus.read_byte_data(self._DEVICE_ADDRESS, self._MODE1)
        if sleep_status:
            new_mode = old_mode | self._SLEEP
        else:
            new_mode = old_mode & ~self._SLEEP
        self._bus.write_byte_data(self._DEVICE_ADDRESS, self._MODE1, new_mode)
        time.sleep(0.005)


    # set PWM frequency (min: 0x1E/200Hz, max: 0xFF/1526Hz)
    def set_freq(self, f):
        prescale = 25000000
        prescale /= 4096.0
        prescale /= float(f)
        prescale -= 1
        prescale = int(prescale)
        if prescale > 3 and prescale <= 255:
            # Frequency can only be changed while sleeping
            self.sleep(True)
            self._bus.write_byte_data(self._DEVICE_ADDRESS, self._PRESCALE, prescale)
            self.sleep(False)

    # set PWM channel value
    def set_pwm(self, channel, val):
        if val < 0 or val > 1:
            return
        start = 0
        end = int(val * self._maxval)
        self._bus.write_byte_data(self._DEVICE_ADDRESS, self._LED0_ON_L + 4 * channel, 0)
        self._bus.write_byte_data(self._DEVICE_ADDRESS, self._LED0_ON_H + 4 * channel, 0)
        self._bus.write_byte_data(self._DEVICE_ADDRESS, self._LED0_OFF_L + 4 * channel, end & 0xff)
        self._bus.write_byte_data(self._DEVICE_ADDRESS, self._LED0_OFF_H + 4 * channel, end >> 8)

    def set_all_pwm(self, val):
        if val < 0 or val > 1:
            return
        start = 0
        end = int(val * self._maxval)
        self._bus.write_byte_data(self._DEVICE_ADDRESS, self._ALL_LED_ON_L, 0)
        self._bus.write_byte_data(self._DEVICE_ADDRESS, self._ALL_LED_ON_H, 0)
        self._bus.write_byte_data(self._DEVICE_ADDRESS, self._ALL_LED_OFF_L, end & 0xff)
        self._bus.write_byte_data(self._DEVICE_ADDRESS, self._ALL_LED_OFF_H, end >> 8)

    def set_color(self, rgb):
        # Note: DIODERs are RBG instead of RGB, so switch last two channels
        self.set_pwm(0, rgb[0])
        self.set_pwm(1, rgb[2])
        self.set_pwm(2, rgb[1])
