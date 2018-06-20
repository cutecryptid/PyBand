# Clepito MB2 Server API

## Intended Behaviour
API runs at system boot and continuously scans for near devices. Devices are not reported until requested.

API allows to:
  * Check for nearby MiBand2s and report connection data such as signal, address and connection/registration status.
  * Check data of a registered device, connect to it, disconnect from it and unregister the device.
  * Check a registered device's alarms, add new alarms up to 5 and clear all alarms.
  * Check a single alarm data, modify it or delete it
  * Check configuration presets and apply them, as well as rebooting the device.
  * Fetch and/or check a registered device's activity data
  * Check the user data paired to a single device, pair to a new user or unpair an old user.

API is secured through Auth Tokens, to operate the API, the app needs to provide a valid email and password to obtain
an auth token and then store it to query any of the other endpoints. The token can be passed as a url parameter, a body
parameter or a header parameter 'token'. The endpoints marked with an asterisk * do not require this token parameter.

Take in account that most of the operations need to have the device phisically near to the server, registered and/or
connected to it. These requirements are specified in each endpoint method.

## Endpoints
### index (/) *
#### GET
**Device Requirements:** None
**Response:** 'env': Environment config, 'api_version': API version, 'app': APP Name

#### DELETE
**Device Requirements:** None
**Body parameters:** 'reboot_key': Reboot key specified in the server configuration file
**Action:** If reboot_key matches, reboots the API server 

### api_authenticate (/authenticate/) *
#### POST
**Device Requirements:** None
**Body Parameters:** 'email': asp.net user email, 'pwd_hash': asp.net password hash
**Action:** Validate email and password hash to generate an auth token valid for 24 hours
**Response:** 'token': auth token, valid for 24hours, 'aspuser_id': asp.net user id

### devices (/devices/)
#### GET
**Device Requirements:** Nearby Devices
**Response:** List of nearby devices in the form of 'address': device address, 'signal': device signal
'registered': device registered status (0 or 1), 'connected': device connection status (0 or 1),
'dev_id': internal device registration id, -1 if not registered, 'battery': battery level percentage

#### POST
**Device Requirements:** Nearby Device
**Body Parameters:** 'address': MiBand2 physical address
**Action:** Initialize and register device, assigning a registration id to it
**Response:** 'dev_id': device's registration id, 'registered': device registered status (0 or 1)

### device (/devices/<int:dev_id>/)
#### GET
**Device Requirements:** Optionally Nearby Device, Optionally Connected, Optionally Registered
**Response:** Displays details of a registered device identified by <dev_id> in the form of
'addr': device address, 'signal': device signal 'registered': device registered status (0 or 1),
'connected': device connection status (0 or 1), 'dev_id': internal device registration id, -1 if not registered
'visible': 0 if device isn't nearby, 1 if it is

#### PUT
**Device Requirements:** Nearby Device, Registered Device
**Body Parameters:** 'action': 'connect'/'disconnect'
**Action:** Establishes or breaks a connection between the server and the MiBand identified by <dev_id>
**Response:** 'connected': connection status (0 or 1), 'dev_id': device's registration id

#### DELETE
**Device Requirements:** Nearby Device, Registered Device, Connected Device
**Action:** Unregister the MiBand and reset it, setting the registered field to 0, for integrity reasons, data is never deleted
**Response:** 'registered': device's registration status (1 or 0), 'dev_id': device's registration id

### alarms (/devices/<int:dev_id>/alarms/)
#### GET
**Device Requirements:** None
**Response:** Displays the device's (identified by <dev_id>) alarms in the form of 'id': general alarm id,
'dev_id': device registration id, 'index': device's alarm index, 'hour': alarm scheduled hour, 'minute':
alarm scheduled minute, 'enabled': status of the alarm (0 or 1), 'repetition': 8-bit binary mask to tell the alarm
to ring on specific weekdays. To not repeat the alarm set the leftmost bit to 1 and the rest to 0 (128), to
repeat the alarm set the leftmost bit to 0 and set the repetition days by setting each of the other bits to 1
in reverse order of signficance (rightmost being mondays and 7th bit from the right being sundays)

#### POST
**Device Requirements:** Nearby Device, Registered Device, Connected Device
**Body Parameters:** 'hour': (mandatory) scheduled alarm hour, 'minute': (mandatory) scheduled alarm minute,
'enabled': (optional, default 1) 1 to enable the alarm 0 to disable it, 'repetition': (optional, default 128) 8-bit binary mask
to tell the alarm to ring on specific weekdays. To not repeat the alarm set the leftmost bit to 1 and the rest to 0 (128), to
repeat the alarm set the leftmost bit to 0 and set the repetition days by setting each of the other bits to 1
in reverse order of signficance (rightmost being mondays and 7th bit from the right being sundays)
**Action:** Add a new alarm to the device identified by <dev_id> with the specified parameters. Only hour and minute are mandatory.
**Response:** Device alarm in the form of 'id': general alarm id, 'dev_id': device registration id,
'index': device's alarm index, 'hour': alarm scheduled hour, 'minute': alarm scheduled minute,
'enabled': status of the alarm (0 or 1), 'repetition': 8-bit binary mask to tell the alarm
to ring on specific weekdays.

