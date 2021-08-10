"""PyEnaSolar interacts as a library to communicate with EnaSolar inverters"""
import aiohttp
import asyncio
import concurrent
from io import StringIO
from datetime import date
import logging
import xml.etree.ElementTree as ET

_LOGGER = logging.getLogger(__name__)

MAPPER_STATES = {
    "0": "Not connected",
    "1": "Waiting",
    "2": "Normal",
    "3": "Error",
    "4": "Upgrading",
}

URL_PATH_METERS = "meters.xml"
URL_PATH_DATA   = "data.xml"

class Sensor(object):
    """Sensor definition"""

    def __init__(self, key, is_hex, name, factor, unit='',
                 per_day_basis=False, per_total_basis=False):
        self.key = key
        self.is_hex = is_hex
        self.name = name
        self.unit = unit
        self.factor = factor
        self.value = None
        self.per_day_basis = per_day_basis
        self.per_total_basis = per_total_basis
        self.date = date.today()
        self.enabled = False


class Sensors(object):
    """EnaSolar sensors"""

    def __init__(self):
        self.__s = []
        self.add(
            (
                Sensor("OutputPower", False, "output_power", 1, "kWh"),
                Sensor("InputVoltage", False, "input_voltage_1", 1, "V"),
                Sensor("InputVoltage2", False, "input_voltage_2", 1, "V"),
                Sensor("OutputVoltage", False, "output_voltage", 1, "V"),
                Sensor("Irradiance", False, "irradiance", 1, "W/m2"),
                Sensor("Temperature", False, "tempertature", 1, "C"),
                Sensor("EnergyToday", True, "today_energy", 0.01, "kWh", True),
                Sensor("EnergyYesterday", True, "yesterday_energy", 0.01, "kWh", True), 
                Sensor("EnergyLifetime", True, "total_energy", 0.01, "kWh", False, True),
                Sensor("DaysProducing", True, "days_producing", 1, "d", False, True),
                Sensor("HoursExportedToday", False, "today_hours", 0.0167, "h", True),
                Sensor("HoursExportedYesterday", True, "yesterday_hours", 0.0167, "h", True),
                Sensor("HoursExportedLifetime", True, "total_hours", 0.0167, "h", False, True),
            )
        )

    def __len__(self):
        """Length."""
        return len(self.__s)

    def __contains__(self, key):
        """Get a sensor using either the name or key."""
        try:
            if self[key]:
                return True
        except KeyError:
            return False

    def __getitem__(self, key):
        """Get a sensor using either the name or key."""
        for sen in self.__s:
            if sen.name == key or sen.key == key:
                return sen
        raise KeyError(key)

    def __iter__(self):
        """Iterator."""
        return self.__s.__iter__()

    def add(self, sensor):
        """Add a sensor, warning if it exists."""
        if isinstance(sensor, (list, tuple)):
            for sss in sensor:
                self.add(sss)
            return

        if not isinstance(sensor, Sensor):
            raise TypeError("pysenasolar.Sensor expected")

        if sensor.name in self:
            old = self[sensor.name]
            self.__s.remove(old)
            _LOGGER.warning("Replacing sensor %s with %s", old, sensor)

        if sensor.key in self:
            _LOGGER.warning("Duplicate EnaSolar sensor key %s", sensor.key)

        self.__s.append(sensor)


class EnaSolar(object):
    """Provides access to EnaSolar inverter data"""

    def __init__(self, host):
        self.host = host

        self.url = "http://{0}/".format(self.host)

    async def read(self, sensors):
        """Returns necessary sensors from EnaSolar inverter"""

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout,
                                             raise_for_status=True) as session:
                current_url = self.url + URL_PATH_METERS

                async with session.get(current_url) as response:
                    data = await response.text()
                    at_least_one_enabled = False

                    xml = ET.fromstring(data)

                    for sen in sensors:
                       find = xml.find(sen.key)
                       if find is not None:
                           sen.value = find.text
                           if sen.is_hex:
                               sen.value = int(sen.value, 16)
                           sen.value = (float(sen.value) * sen.factor)
                           sen.date = date.today()
                           sen.enabled = True
                           at_least_one_enabled = True

                    if not at_least_one_enabled:
                        raise ET.ParseError

                    if sen.enabled:
                        _LOGGER.debug("Got new value for sensor %s: %s",
                                      sen.name, sen.value)

                current_url = self.url + URL_PATH_DATA

                async with session.get(current_url) as response:
                    data = await response.text()
                    at_least_one_enabled = False

                    xml = ET.fromstring(data)

                    for sen in sensors:
                       find = xml.find(sen.key)
                       if find is not None:
                           sen.value = find.text
                           if sen.is_hex:
                               sen.value = int(sen.value, 16)
                           sen.value = (float(sen.value) * sen.factor)
                           sen.date = date.today()
                           sen.enabled = True
                           at_least_one_enabled = True

                    if not at_least_one_enabled:
                        raise ET.ParseError

                    if sen.enabled:
                        _LOGGER.debug("Got new value for sensor %s: %s",
                                      sen.name, sen.value)

                    return True

        except (aiohttp.client_exceptions.ClientConnectorError,
                concurrent.futures._base.TimeoutError):
            # Connection to inverter not possible.
            # This can be "normal" - so warning instead of error - as SAJ
            # inverters are powered by DC and thus have no power after the sun
            # has set.
            _LOGGER.warning("Connection to EnaSolar inverter is not possible. " +
                            "Otherwise check host/ip address.")
            return False

        except aiohttp.client_exceptions.ClientResponseError as err:
            # 401 Unauthorized: wrong username/password
            if err.status == 401:
                raise UnauthorizedException(err)
            else:
                raise UnexpectedResponseException(err)

        except ET.ParseError:
            # XML is not valid or even no XML at all
            raise UnexpectedResponseException(
                str.format("No valid XML received from {0} at {1}", self.host,
                           current_url)
            )

class UnexpectedResponseException(Exception):
    """Exception for unexpected status code"""
    def __init__(self, message):
        Exception.__init__(self, message)
