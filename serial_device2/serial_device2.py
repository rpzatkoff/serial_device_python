from __future__ import print_function, division
import serial
import os
import time
import platform
import atexit
import operator
import threading

try:
    from pkg_resources import get_distribution, DistributionNotFound
    _dist = get_distribution('serial_device2')
    # Normalize case for Windows systems
    dist_loc = os.path.normcase(_dist.location)
    here = os.path.normcase(__file__)
    if not here.startswith(os.path.join(dist_loc, 'serial_device2')):
        # not installed, but there is another version that *is*
        raise DistributionNotFound
except (ImportError,DistributionNotFound):
    __version__ = None
else:
    __version__ = _dist.version

DEBUG = False

class WriteFrequencyError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class SerialDevice(serial.Serial):
    '''
    SerialDevice inherits from serial.Serial and adds methods to it,
    like auto discovery of available serial ports in Linux, Windows, and
    Mac OS X.

    Example Usage:

    dev = SerialDevice() # Might automatically find device if one available
    # if it is not found automatically, specify port directly
    dev = SerialDevice(port='/dev/ttyUSB0') # Linux
    dev = SerialDevice(port='/dev/tty.usbmodem262471') # Mac OS X
    dev = SerialDevice(port='COM3') # Windows
    dev.get_device_info()
    '''
    TIMEOUT = 0.05
    WRITE_READ_DELAY = 0.05
    WRITE_WRITE_DELAY = 0.05

    def __init__(self, *args, **kwargs):
        try:
            self.debug = kwargs.pop('debug')
        except KeyError:
            self.debug = DEBUG
        if 'try_ports' in kwargs:
            try_ports = kwargs.pop('try_ports')
        else:
            try_ports = None
        try:
            self._write_read_delay = kwargs.pop('write_read_delay')
        except KeyError:
            self._write_read_delay = self.WRITE_READ_DELAY
        try:
            self._write_write_delay = kwargs.pop('write_write_delay')
        except KeyError:
            self._write_write_delay = self.WRITE_WRITE_DELAY
        try:
            self.device_name = kwargs.pop('device_name')
        except KeyError:
            self.device_name = ''

        if ('port' not in kwargs) or (kwargs['port'] is None):
            kwargs.update({'port': find_serial_device_port(try_ports=try_ports,debug=self.debug)})
        if 'timeout' not in kwargs:
            kwargs.update({'timeout': self.TIMEOUT})

        super(SerialDevice,self).__init__(*args,**kwargs)
        atexit.register(self._exit_serial_device)
        self._time_write_prev = time.time()
        self._lock = threading.Lock()

    def _exit_serial_device(self):
        '''
        Close the serial connection to provide some clean up.
        '''
        self.close()

    def _debug_print(self, *args):
        '''
        Prints debug info if self.debug == True.
        '''
        if self.debug:
            print(*args)

    def write_check_freq(self,cmd_str,delay_write=False,lock_=True):
        '''
        Use instead of self.write when you want to ensure that
        serial write commands do not happen too
        frequently. delay_write=True waits and then writes the serial
        command, delay_write=False raises WriteFrequencyError
        Exception if time between method calls is too short. Might
        remove delay_write option if it turns out to be
        unnecessary.
        '''
        time_now = time.time()
        time_since_write_prev = time_now - self._time_write_prev
        if time_since_write_prev < self._write_write_delay:
            delay_time_needed = self._write_write_delay - time_since_write_prev
            if delay_write:
                time.sleep(delay_time_needed)
            else:
                raise WriteFrequencyError(delay_time_needed)
        if lock_:
            self._lock.acquire()
        try:
            bytes_written = self.write(cmd_str)
            self._time_write_prev = time_now
        except (serial.writeTimeoutError):
            bytes_written = 0
        if lock_:
            self._lock.release()
        self._debug_print('command:', cmd_str)
        self._debug_print('bytes_written:', bytes_written)
        return bytes_written

    def write_read(self,cmd_str,use_readline=True,check_write_freq=True,max_read_attempts=1):
        '''
        A simple self.write followed by a self.readline with a
        delay set by write_read_delay when use_readline=True and
        check_write_freq=False. Setting check_write_freq=True ensures
        the write frequency is not too fast for the serial device to
        handle. Setting use_readline=False reads all response
        characters that are available instead of looking for the end
        of line character or timing out.

        max_read_attempts opens the possibility to read from the device again
        if the device did not have the response ready after the first read
        '''

        # First clear garbage.
        response = None
        with self._lock:
            chars_waiting = self.inWaiting()
            self.read(chars_waiting)
            if check_write_freq:
                bytes_written = self.write_check_freq(cmd_str,delay_write=True,lock_=False)
            else:
                bytes_written = self.write(cmd_str)
            if 0 < bytes_written:
                time.sleep(self._write_read_delay)
                response = self._read_with_retry(use_readline, max_read_attempts)
                self._debug_print('response:', response)

            return response

    def _read_with_retry(self,use_readline,max_read_attempts):
        '''
        Reads data from the device.  If there is no data, try
        reading again.
        '''
        for i in range(max_read_attempts):
            response = self._read(use_readline)
            if response:
                return response

            self._debug_print('no response -- retrying')

        return response

    def _read(self,use_readline):
        '''
        Reads data from the device
        '''
        if use_readline:
            response = self.readline()
        else:
            chars_waiting = self.inWaiting()
            self._debug_print('chars_waiting:', chars_waiting)
            response = self.read(chars_waiting)

        return response

    def get_device_info(self):
        '''
        Returns device name and serial port.
        '''
        serial_device_info = {'device_name' : self.device_name,
                              'port' : self.port,
                              }
        return serial_device_info