#### DELETE
**Device Requirements:** Nearby Device, Registered Device, Connected Device
**Action:** Delete all alarms stored on device
**Response:** 'alarms_deleted': 1 or 0 if all alarms were deleted, 'dev_id': device's id

### alarm (/devices/<int:dev_id>/alarm/<int:alarm_index>/)
#### GET
**Device Requirements:** None
**Response:** Displays the device's (identified by <dev_id>) alarm at index <alarm_index>
in the form of 'id': general alarm id, 'dev_id': device registration id, 'index': device's alarm index,
'hour': alarm scheduled hour, 'minute': alarm scheduled minute, 'enabled': status of the alarm (0 or 1),
'repetition': 8-bit binary mask to tell the alarm to ring on specific weekdays.

#### PUT
**Device Requirements:** Nearby Device, Registered Device, Connected Device
**Body Parameters:** 'hour': (optional) scheduled alarm hour, 'minute': (optional) scheduled alarm minute,
'enabled': (optional) 1 to enable the alarm 0 to disable it, 'repetition': (optional) 8-bit binary mask
to tell the alarm to ring on specific weekdays. To not repeat the alarm set the leftmost bit to 1 and the rest to 0 (128), to
repeat the alarm set the leftmost bit to 0 and set the repetition days by setting each of the other bits to 1
in reverse order of signficance (rightmost being mondays and 7th bit from the right being sundays)
**Action:** Modify the device's (identified by <dev_id>) alarm at index <alarm_index>
**Response:** Device alarm in the form of 'id': general alarm id, 'dev_id': device registration id,
'index': device's alarm index, 'hour': alarm scheduled hour, 'minute': alarm scheduled minute,
'enabled': status of the alarm (0 or 1), 'repetition': 8-bit binary mask to tell the alarm
to ring on specific weekdays.

#### DELETE
**Device Requirements:** Nearby Device, Registered Device, Connected Device
**Action:** Delete device's (identified by <dev_id>) alarm at index <alarm_index>
**Response:** 'alarm_deleted': 1 or 0 if all alarms were deleted, 'dev_id': device's id

### config (/devices/<int:dev_id>/config/)
#### GET
**Device Requirements:** None
**Response:** Displays the available configuration presets for the device

#### PUT
**Device Requirements:** Nearby Device, Registered Device, Connected Device
**Body Parameters:** 'preset': Preset name
**Action:** Apply configuration preset to the device identified by <dev_id>
**Response:** 'configured': 1 or 0 if the device was correctly configured or not, 'dev_id': device's id
'preset': the preset applied to the device

#### PATCH
**Device Requirements:** Nearby Device, Registered Device, Connected Device
**Action:** Reboots the device identified by <dev_id>
**Response:** 'rebooted': 1 or 0 if all alarms were deleted, 'dev_id': device's id

### activity (/devices/<int:dev_id>/activity/)
#### GET
**Device Requirements:** None, if fetch parameter is used then Nearby Device, Registered Device
**URL Parameters:** 'fetch': (optional, default 0) if 1 the server will fetch the activity data from device (and connect to it if it isn't connected)
form the device, device need to be nearby, registered and connected before doing so,
'since': (optional, default first registered frame on device) datetime in format "YYYY-MM-DD hh:mm" to display activity since,
'until': (optional, default now) datetime in format "YYYY-MM-DD hh:mm" to display activity until
**Response:** Displays the stored activity data for the device in the form of a list of
'date': activity frame datetime, 'type': numeric id of activity type, 'steps': frame steps,
'intensity': activity frame intensity, 'heartrate': frame heartrate, 'dev_id': id of the
device that registered the data frame, 'user_id': user wearing the device at the
moment of registering the frame

### device_user (/devices/<int:dev_id>/user/)
#### GET
**Device Requirements:** None
**Response:** Displays user data associated to the device identified by <dev_id> in the form
'id': user id, 'name': first name, 'surname': last name, 'email': user email, 'weight': user weight,
'height': user height, 'center': user center of residence, 'dev_id': device id, 'alias': autogenerated user alias

#### POST
**Device Requirements:** Nearby Device, Registered Device, Connected Device
**Body parameters:** 'user_id': (mandatory) internal user id, 'position': (mandatory) wrist
in which the user carries the device ('left', 'right')
**Action:** Pair the registered and connected device identified by <dev_id> to user identified by 'user_id'
**Response:** 'linked': 1 or 0 if device was correctly paired to user or not, 'dev_id': device's id,
'user_id': paired user's id, 'position': registered position for the user's MiBand2

#### DELETE
**Device Requirements:** None
**Action:** Unpair the identified by <dev_id> to user identified by 'user_id'
**Response:** 'linked': 0 or 1 if device was correctly unpaired to user or not, 'dev_id': device's id
