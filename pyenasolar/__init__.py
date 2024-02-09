"""PyEnaSolar communicates with EnaSolar inverters"""

import asyncio
import re
from datetime import date
import logging
import xml.etree.ElementTree as ET
import aiohttp

_LOGGER = logging.getLogger(__name__)

URL_PATH_METERS = "meters.xml"
URL_PATH_DATA = "data.xml"

HAS_POWER_METER = 1
HAS_SOLAR_METER = 2
HAS_TEMPERATURE = 4
USE_FAHRENHIET = 256


class Sensor:
    """Sensor definition"""

    # pylint: disable=too-many-instance-attributes,too-few-public-methods

    def __init__(
        self,
        key,
        is_hex,
        name,
        factor,
        is_meter,
        unit="",
        per_day_basis=False,
        per_total_basis=False,
    ):
        # pylint: disable=too-many-arguments
        self.key = key
        self.is_hex = is_hex
        self.name = name
        self.unit = unit
        self.factor = factor
        self.value = None
        self.is_meter = is_meter
        self.per_day_basis = per_day_basis
        self.per_total_basis = per_total_basis
        self.date = date.today()
        self.enabled = True


class Sensors:
    """EnaSolar sensors"""

    def __init__(self, inv):
        self.__s = []
        self.add(
            (
                Sensor("OutputPower", False, "output_power", 1, True, "kW"),
                Sensor("InputVoltage", False, "input_voltage_1", 1, True, "V"),
                Sensor("OutputVoltage", False, "output_voltage", 1, True, "V"),
                Sensor("EnergyToday", True, "today_energy", 0.01, False, "kWh", True),
                Sensor(
                    "EnergyYesterday",
                    True,
                    "yesterday_energy",
                    0.01,
                    False,
                    "kWh",
                    True,
                ),
                Sensor(
                    "EnergyLifetime",
                    True,
                    "total_energy",
                    0.01,
                    False,
                    "kWh",
                    False,
                    True,
                ),
                Sensor(
                    "DaysProducing", True, "days_producing", 1, False, "d", False, True
                ),
                Sensor(
                    "HoursExportedToday", False, "today_hours", 0.0167, False, "h", True
                ),
                Sensor(
                    "HoursExportedYesterday",
                    False,
                    "yesterday_hours",
                    0.0167,
                    False,
                    "h",
                    True,
                ),
                Sensor(
                    "HoursExportedLifetime",
                    True,
                    "total_hours",
                    0.0167,
                    False,
                    "h",
                    False,
                    True,
                ),
                Sensor("Utilisation", False, "utilisation", 1, True, "%"),
                Sensor(
                    "AverageDailyPower",
                    False,
                    "average_daily_power",
                    1,
                    False,
                    "kWh",
                    True,
                    True,
                ),
            )
        )
        if inv.dc_strings == 2:
            self.add((Sensor("InputVoltage2", False, "input_voltage_2", 1, True, "V")))

        if inv.capability & HAS_POWER_METER:
            self.add(
                (
                    Sensor("MeterToday", True, "meter_today", 1, False, "kWh"),
                    Sensor("MeterYesterday", True, "meter_yesterday", 10, False, "kWh"),
                    Sensor("MeterLifetime", True, "meter_lifetime", 1, False, "kWh"),
                )
            )

        if inv.capability & HAS_SOLAR_METER:
            self.add(
                (
                    Sensor("Irradiance", False, "irradiance", 1, True, "W/m2"),
                    Sensor(
                        "InsolationToday",
                        True,
                        "insolation_today",
                        0.001,
                        False,
                        "kWh/m2",
                    ),
                    Sensor(
                        "InsolationYesterday",
                        True,
                        "insolation_yesterday",
                        0.001,
                        False,
                        "kWh/m2",
                    ),
                )
            )

        if inv.capability & HAS_TEMPERATURE:
            t_unit = "C"
            if inv.capability & USE_FAHRENHIET:
                t_unit = "F"
            self.add((Sensor("Temperature", False, "temperature", 1, True, t_unit),))

    def __len__(self) -> int:
        """Length."""
        return len(self.__s)

    def __contains__(self, key: str) -> bool:
        """Get a sensor using either the name or key."""
        try:
            if self[key]:
                return True
        except KeyError:
            return False
        return False

    def __getitem__(self, key: str) -> Sensor:
        """Get a sensor using either the name or key."""
        for sen in self.__s:
            if key in (sen.name, sen.key):
                return sen
        raise KeyError(key)

    def __iter__(self):
        """Iterator."""
        return self.__s.__iter__()

    def add(self, sensor: Sensor) -> None:
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