# device_names example:
# [{'port':'/dev/ttyACM0',
#   'device_name':'port0'},
#  {'port':'/dev/ttyACM1',
#   'device_name':'port1'}]
class SerialDevices(list):
    '''
    SerialDevices inherits from list and automatically populates it
    with SerialDevices on all available serial ports.

    Example Usage:

    devs = SerialDevices()  # Might automatically find all available devices
    # if they are not found automatically, specify ports to use
    devs = SerialDevices(use_ports=['/dev/ttyUSB0','/dev/ttyUSB1']) # Linux
    devs = SerialDevices(use_ports=['/dev/tty.usbmodem262471','/dev/tty.usbmodem262472']) # Mac OS X
    devs = SerialDevices(use_ports=['COM3','COM4']) # Windows
    devs.get_devices_info()
    devs.sort_by_port()
    dev = devs[0]
    dev.get_device_info()
    '''

    def __init__(self,*args,**kwargs):
        if 'debug' in kwargs:
            debug = kwargs['debug']
        else:
            debug = DEBUG
        if 'use_ports' in kwargs:
            use_ports = kwargs.pop('use_ports')
        else:
            use_ports = None
        if 'try_ports' in kwargs:
            try_ports = kwargs.pop('try_ports')
        else:
            try_ports = None
        if 'device_names' in kwargs:
            device_names = kwargs.pop('device_names')
        else:
            device_names = []

        if use_ports is not None:
            serial_device_ports = use_ports
        else:
            serial_device_ports = find_serial_device_ports(try_ports=try_ports,debug=debug)
        for port in serial_device_ports:
            kwargs.update({'port': port})
            self.append_device(*args,**kwargs)

        self._update_device_names(device_names)

    def _update_device_names(self,device_names):
        for name_dict in device_names:
            device_name = name_dict.pop('device_name')
            for device_index in range(len(self)):
                dev = self[device_index]
                match = True
                for key in name_dict.keys():
                    if name_dict[key] != getattr(dev,key):
                        match = False
                if match:
                    dev.device_name = str(device_name)

    def append_device(self,*args,**kwargs):
        '''
        Appends another SerialDevice.
        '''
        self.append(SerialDevice(*args,**kwargs))

    def get_devices_info(self):
        '''
        Get info for each SerialDevice.
        '''
        serial_devices_info = []
        for dev in self:
            serial_devices_info.append(dev.get_device_info())
        return serial_devices_info

    def sort_by_port(self,*args,**kwargs):
        '''
        Sort SerialDevices by port.
        '''
        kwargs['key'] = operator.attrgetter('port')
        self.sort(**kwargs)

    def get_by_port(self,port):
        '''
        Return a SerialDevice by port.
        '''
        for device_index in range(len(self)):
            dev = self[device_index]
            if dev.port == port:
                return dev

    def sort_by_device_name(self,*args,**kwargs):
        '''
        Sort SerialDevices by device names.
        '''
        kwargs['key'] = operator.attrgetter('device_name','port')
        self.sort(**kwargs)

    def get_by_device_name(self,device_name):
        '''
        Return a SerialDevice by its device name.
        '''
        dev_list = []
        for device_index in range(len(self)):
            dev = self[device_index]
            if dev.device_name == device_name:
                dev_list.append(dev)
        if len(dev_list) == 1:
            return dev_list[0]
        elif 1 < len(dev_list):
            return dev_list


# ----------------------------------------------------------------------------

def find_serial_device_ports(try_ports=None, debug=DEBUG):
    '''
    Returns a list of all available serial ports.
    Linux: /dev/ttyUSB* or /dev/ttyACM* or /dev/*arduino*
    Mac OS X: /dev/tty.* or /dev/cu.*
    Windows: COM*
    '''
    serial_device_ports = []
    os_type = platform.system()
    if os_type == 'Linux':
        serial_device_ports = os.listdir('{0}dev'.format(os.path.sep))
        serial_device_ports = [x for x in serial_device_ports if 'ttyUSB' in x or 'ttyACM' in x or 'arduino' in x]
        serial_device_ports = ['{0}dev{0}{1}'.format(os.path.sep,x) for x in serial_device_ports]
    elif os_type == 'Windows':
        import _winreg as winreg
        import itertools

        path = 'HARDWARE\\DEVICEMAP\\SERIALCOMM'
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        except WindowsError:
            key = None

        if key is not None:
            for i in itertools.count():
                try:
                    val = winreg.EnumValue(key, i)
                    # Only return USBSER devices
                    if 'USBSER' in val[0]:
                        serial_device_ports.append(str(val[1]))
                except EnvironmentError:
                    break
    elif os_type == 'Darwin':
        serial_device_ports = os.listdir('{0}dev'.format(os.path.sep))
        serial_device_ports = [x for x in serial_device_ports if 'tty.' in x or 'cu.' in x]
        serial_device_ports = ['{0}dev{0}{1}'.format(os.path.sep,x) for x in serial_device_ports]

    if try_ports is not None:
        serial_device_ports = list(set(try_ports) & set(serial_device_ports))

    serial_device_ports.sort()
    return serial_device_ports

def find_serial_device_port(try_ports=None, debug=DEBUG):
    '''
    Returns a serial port if one is available.
    '''
    serial_device_ports = find_serial_device_ports(try_ports)
    if len(serial_device_ports) == 1:
        return serial_device_ports[0]
    elif len(serial_device_ports) == 0:
        raise RuntimeError('Could not find any serial devices. Check connections and permissions.')
    else:
        raise RuntimeError('Found more than one serial device. Specify port.\n' + str(serial_device_ports))
