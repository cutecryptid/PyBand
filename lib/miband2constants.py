UUID_SVC_MIBAND = "0000fee0-0000-1000-8000-00805f9b34fb"
UUID_SVC_MIBAND2 = "0000fee1-0000-1000-8000-00805f9b34fb"
UUID_CHAR_AUTH = "00000009-0000-3512-2118-0009af100700"
UUID_SVC_ALERT = "00001802-0000-1000-8000-00805f9b34fb"
UUID_CHAR_ALERT = "00002a06-0000-1000-8000-00805f9b34fb"
UUID_SVC_ALERT_NOTIFICATION = "00001811-0000-1000-8000-00805f9b34fb"
UUID_CHAR_NEW_ALERT = "00002a46-0000-1000-8000-00805f9b34fb"
UUID_SVC_HEART_RATE = "0000180d-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HRM_MEASURE = "00002a37-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HRM_CONTROL = "00002a39-0000-1000-8000-00805f9b34fb"
BASE_UUID = "0000fee1-0000-1000-8000-00805f9b34fb"
UUID_SERVICE_HEART_RATE = "0000180d-0000-1000-8000-00805f9b34fb"
UUID_SERVICE_FIRMWARE_SERVICE = "00001530-0000-3512-2118-0009af100700"
UUID_CHARACTERISTIC_FIRMWARE = "00001531-0000-3512-2118-0009af100700"
UUID_CHARACTERISTIC_FIRMWARE_DATA = "00001532-0000-3512-2118-0009af100700"
UUID_UNKNOWN_CHARACTERISTIC0 = "00000000-0000-3512-2118-0009af100700"
UUID_UNKNOWN_CHARACTERISTIC1 = "00000001-0000-3512-2118-0009af100700"
UUID_UNKNOWN_CHARACTERISTIC2 = "00000002-0000-3512-2118-0009af100700"

# Alarms, Display and other configuration.

UUID_CHARACTERISTIC_CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"
UUID_CHARACTERISTIC_3_CONFIGURATION = "00000003-0000-3512-2118-0009af100700"
UUID_CHARACTERISTIC_4_FETCH = "00000004-0000-3512-2118-0009af100700"
UUID_CHARACTERISTIC_5_ACTIVITY_DATA = "00000005-0000-3512-2118-0009af100700"
UUID_CHARACTERISTIC_6_BATTERY_INFO = "00000006-0000-3512-2118-0009af100700"
UUID_CHARACTERISTIC_7_REALTIME_STEPS = "00000007-0000-3512-2118-0009af100700"
UUID_CHARACTERISTIC_8_USER_SETTINGS = "00000008-0000-3512-2118-0009af100700"

UUID_CHARACTERISTIC_AUTH = "00000009-0000-3512-2118-0009af100700"
UUID_CHARACTERISTIC_DEVICEEVENT = "00000010-0000-3512-2118-0009af100700"

ALERT_LEVEL_NONE = 0
ALERT_LEVEL_MESSAGE = 1
ALERT_LEVEL_PHONE_CALL = 2
ALERT_LEVEL_VIBRATE_ONLY = 3

HRM_COMMAND = 0x15
HRM_MODE_SLEEP      = 0x00
HRM_MODE_CONTINUOUS = 0x01
HRM_MODE_ONE_SHOT   = 0x02

CCCD_UUID = 0x2902

RESPONSE = 0x10

SUCCESS = 0x01
COMMAND_ACTIVITY_DATA_START_DATE = 0x01
COMMAND_ACTIVITY_DATA_TYPE_ACTIVTY = 0x01
COMMAND_ACTIVITY_DATA_TYPE_UNKNOWN_2 = 0x02
COMMAND_ACTIVITY_DATA_XXX_DATE = 0x02

COMMAND_ENABLE_HR_SLEEP_MEASUREMENT = b'\x15\x00\x01'
COMMAND_DISABLE_HR_SLEEP_MEASUREMENT = b'\x15\x00\x00'

COMMAND_SET_PERIODIC_HR_MEASUREMENT_INTERVAL = 0x14

ALARM_MON = 1
ALARM_TUE = 2
ALARM_WED = 4
ALARM_THU = 8
ALARM_FRI = 16
ALARM_SAT = 32
ALARM_SUN = 64

COMMAND_FIRMWARE_REBOOT = 0x05