class EnaSolar:
    """Provides access to EnaSolar inverter data"""

    def __init__(self):
        self.host = None
        self.url = None
        self.serial_no = None
        self.capability = None
        self.dc_strings = None
        self.max_output = None
        self.sensors = None

    def setup_sensors(self) -> None:
        """Instantiate the various sensors"""
        self.sensors = Sensors(self)

    def get_serial_no(self) -> str:
        """Expose Serial No """
        return self.serial_no

    def get_capability(self) -> int:
        """Expose Capability """
        return self.capability

    def get_dc_strings(self) -> int:
        """Expose number of DC Strings"""
        return self.dc_strings

    def get_max_output(self) -> float:
        """Expose Max Output"""
        return self.max_output

    async def interogate_inverter(self, host: str) -> None:
        """Connect to the inverter and try to extract the configuration"""
        self.host = host
        self.url = "http://{0}/".format(self.host)

        _LOGGER.debug("Attempt to determine the Inverter's Serial No.")
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(
                timeout=timeout, raise_for_status=True
            ) as session:
                current_url = self.url + "settings.html"
                try:
                    async with session.get(current_url) as response:
                        data = await response.text()
                        pat = re.compile(
                            r'\(Number\(\("(\d+)"\)\*(\d+)\)\+Number\("(\d+)"\)\)',
                            re.M | re.I,
                        )
                        snum = pat.findall(data)
                        self.serial_no = int(snum[0][0]) * int(snum[0][1]) + int(
                            snum[0][2]
                        )

                    _LOGGER.debug("Found Serial No. %s", self.serial_no)

                except aiohttp.client_exceptions.ClientConnectorError as err:
                    # Connection to inverter not possible.
                    _LOGGER.warning(
                        "Connection failed. Check FQDN or IP address - %s", str(err)
                    )
                    raise
                except asyncio.TimeoutError:
                    raise

        except aiohttp.client_exceptions.ClientResponseError as err:
            # Connection to inverter succeeded but not expected result
            _LOGGER.warning("Connection to inverter succeeded. %s", str(err))
            raise

        _LOGGER.debug("Attempt to determine Inverter model setup and capabilities")
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(
                timeout=timeout, raise_for_status=True
            ) as session:
                current_url = self.url
                try:
                    async with session.get(current_url) as response:
                        data = await response.text()
                        pat = re.compile(r'Number\("(\d+|\d+\.\d+)"\);', re.M | re.I)
                        cap = pat.findall(data)
                        self.capability = int(cap[0])
                        self.dc_strings = int(cap[1])
                        self.max_output = float(cap[2])

                    _LOGGER.debug(
                        "Found: CAP=%s, DC=%s, Max=%s",
                        self.capability,
                        self.dc_strings,
                        self.max_output,
                    )

                except aiohttp.ClientConnectorError as err:
                    # Connection to inverter not possible.
                    _LOGGER.warning(
                        "Connection failed. Check FQDN or IP address - %s", str(err)
                    )
                    raise
                except asyncio.TimeoutError:
                    # Connection to inverter timeout
                    _LOGGER.warning("Connection to inverter timeout.")
                    raise

        except aiohttp.client_exceptions.ClientResponseError as err:
            # Connection to inverter succeeded but not expected result
            _LOGGER.warning("Connection to inverter succeeded. %s", str(err))
            raise

    async def read_meters(self) -> bool:
        """Extract the meters from their web page"""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(
                timeout=timeout, raise_for_status=True
            ) as session:
                current_url = self.url + URL_PATH_METERS

                try:
                    async with session.get(current_url) as response:
                        data = await response.text()
                        at_least_one_enabled = False

                        xml = ET.fromstring(data)

                        for sen in self.sensors:
                            if not sen.is_meter:
                                continue
                            find = xml.find(sen.key)
                            if find is not None:
                                sen.value = find.text
                                if sen.is_hex:
                                    sen.value = int(sen.value, 16)
                                sen.value = float(sen.value) * sen.factor
                                sen.date = date.today()
                                sen.enabled = True
                                at_least_one_enabled = True

                            if sen.enabled:
                                _LOGGER.debug(
                                    "Set METER sensor %s => %s", sen.name, sen.value
                                )

                        if not at_least_one_enabled:
                            raise ET.ParseError

                    # Calculate the derived sensors

                    sen1 = self.sensors.__getitem__("OutputPower")
                    sen2 = self.sensors.__getitem__("Utilisation")
                    sen2.value = round((float(sen1.value) * 100 / self.max_output), 2)
                    sen2.date = date.today()
                    sen2.enabled = True
                    _LOGGER.debug("Set CALC sensor %s => %s", sen2.name, sen2.value)

                    return True

                except asyncio.TimeoutError:
                    raise

        except aiohttp.client_exceptions.ClientConnectorError as err:
            # Connection to inverter not possible.
            _LOGGER.warning(
                "Connection failed. Check FQDN or IP address - %s", str(err)
            )
            raise

        except aiohttp.client_exceptions.ClientResponseError as err:
            # Connection to inverter succeeded but not expected result
            _LOGGER.warning("Connection to inverter succeeded. %s", str(err))
            raise

        except ET.ParseError:
            # XML is not valid or even no XML at all
            raise UnexpectedResponseException(
                str.format(
                    "No valid XML received from {0} at {1}", self.host, current_url
                )
            )

    async def read_data(self) -> bool:
        """Extract the data accummulators from their web page"""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(
                timeout=timeout, raise_for_status=True
            ) as session:
                current_url = self.url + URL_PATH_DATA

                try:
                    async with session.get(current_url) as response:
                        data = await response.text()
                        at_least_one_enabled = False

                        xml = ET.fromstring(data)

                        for sen in self.sensors:
                            if sen.is_meter:
                                continue
                            find = xml.find(sen.key)
                            if find is not None:
                                sen.value = find.text
                                if sen.is_hex:
                                    sen.value = int(sen.value, 16)
                                sen.value = float(sen.value) * sen.factor
                                if sen.unit == "h":
                                    sen.value = "{:,d}:{:02d}".format(
                                        *divmod(int(sen.value * 60), 60)
                                    )
                                sen.date = date.today()
                                sen.enabled = True
                                at_least_one_enabled = True

                            if sen.enabled:
                                _LOGGER.debug(
                                    "Set DATA sensor %s => %s", sen.name, sen.value
                                )

                        if not at_least_one_enabled:
                            raise ET.ParseError

                    # Calculate the derived sensors

                    sen1 = self.sensors.__getitem__("EnergyLifetime")
                    sen2 = self.sensors.__getitem__("DaysProducing")
                    sen3 = self.sensors.__getitem__("AverageDailyPower")
                    sen3.value = round((float(sen1.value) / sen2.value), 2)
                    sen3.date = date.today()
                    sen3.enabled = True
                    _LOGGER.debug("Set CALC sensor %s => %s", sen3.name, sen3.value)

                    return True

                except asyncio.TimeoutError:
                    raise

        except aiohttp.client_exceptions.ClientConnectorError as err:
            # Connection to inverter not possible.
            _LOGGER.warning("Connection to inverter failed. %s", str(err))
            raise

        except ET.ParseError:
            # XML is not valid or even no XML at all
            raise UnexpectedResponseException(
                str.format(
                    "No valid XML received from {0} at {1}", self.host, current_url
                )
            )


class UnexpectedResponseException(Exception):
    """Exception for unexpected status code"""

    def __init__(self, message):
        Exception.__init__(self, message)
