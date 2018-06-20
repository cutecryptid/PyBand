import argparse
import re
import sys
import time
sys.path.append('./lib')
from miband2 import MiBand2
from miband2time import MiBand2Time

def main():
    """ main func """
    parser = argparse.ArgumentParser()
    parser.add_argument('host', action='store', help='MAC of BT device')
    parser.add_argument('-t', action='store', type=float, default=3.0,
                        help='duration of each notification')

    parser.add_argument('--init', action='store_true', default=False)
    parser.add_argument('-n', '--notify', action='store_true', default=False)
    parser.add_argument('-hrm', '--heart', action='store_true', default=False)
    parser.add_argument('-act', '--activity', action='store_true', default=False)
    parser.add_argument('-sn', '--since', action='store', type=str, default="2018-04-06 00:00",
                        help='optional date to retrieve activity since, format "YYYY-MM-DD hh:mm"')
    parser.add_argument('-de', '--devevent', action='store_true', default=False)
    arg = parser.parse_args(sys.argv[1:])

    print('Connecting to ' + arg.host)
    band = MiBand2(arg.host, initialize=arg.init)

    if arg.notify:
        print("Sending message notification...")
        band.send_alert(b'\x01')
        time.sleep(arg.t)
        print("Sending phone notification...")
        band.send_alert(b'\x02')
        time.sleep(arg.t)
        print("Turning off notifications...")
        band.send_alert(b'\x00')

    if arg.heart:
        band.monitorHeartRate()

    if arg.activity:
        band.setLastSyncDate(arg.since)
        band.fetch_activity_data()

    if arg.devevent:
        band.event_listen()

    print("Disconnecting...")
    band.disconnect()
    del band

if __name__ == '__main__':
    main()
