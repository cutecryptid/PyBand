from bluepy.btle import Scanner, DefaultDelegate
from miband2 import MiBand2, ActivityDelegate

def main():
    sc = Scanner()
    devs = sc.scan(5)

    if (len(devs) > 0):
        mb2 = MiBand2(devs[0])
    else:
        exit()

    mb2.authenticate()

    mb2.setDelegate(ActivityDelegate(mb2))

    mb2.req_battery()

    print(mb2.battery_info)


if __name__ == "__main__":
    main()
